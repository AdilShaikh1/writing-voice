"""Find writing-voice candidates in Markdown, HTML or text files.

The script reports colon reveals, tacked-on "-ing" clauses, this style's own banned words, first-person narrative in
READMEs and confidential terms from a per-project list. Grammar hits are candidates for a human (or the model) to
judge in context, and the script never edits anything. Prose checks skip code (fenced, ~~~, indented and inline
code, <pre>, <code>, <script>, <style>), HTML comments, YAML front matter, quoted text and bold run-in labels.

The confidential-term scan also reads code, attributes and comments. It is built to catch accidental leaks in normal
writing. It reads through Markdown and HTML markup, entities, URL encoding, invisible format characters, accents,
dash and apostrophe variants and fullwidth letters. It matches a term written with spaces, "-", "_", "," or an
apostrophe between its parts, with or without a "#" before a number ("Project #7", "Project 7") or separators
around "&" ("AT&T", "AT & T"), and its plural. It doesn't match "&" written as "and" or dropped from a URL slug
("johnson-varnley" for "Johnson & Varnley"). It is not a defence against deliberate disguise such as look-alike
letters from other alphabets. With a term list, grammar hits print only file, line and kind, never text from the
file, so the report can't print a term even when the scan misses one.

File names are printed as given, and "**" skips dot folders. The scan doesn't match "Zeta Corp" written as one
run-together word ("zetacorp", "ZetaCorp") or with a dot or slash between its parts ("zeta.corp", "zeta/corp").
It also misses a one-word term split by a line-end hyphen ("Kestrel-" at the end of one line, "net" on the next),
and a note glued to a term-file line without spaces ("Zeta Corp/client"). Rarer forms it misses are a
double-encoded or Latin-1 percent escape ("zeta%2520corp", "Jos%E9"), a "+" in a relative link's path, a NUL byte
inside a word, and a space or a second "#" after a number sign ("Project # 7").

Usage:  python check_voice.py [--terms INTERNAL/nda_terms.txt] -- FILE_OR_GLOB...
        python check_voice.py --self-test

The script exits 0 when no confidential term is found, since grammar hits are only advice. It exits 1 when a
confidential term is found or the self-test fails. It exits 2 on a usage error, such as no files given, a file or
pattern that can't be read, --terms given twice or empty, a term file with no usable terms or with a note on a term
line, or --self-test given with other arguments. A pre-push check can then gate on it without blocking on judgment
calls.
"""
import argparse
import bisect
import glob
import html
import re
import sys
import time
import unicodedata
import urllib.parse
from pathlib import Path

# this skill's own bans; the general AI-pattern word list belongs to the no-ai-slop skill and isn't repeated here
BANNED_WORDS = re.compile(r"\b(builders?|put\s+together)\b", re.I)
# words ending in "ing" that are not participles, or that introduce a list rather than a second claim
NOT_PARTICIPLES = {"including", "according", "during", "something", "nothing", "anything", "everything", "thing",
                   "string", "bring", "spring", "morning", "evening", "ring", "wing", "ceiling", "king", "sibling"}
# first person in a README; "I" followed by "/" or a word character is "I/O" or a Roman numeral, not a pronoun
FIRST_PERSON = re.compile(r"\b(?:I(?![/\w])|I'm|I've|I'd|[Mm]y|[Mm]e|[Mm]ine|[Mm]yself|[Ww]e|[Oo]urs?|us)\b")
# "I" after one of these words is a Roman numeral ("Phase I", "Type I"), not the pronoun
ROMAN_NUMERAL_LEADS = {"phase", "part", "type", "class", "level", "stage", "chapter", "mark", "series", "tier",
                       "appendix", "section", "volume", "gen"}
PREVIOUS_WORD_CHARS = 40   # how far back the Roman-numeral check looks for the word before "I"
LIST_MARKER = re.compile(r"^\s*(?:[-*+]|\d+\.|>)\s+")
SENTENCE_END = re.compile(r"[.!?][\"')\]*_]*\s")
MAX_LABEL_WORDS = 2   # "Fixed:", "Note:", "Next steps:" at the start of a line are labels, not reveals
# a short clause that starts with one of these is a reveal ("The fix: …", "Best part: …"), not a label
REVEAL_LEAD_WORDS = {"the", "a", "an", "our", "my", "this", "its", "best", "worst", "key", "real", "big", "one"}
SNIPPET_CHARS = 50
MAX_CLAUSE_CHARS = 300   # a colon check reads at most this much of the clause before it, so long lines stay linear
LEADING_SPACE = re.compile(r"\s*")
MAX_QUOTE_CHARS = 300   # a quote longer than this, or spanning lines, is treated as prose
MAX_TAG_CHARS = 4096
# a real tag or <!doctype>. "a < b > c" survives. The bound and the ban on "<" inside keep a stray "<" from scanning
# the rest of the file for a ">" (slow); the term scan's keep-tags view covers a stray "<" that does reach one
HTML_TAG = re.compile(rf"<[!/?]?[A-Za-z](?:[^<>\"']|\"[^\"<]*\"|'[^'<]*'){{0,{MAX_TAG_CHARS}}}>")   # quoted ">" ok
# in a page, these tags end a block, so minified HTML doesn't run two paragraphs into one sentence
HTML_BLOCK_TAG = re.compile(rf"</?(?:p|div|li|ul|ol|h[1-6]|hr|tr|td|th|table|section|article|header|footer|nav|main"
                            rf"|blockquote|figure|figcaption)\b[^<>]{{0,{MAX_TAG_CHARS}}}>", re.I)
SNIPPET_CLAUSE_CHARS = 80   # a snippet shows at most this much of the clause before a colon
CODE_SPAN = re.compile(r"`[^`\n]*`")
FENCED_CODE = r"(```|~~~).*?\1"
CODE_BLOCK_OR_SPAN = re.compile(FENCED_CODE + r"|`[^`\n]*`", re.S)
CODE_ELEMENT_OPENER = re.compile(r"<(pre|code|script|style)\b", re.I)
LABEL_LEAD_MARKS = "(\"'“‘["   # "(The fix: …)" is led by "the", not by "(the"

# The term view: the text as a reader sees it, built to catch accidental leaks in normal writing (not deliberate
# disguise such as look-alike letters). Entities that decode to a newline would shift every later line, so they
# become a space first, with or without the closing ";".
NEWLINE_ENTITIES = re.compile(r"&#0*10(?![0-9]);?|&#x0*a(?![0-9a-f]);?|&NewLine;", re.I)
# a footnote number: "Zeta<sup>1</sup> Corp", or the linked form renderers emit, <sup><a href="#fn1">1</a></sup>
SUPERSCRIPT = re.compile(r"<sup\b[^<>]{0,200}>(?:<a\b[^<>]{0,500}>)?[^<\n]{0,20}(?:</a>)?</sup>", re.I)
MAX_LINK_TARGET_CHARS = 2048
# "[Zeta](url) Corp" reads "Zeta Corp"; one level of parentheses inside the URL, and a bound for speed
MARKDOWN_LINK_TARGET = re.compile(rf"\]\((?:[^()\n]|\([^()\n]*\)){{0,{MAX_LINK_TARGET_CHARS}}}\)")
FOOTNOTE_MARKER = re.compile(r"\[\^[^\]\n]{0,100}\]")                 # "Zeta[^1] Corp"
REFERENCE_LABEL = re.compile(r"\]\[[^\]\n]{0,100}\]")                  # "[Zeta][zc] Corp"
BLOCKQUOTE_PREFIX = re.compile(r"(?m)^(?:[ \t]*>)+")                  # "> > Zeta", nested quotes too
# Markdown "QX\-90" and "zeta\_corp" render without the backslash, and "Zeta\" + newline is a hard line break
ESCAPE_BACKSLASH = re.compile(r"\\(?=[^\w \t]|_)")
URL = re.compile(r"(?:https?://|www\.)[^\s<>\"'()\[\]]+")   # decoded in full: "?q=zeta+corp" reads "zeta corp"
PERCENT_ESCAPE = re.compile(r"(?:%[0-9A-F]{2})+", re.I)     # decoded anywhere, such as "Jos%C3%A9" in a relative link
QUERY_STRING = re.compile(r"\?[\w%.~-]+=[^\s<>\"'()\[\]]*")   # "/search?q=zeta+corp" in a relative link
APOSTROPHES = "\u2018\u2019\u02bc"                 # typographic apostrophes, read as "'"
EMPHASIS_AND_BRACKETS = "*~`[]()"                  # markers and brackets in or around a term, read as the fill
MINUS_SIGN = "\u2212"                              # a math symbol to Unicode, but pasted in place of a hyphen
# NFKD would turn these into letters or digits that touch the term ("Kestrelnet\u2122" reads "KestrelnetTM"), so
# they become the fill first: trademark and service marks, ordinal indicators and superscript digits. The
# registered sign stays whole under NFKD, but it would still touch a term written as "Kestrelnet\u00ae"
BEFORE_NFKD_FILL = "\u00ae\u2122\u2120\u00aa\u00ba\u00b9\u00b2\u00b3" + "".join(map(chr, range(0x2070, 0x207A)))
# letters NFKD leaves whole, folded like accents ("\u0141ukasz" reads "Lukasz", "Gro\u00dfmann" reads "Grossmann")
STROKE_FOLDS = str.maketrans({"\u00f8": "o", "\u00d8": "O", "\u0142": "l", "\u0141": "L", "\u0111": "d",
                              "\u0110": "D", "\u0127": "h", "\u0126": "H", "\u00df": "ss", "\u00e6": "ae",
                              "\u00c6": "AE", "\u0153": "oe", "\u0152": "OE", "\u00f0": "d", "\u00d0": "D",
                              "\u00fe": "th", "\u00de": "Th", "\u0131": "i", "\u1e9e": "SS"})
# the code points the tables cover: the BMP, the tag characters and the variation selectors supplement
TABLE_CODE_POINTS = [*range(0x10000), *range(0xE0000, 0xE0080), *range(0xE0100, 0xE01F0)]


def unicode_tables():
    """(format characters, dashes, nonspacing marks). Format (Cf) characters render as nothing, dashes (Pd) read
    as "-", and nonspacing marks (Mn) are accents, the combining grapheme joiner and the variation selectors."""
    format_characters, nonspacing_marks = [], []
    dashes = [MINUS_SIGN]
    for code_point in TABLE_CODE_POINTS:
        category = unicodedata.category(chr(code_point))
        if category == "Cf":
            format_characters.append(chr(code_point))
        elif category == "Pd":
            dashes.append(chr(code_point))
        elif category == "Mn":
            nonspacing_marks.append(chr(code_point))
    return format_characters, dashes, nonspacing_marks


FORMAT_CHARACTERS, DASHES, NONSPACING_MARKS = unicode_tables()
# after NFKD splits "é" into "e" and an accent, this deletes the accent: "José Pérez" reads "Jose Perez"
FOLD_ACCENTS = {ord(mark): None for mark in NONSPACING_MARKS}


def view_translation(fill):
    """The character map for one term view: markers and invisible characters become fill, dashes "-"."""
    table = {ord(character): fill for character in [*EMPHASIS_AND_BRACKETS, *FORMAT_CHARACTERS]}
    table.update({ord(apostrophe): "'" for apostrophe in APOSTROPHES})
    table.update({ord(dash): "-" for dash in DASHES})
    return table


VIEW_TRANSLATIONS = {fill: view_translation(fill) for fill in (" ", "")}
BEFORE_NFKD_TRANSLATIONS = {fill: {ord(character): fill for character in BEFORE_NFKD_FILL} for fill in (" ", "")}
# between a term's parts: spaces, line breaks, "-", "_", "," ("Acme, Inc.") or a "#" before a digit, so
# "Project #7", "Project 7" and "project-7" all match each other. An apostrophe separates too, because it is
# often typed as an accent or a backtick ("O'Varnley", "O´Varnley" and "O`Varnley" all match)
TERM_PART_SEPARATOR = r"(?:[\s,_'-]|#(?=\d))+"
# "AT & T", "AT&T" and "AT_&_T" are one name, so any separators around "&" are optional. The lookbehind starts a
# match only at the first separator of a run, which keeps a long run of separators linear
AMPERSAND_SPACING = re.compile(r"(?<![\s,_'-])[\s,_'-]*&[\s,_'-]*")
PLURAL_ENDING = r"(?:e?s)?"
MIN_PLURAL_PART_CHARS = 3   # a short last word takes no plural, so "Li" doesn't match "lies"
# term file: "KX-200   # charger model" ends in a comment. List markers (Word, Docs and Slack bullets too), wrapping
# quotes and a trailing "," ";" or "." are pasted-in decoration. A note on the line, a letter list marker or an odd
# first or last character would make the term never match, so the line is a usage error instead. A "#" before a
# digit is part of the term ("Project #7"). An unspaced en dash stays, because it is a hyphen pasted from a word
# processor ("KX\u2013200")
# a lookbehind, not "\s+#": a long run of spaces would make "\s+" retry from every space (quadratic)
INLINE_COMMENT = re.compile(r"(?<=\s)#(?:\s.*)?$")
LIST_MARKER_PREFIX = re.compile("^(?:[-*+\u2022\u25e6\u25aa\u2023]|\\d+[.)])\\s+")
WRAPPING_QUOTES = re.compile("^[\"'\u201c\u2018](.+)[\"'\u201d\u2019]$")
TERM_DECORATION_END = ",;."   # a trailing comma, semicolon or period, inside or outside wrapping quotes
# a note: brackets, a colon, semicolon, tab, table bar, comma or em dash; an arrow or "//" ("->", "=>", "<-", an
# arrow sign) anywhere; a spaced run of punctuation ("Zeta Corp - note", " ... ") other than "&" ("AT & T");
# "--"; a "#" touching a letter; two spaces inside the term; or two "&" with only separators between them, which no
# name has and which would make the scan backtrack on a long run of spaces
TERM_NOTE = re.compile(r"[\t|(),:;\[\]\u2014\u2190-\u21ff]|->|=>|<-|//|\s[^\w\s&]+\s|--|#[^\W\d]|\S {2,}\S"
                       r"|&[\s,_'-]*&")
# line breaks that "\n" doesn't cover: each one ends a term, but the line number still counts only "\n"
LINE_BREAKS_INSIDE_LINE = re.compile("[\x0b\x0c\x1c-\x1e\x85\u2028\u2029]")
LETTER_LIST_MARKER = re.compile(r"^(?:[a-z]|[ivx]{1,4})[.)]\s")   # "a. Zeta Corp", "iv) Zeta Corp"
TERM_START = re.compile(r"^[\w@.$]")
TERM_END = re.compile(r"[\w.+#&'\u2122\u2120\u00ae\u00b9\u00b2\u00b3]$")
LONG_WORD_CHARS = 30000      # self-test: one word this long takes about 5 s without the \b fix, a few ms with it
MAX_LONG_WORD_SECONDS = 2
EXIT_CLEAN, EXIT_TERM_FOUND, EXIT_USAGE = 0, 1, 2
EXIT_SELF_TEST_FAILED = 1


def blank_text(text):
    """The text as spaces. Its newlines stay, so line numbers stay right."""
    return re.sub(r"[^\n]", " ", text)


def blank_out(match):
    """Replace a skipped region with spaces, keeping its newlines."""
    return blank_text(match.group(0))


def blank_inside_quotes(match):
    """Blank a quote's words but keep its marks, so the colon check still sees that a quote follows."""
    quote = match.group(0)
    return quote[0] + blank_text(quote[1:-1]) + quote[-1]


def replace_closed_comments(text, replacement):
    """The text with each closed <!-- ... --> replaced by replacement(comment). A linear scan: an unclosed "<!--"
    and everything after it stay, so a stray one can neither make the scan quadratic nor swallow the file."""
    pieces, position = [], 0
    while True:
        start = text.find("<!--", position)
        end = text.find("-->", start + 4) if start != -1 else -1
        if end == -1:
            pieces.append(text[position:])
            return "".join(pieces)
        pieces += [text[position:start], replacement(text[start:end + 3])]
        position = end + 3


def blank_closed_elements(text):
    """The text with each closed <pre>, <code>, <script> or <style> element blanked. A linear scan: once one has no
    closing tag, later openers of that name are skipped, so an unclosed one can't make the scan quadratic."""
    pieces, position, unclosed = [], 0, set()
    for opener in CODE_ELEMENT_OPENER.finditer(text):
        name = opener.group(1).lower()
        if opener.start() < position or name in unclosed:
            continue
        closer = re.compile(rf"</{name}>", re.I).search(text, opener.end())
        if not closer:
            unclosed.add(name)
            continue
        pieces += [text[position:opener.start()], blank_text(text[opener.start():closer.end()])]
        position = closer.end()
    return "".join(pieces) + text[position:]


def decode_urls(view):
    """URLs as a reader would type them. A link or a relative link's query is decoded in full ("?q=zeta+corp"), and a
    percent escape is decoded anywhere. A decoded newline becomes a space, so later lines don't shift."""
    def decode(url):
        return urllib.parse.unquote_plus(url.group(0)).replace("\n", " ")
    view = QUERY_STRING.sub(decode, URL.sub(decode, view))
    return PERCENT_ESCAPE.sub(lambda escape: urllib.parse.unquote(escape.group(0)).replace("\n", " "), view)


def line_number_finder(text):
    """A function mapping a character offset in text to its 1-based line number."""
    line_starts = [0] + [match.end() for match in re.finditer("\n", text)]
    return lambda offset: bisect.bisect_right(line_starts, offset)


def blank_indented_code(text):
    """Markdown indented code: 4+ spaces or a tab after a blank line (or after more indented code)."""
    lines, in_code = text.split("\n"), False
    for index, line in enumerate(lines):
        previous_blank = index == 0 or not lines[index - 1].strip()
        if re.match(r"( {4}|\t)", line) and (previous_blank or in_code):
            lines[index], in_code = " " * len(line), True
        elif line.strip():
            in_code = False
    return "\n".join(lines)


def prose_only(text, is_html):
    """The text with code, labels, comments and tags blanked out (same length and line count as the input)."""
    text = re.sub(r"\A---\n.*?\n---\n", blank_out, text, flags=re.S)             # YAML front matter
    text = re.sub(FENCED_CODE, blank_out, text, flags=re.S)                       # fenced code blocks
    if not is_html:
        text = blank_indented_code(text)
    text = CODE_SPAN.sub(blank_out, text)                                        # inline code
    text = replace_closed_comments(text, blank_text)
    text = blank_closed_elements(text)
    text = re.sub(r"\*\*[^*\n]+(?::\*\*|\*\*:)|__[^_\n]+(?::__|__:)", blank_out, text)   # bold run-in labels
    text = re.sub(r"<(strong|b)>[^<]*:</\1>|<(strong|b)>[^<]*</\2>:", blank_out, text, flags=re.I)
    if is_html:   # "." plus spaces: same length, and the colon check sees a sentence end between blocks
        text = HTML_BLOCK_TAG.sub(lambda block_tag: "." + blank_out(block_tag)[1:], text)
    text = HTML_TAG.sub(blank_out, text)
    # quoted text is someone else's words (often a quoted bad example), so grammar checks skip it; one line max
    quoted = (rf"\"[^\"\n]{{1,{MAX_QUOTE_CHARS}}}\"|“[^”\n]{{1,{MAX_QUOTE_CHARS}}}”"
              rf"|&quot;[^\n]{{1,{MAX_QUOTE_CHARS}}}?&quot;|&ldquo;[^\n]{{1,{MAX_QUOTE_CHARS}}}?&rdquo;")
    return re.sub(quoted, blank_inside_quotes, text)


def join_soft_wraps(prose):
    """Replace newlines inside a paragraph with spaces (same length), so a sentence wrapped over lines is checked
    whole. A newline is kept after a heading, and before a blank line, a bulleted or numbered list item, a heading
    or a table row."""
    return re.sub(r"(?m)^(?![ \t]*#)(.*\S)\n(?![ \t]*\d+[.)]\s)(?=[ \t]*[^\s\-*+>|#])", r"\1 ", prose)


def colon_reveals(line):
    """[(offset, snippet)] for colons inside a sentence that introduce its real content."""
    if line.lstrip().startswith("|"):
        return []   # table row
    sentence_ends = [match.end() for match in SENTENCE_END.finditer(line)]   # computed once: linear in the line
    hits = []
    # a colon before "//" (a URL), a digit (a time) or a path separator (C:\, a:/b) is not a reveal
    for colon in re.finditer(r":(?!//)(?!\d)(?![\\/])", line):
        # every slice below is bounded, so a minified page with thousands of colons on one line stays linear
        after_start = LEADING_SPACE.match(line, colon.end()).end()
        after = line[after_start:after_start + SNIPPET_CHARS]
        if not after or not (after[0].isalnum() or after[0] == "("):
            continue   # colon ends the line (a list intro) or is followed by a quote, now blanked, or punctuation
        # only the 2 characters before the colon matter, which keeps the loop linear on long minified lines
        if re.search(r"(?:^|[\s\"'(])[A-Za-z]$", line[max(0, colon.start() - 2):colon.start()]):
            continue   # a drive letter standing alone, as in C:\Tools (not the "d" of "signal_2d:")
        previous_end = bisect.bisect_right(sentence_ends, colon.start()) - 1
        at_line_start = previous_end < 0
        start = 0 if at_line_start else sentence_ends[previous_end]
        clause = line[max(start, colon.start() - MAX_CLAUSE_CHARS):colon.start()]
        if at_line_start:
            clause = LIST_MARKER.sub("", clause)
        words = [word for word in clause.split() if any(character.isalnum() for character in word)]   # not quote marks
        is_label = not words or (len(words) <= MAX_LABEL_WORDS
                                 and words[0].lower().lstrip(LABEL_LEAD_MARKS) not in REVEAL_LEAD_WORDS)
        if not is_label:
            shown_clause = clause.strip()
            if len(shown_clause) > SNIPPET_CLAUSE_CHARS:
                shown_clause = "…" + shown_clause[-SNIPPET_CLAUSE_CHARS:]
            hits.append((start, shown_clause + ": " + after.rstrip()))
    return hits


def trailing_participles(line):
    """[(offset, snippet)] for ", <word>ing" clauses hung off the end of a claim. An -ing word followed by a comma,
    "and", "or" or a table bar is a list item ("ingest, logging"), and so is one that follows another -ing word."""
    if line.lstrip().startswith("|"):
        return []
    # the leading \b makes each attempt start at a word start; without it one long word takes quadratic time
    clause_starts = re.finditer(r"\b(\w+),\s+(?:\w+ly\s+)?(\w+ing)\b(?!\s*[,|]|\s+(?:and|or)\b)", line)
    return [(match.start(), match.group(0)) for match in clause_starts
            if match.group(2).lower() not in NOT_PARTICIPLES and not match.group(1).lower().endswith("ing")]


def term_view(text, fill, keep_tags=False):
    """The text as a reader sees it, for matching terms. Entities and URLs are decoded. Comments, tags (unless
    keep_tags), footnote numbers, reference labels, emphasis and code markers, brackets and invisible format
    characters become fill (" " or ""). Link targets (unless keep_tags), quote markers, escape backslashes and accents
    are dropped, and apostrophes, dashes and fullwidth letters are normalised. Every step keeps the newline count,
    so an offset maps to the right line."""
    def fill_region(region):
        return fill + "\n" * region.count("\n")
    def fill_match(match):
        return fill_region(match.group(0))
    view = html.unescape(NEWLINE_ENTITIES.sub(" ", text))
    # a "<!--" in code is code, not a comment start, so it must not swallow the paragraphs up to a later "-->"
    view = CODE_BLOCK_OR_SPAN.sub(lambda code: code.group(0).replace("<!--", "    "), view)
    view = SUPERSCRIPT.sub(fill_match, view)
    if not keep_tags:   # the keep-tags view also keeps link targets, so their URL encoding is read
        view = HTML_TAG.sub(fill_match, replace_closed_comments(view, fill_region))
        view = MARKDOWN_LINK_TARGET.sub(" ", view)
    view = REFERENCE_LABEL.sub(fill, FOOTNOTE_MARKER.sub(fill, decode_urls(view)))
    view = ESCAPE_BACKSLASH.sub("", BLOCKQUOTE_PREFIX.sub(" ", view)).replace("==", fill)
    # NFKD maps fullwidth letters to ASCII and splits accents off, FOLD_ACCENTS deletes them and STROKE_FOLDS does
    # the letters NFKD leaves whole
    view = unicodedata.normalize("NFKD", view.translate(BEFORE_NFKD_TRANSLATIONS[fill]))
    view = view.translate(FOLD_ACCENTS).translate(STROKE_FOLDS)
    return view.translate(VIEW_TRANSLATIONS[fill])   # after NFKD, which maps U+2011 to U+2010


def term_patterns(numbered_terms):
    """[(term-file line, pattern)] from [(term-file line, term)]. Each term is read through the term view first (a
    pasted en dash, curly apostrophe, accent or soft hyphen in the term file). Its parts may be joined by spaces,
    line breaks, "-", "_", ",", an apostrophe or a "#" before a digit, and any of those around "&" is optional. A
    plural is allowed after a last part of 3+ characters or a digit ("-y" also matches "-ies"), and no letter or
    digit may touch either end."""
    patterns = []
    for file_line, term in numbered_terms:
        # "AT & T" stays one part; a backtick in the term file is an apostrophe typed on the wrong key
        term_text = AMPERSAND_SPACING.sub("&", term_view(term.replace("`", "'"), ""))
        parts = [part for part in re.split(TERM_PART_SEPARATOR, term_text) if part]
        if not parts:   # a term made only of separators or markup can't be matched
            continue
        *leading_parts, last_part = parts
        if len(last_part) >= MIN_PLURAL_PART_CHARS and last_part[-1] in "yY":
            last_pattern = re.escape(last_part[:-1]) + "(?:y|ys|ies)"   # "Agency" also matches "Agencies"
        else:
            # model codes take a plural ("QX-90s"); a short word doesn't ("Li" must not match "lies")
            takes_plural = len(last_part) >= MIN_PLURAL_PART_CHARS or last_part[-1].isdigit()
            last_pattern = re.escape(last_part) + (PLURAL_ENDING if takes_plural else "")
        body = TERM_PART_SEPARATOR.join([*map(re.escape, leading_parts), last_pattern])
        body = body.replace(re.escape("&"), AMPERSAND_SPACING.pattern)
        patterns.append((file_line, re.compile(r"(?<![A-Za-z0-9])" + body + r"(?![A-Za-z0-9])", re.I)))
    return patterns


def confidential_hits(text, patterns):
    """{(line_number, term-file line)} for every term found in the raw text or a term view: tags read as a space
    ("Zeta<br>Corp"), as nothing ("Ze<b>ta</b>"), or kept as text with link targets, in case something that looks
    like a tag hides real text. The raw text keeps what every view drops, such as "<sup>RB-77</sup>" or
    "[^rb-77]". Every variant keeps the newlines, so offsets map to lines."""
    if not patterns:   # no term list: skip building the views, the slow part of a run over a whole site
        return set()
    variants = [text, term_view(text, " "), term_view(text, ""), term_view(text, "", keep_tags=True)]
    found = set()
    for variant in variants:
        line_of = line_number_finder(variant)
        for file_line, pattern in patterns:
            for match in pattern.finditer(variant):
                found.add((line_of(match.start()), file_line))   # each term on a line counts
    return found


def check_text(text, filename, terms):
    """[(line_number, kind, snippet)] for one file's contents, sorted by line. With terms, grammar hits carry an
    empty snippet: the report then holds no text from the file, so it can't print a term the scan missed."""
    is_html = filename.lower().endswith((".html", ".htm"))
    is_readme = Path(filename).name.lower().startswith("readme")
    patterns = term_patterns(terms)
    hits = [(line, "confidential-term", f"(term on line {file_line} of the term file)")
            for line, file_line in sorted(confidential_hits(text, patterns))]
    # entities decoded for every file type: Markdown renders "&#x20;" as a space too. List and quote markers stay,
    # because the wrap joining reads them
    prose = html.unescape(NEWLINE_ENTITIES.sub(" ", prose_only(text, is_html)))
    line_of = line_number_finder(prose)
    joined, position = join_soft_wraps(prose), 0
    for logical_line in joined.split("\n"):
        for offset, snippet in colon_reveals(logical_line):
            hits.append((line_of(position + offset), "colon-reveal", snippet))
        for offset, snippet in trailing_participles(logical_line):
            hits.append((line_of(position + offset), "trailing-ing", snippet))
        for word_match in BANNED_WORDS.finditer(logical_line):
            hits.append((line_of(position + word_match.start()), "banned-word", word_match.group(0)))
        position += len(logical_line) + 1
    if is_readme:
        for number, line in enumerate(prose.split("\n"), start=1):
            for pronoun_match in FIRST_PERSON.finditer(line):
                # a bounded look back, so a long line full of pronouns stays linear
                previous_word = line[max(0, pronoun_match.start() - PREVIOUS_WORD_CHARS):pronoun_match.start()].split()[-1:] or [""]
                if pronoun_match.group(0) == "I" and previous_word[0].lower() in ROMAN_NUMERAL_LEADS:
                    continue
                hits.append((number, "first-person-in-readme", pronoun_match.group(0)))
    if patterns:   # with a term list, no grammar hit carries text from the file
        hits = [(line, kind, snippet if kind == "confidential-term" else "") for line, kind, snippet in hits]
    return sorted(hits)


def parse_terms(term_file_text):
    """([(term-file line, term)], [unclear term-file lines]). One term per line. A line that starts with # is a
    comment, and so is " # note" after a term. A list marker, wrapping quotes and a trailing "," ";" or "." are
    dropped, because they get pasted in from other documents. A line that still carries a note, a letter list
    marker or an odd first or last character, or that leaves nothing to match, is unclear: as a term it would never
    match, so the caller reports it."""
    terms, unclear_lines = [], []
    # number lines by "\n" only, the way an editor does (reading the file already turned "\r\n" and "\r" into "\n");
    # a rarer line break such as U+2028 or a form feed still ends a term, so two terms never run together
    for number, line in enumerate(term_file_text.split("\n"), start=1):
        for piece in LINE_BREAKS_INSIDE_LINE.split(line):
            term = INLINE_COMMENT.sub("", piece).strip()
            if not term or term.startswith("#"):
                continue
            term = LIST_MARKER_PREFIX.sub("", term).rstrip(TERM_DECORATION_END).strip()
            term = WRAPPING_QUOTES.sub(r"\1", term).rstrip(TERM_DECORATION_END).strip()   # '"Zeta Corp."' too
            unclear = (TERM_NOTE.search(term) or LETTER_LIST_MARKER.match(term) or not TERM_START.match(term)
                       or not TERM_END.search(term) or not term_patterns([(number, term)]))
            if not unclear:
                terms.append((number, term))
            elif unclear_lines[-1:] != [number]:   # one report per line, even with two unclear pieces on it
                unclear_lines.append(number)
    return terms, unclear_lines


def read_terms(path):
    """The parsed term file, or ([], []) when no term file was given."""
    if not path:
        return [], []
    return parse_terms(Path(path).read_text(encoding="utf-8-sig"))   # -sig: Notepad and PowerShell write a BOM


def expand(arguments):
    """Expand wildcards ourselves, because PowerShell passes "site/*.html" through unexpanded. "**" reaches
    subfolders, folders a pattern matches are skipped, and a file named twice is checked once."""
    files = []
    for argument in arguments:
        if Path(argument).is_file():   # an existing name such as "[id].md" is a file, not a pattern
            files.append(argument)
            continue
        matches = [path for path in sorted(glob.glob(argument, recursive=True)) if not Path(path).is_dir()]
        files += matches or [argument]   # no match: keep it, so reading it fails loudly
    return list(dict.fromkeys(files))


def self_test():
    """Each sample is (text, filename, terms, expected [(line, kind)] in line order). Returns the failure count."""
    terms = [(3, "Zeta Corp"), (5, "KX-200"), (7, "O'Brien")]   # numbered as in a term file with comments between
    colon, trailing, banned, first_person, term_hit = (
        "colon-reveal", "trailing-ing", "banned-word", "first-person-in-readme", "confidential-term")
    samples = [
        ("Designed and shipped the planner: a lattice search combined with a learned cost map, running on ROS 2.",
         "page.md", [], [(1, colon), (1, trailing)]),
        ("I came to tooling through support: two years on the help desk.", "page.md", [], [(1, colon)]),
        ("The best part: it learns.", "page.md", [], [(1, colon)]),
        ("The fix: a lattice search.", "page.md", [], [(1, colon)]),
        ("Best part: it learns.", "page.md", [], [(1, colon)]),
        ("**Build a new index:** run the indexing job.", "README.md", [], []),
        ("- **Build a new index**: run the indexing job.", "README.md", [], []),
        ("__Plan the backups:__ start the scheduler.", "README.md", [], []),
        ("<p><strong>Plan for the backups:</strong> start the scheduler.</p>", "page.html", [], []),
        ("<!doctype html><p>Note: needs Python 3.8.</p>", "page.html", [], []),
        ("Last tested in 2024 with:\n\n- Debian 12", "README.md", [], []),
        ("Fixed: the tracker runs at 10 Hz.", "page.md", [], []),
        ("See https://example.com before 10:30, under C:\\Tools\\ink.", "page.md", [], []),
        ('You can also name it: "use writing-voice on the About section".', "README.md", [], []),
        ("The tracker fuses lidar and odometry, including wheel encoders.", "page.md", [], []),
        ("I tuned the filter in signal_2d: it publishes the reading.", "page.md", [], [(1, colon)]),
        ("He is a builder who put together the rig.", "page.md", [], [(1, banned), (1, banned)]),
        ("I trained the detector. We tuned it with our team.", "README.md", [],
         [(1, first_person), (1, first_person), (1, first_person)]),
        ("My planner reads that frame.", "README.md", [], [(1, first_person)]),
        ("The board has 8 I/O pins for Phase I.", "README.md", [], []),
        ("I trained the detector.", "about.md", [], []),
        ("---\nname: writing-voice\ndescription: >\n  House style: plain.\nlicense: MIT\n---\nBody text.", "SKILL.md",
         [], []),
        ('- Flagged: "Designed the planner: a lattice search, running on ROS 2."', "SKILL.md", [], []),
        ('He said "Zeta Corp: done" twice.', "page.md", terms, [(1, term_hit)]),
        ("```\nkey: value, running\n```\n~~~\nx: y, running\n~~~\nUse `a: b, running` here.", "README.md", [], []),
        ("Intro.\n\n    key: value, running\n\nAfter.", "README.md", [], []),
        ("<p>Designed the planner: a search.</p>\n<code>a: b, running</code>", "page.html", [], [(1, colon)]),
        ("<pre>key: value, running</pre>", "README.md", [], []),
        ("| Interface | Name |\n|---|---|\n| Feed | Topic: the merged feed |", "README.md", [], []),
        ("| Merged feed | `/feed_all` | ingest, logging |", "README.md", [], []),
        ("Postgres 16, the ingest service, logging, s3_sync_tools and signal_2d", "README.md", [], []),
        ("It covers mapping, planning, logging.", "README.md", [], []),
        ("I set it up the same way, syncing the logs to one clock.", "page.md", [], [(1, trailing)]),
        ("The service runs, typically running at night.", "page.md", [], [(1, trailing)]),
        # hard-wrapped prose is checked as one sentence; the hit is reported on the line where the clause starts
        ("We designed and shipped the\nplanner: a lattice search.", "page.md", [], [(1, colon)]),
        ("Designed the planner:\na lattice search over poses.", "page.md", [], [(1, colon)]),
        ("The tracker fuses lidar and odometry,\nrunning at 10 Hz.", "page.md", [], [(1, trailing)]),
        ("Run these steps in order:\n1. Build the image.\n2. Run it.", "README.md", [], []),
        ("## Install\nNote: needs Python 3.8.", "README.md", [], []),
        ("Install it first.\nNote: needs Python 3.8.", "README.md", [], []),
        ("He is the one who put\ntogether the rig.", "page.md", [], [(1, banned)]),
        # confidential terms: found in any form a reader would recognise, never echoed
        ("We worked with Zeta Corp on it.", "page.md", terms, [(1, term_hit)]),
        ("Zeta Corp shipped the KX-200 rigs.", "page.md", terms, [(1, term_hit), (1, term_hit)]),
        ("Use `kx-200 --init` here.\n```\nclient = 'Zeta Corp'\n```", "README.md", terms, [(1, term_hit), (3, term_hit)]),
        ('<img alt="KX-200 rig"><!-- Zeta Corp notes --><p>Zeta <em>Corp</em></p>', "page.html", terms,
         [(1, term_hit), (1, term_hit)]),   # two different terms on the line: one hit each
        ("We worked on Zeta\nCorp for a year, and Zeta&#32;Corp again.", "page.md", terms, [(1, term_hit), (2, term_hit)]),
        # one disguised form per line, so each line must earn its own hit
        ("We met Zeta *Corp*.\nWe met **Zeta** Corp.\nWe met _Zeta_ Corp.\nWe met Ze*ta* Corp.\nWe met Ze`ta` Corp.",
         "page.md", terms, [(line, term_hit) for line in range(1, 6)]),
        ("[Zeta](https://example.com/a_(b)) Corp.\n[Zeta][zc] Corp.\n[Zeta] Corp.\nZeta[^1] Corp.",
         "page.md", terms, [(line, term_hit) for line in range(1, 5)]),
        ("Zeta&shy;Corp.\nZeta&#8203;Corp.\nZe\u200eta Corp.\nZeta\u2063Corp.", "page.md", terms,
         [(line, term_hit) for line in range(1, 5)]),
        ("<p>We met Zeta<br>Corp.</p>\n<p>We met Ze<b>ta</b> Corp.</p>\n<p>We met Zeta<sup>1</sup> Corp.</p>",
         "page.html", terms, [(line, term_hit) for line in range(1, 4)]),
        ("We met Zeta <!-- note --> Corp.\n> We met Zeta\n> Corp.\n> > Zeta\n> > Corp.\nZeta\\\nCorp.", "page.md", terms,
         [(1, term_hit), (2, term_hit), (4, term_hit), (6, term_hit)]),
        ("The KX\\-200.\nThe KX\u2011200.\nThe KX\u058a200.\nTwo KX-200s.\nA KX 200.\nA kx_200.", "page.md", terms,
         [(line, term_hit) for line in range(1, 7)]),
        ("See zeta-corp.\nSee zeta_corp.\nSee \uff3a\uff45\uff54\uff41 Corp.\nhttps://example.com/zeta%20corp\n"
         "https://example.com/?q=zeta+corp\nhttps://example.com/kx%2D200\nWe met ==Zeta== Corp.",
         "page.md", terms, [(line, term_hit) for line in range(1, 8)]),
        ('<p>On Zeta<span title="a>b"> Corp</span>.</p>\n<p>On Ze<?x?>ta Corp.</p>', "page.html", terms,
         [(1, term_hit), (2, term_hit)]),
        ("We met O\u2019Brien.\nWe met O&rsquo;Brien.", "page.md", terms, [(1, term_hit), (2, term_hit)]),
        ("See [the notes](https://example.com/zeta-corp) first.", "page.md", terms, [(1, term_hit)]),   # raw only
        ("One&#10;two.\nWe met Zeta Corp.", "page.md", terms, [(2, term_hit)]),   # a newline entity shifts no line
        ("One&#10two.\nWe met Zeta Corp.", "page.md", terms, [(2, term_hit)]),
        # a stray "<" or "<!--" must not hide the text up to a later ">" or "-->"
        ("Check that `i<n` holds.\n\nWe met Zeta&#32;Corp.\n\nThen a -> b.", "page.md", terms, [(3, term_hit)]),
        ("Check that `i<n` holds.\n\nWe met Zeta<br>Corp.\n\nThen a -> b.", "page.md", terms, [(3, term_hit)]),
        ("Type `<!--` here.\n\nWe met Zeta<br>Corp.\n\nThen `-->` there.", "page.md", terms, [(3, term_hit)]),
        ("If a<b holds.\n\nWe met Zeta *Corp*.\n\nThen x > y.", "page.md", terms, [(3, term_hit)]),   # keep-tags view
        # a term from the term file is read the same way: a pasted en dash or curly apostrophe still matches
        ("The KX-200 rig and O'Brien.", "page.md", [(1, "KX\u2013200"), (2, "O\u2019Brien")], [(1, term_hit), (1, term_hit)]),
        ("Kai lies here.", "page.md", [(1, "Li")], []),   # a short word takes no plural
        ("Two QX-90s ran.", "page.md", [(1, "QX-90")], [(1, term_hit)]),   # a model code does
        ("The kx200 and zetacorp names are different words.", "page.md", terms, []),
        ("Run these steps in order:\n* Build the image.\n* Run it.", "README.md", [], []),
        ("The relay ships in a blue case.\n> Note: the fan is quiet.", "page.md", [], []),
        ("<div>Status: ready at 10:30</div><p>Note: the fan runs quietly.</p>", "page.html", [], []),
        ("<p>The tracker fuses lidar and odometry,<br>running at 10 Hz.</p>", "page.html", [], [(1, trailing)]),
        ('He told the team: "ship it today." Then he left.', "page.md", [], []),
        ("&ldquo;Designed the planner: a lattice search&rdquo; is the flagged line.", "page.md", [], []),
        ("(The fix: a lattice search.)", "page.md", [], [(1, colon)]),   # a bracket doesn't make it a label
        ('version: "1.1"\nname: fix-pattern\noutcome: | The pages.', "case.yaml", [], []),   # quote marks aren't words
        # round 6: link targets, escapes, signs, footnotes, code, accents, term-file invisibles, format characters
        ("[the search](https://example.com/?q=zeta+corp)\n[notes](docs/Zeta%20Corp.md)\n[spec](https://example.com/kx%2D200)\n"
         "www.example.com/?q=zeta+corp\nSee docs/zeta%20corp.md first.", "page.md", terms,
         [(line, term_hit) for line in range(1, 6)]),
        ("See zeta\\_corp.\nThe KX\u2212200.\nThe KX&minus;200.\n<p>Zeta<sup><a href=\"#fn1\">1</a></sup> Corp.</p>",
         "page.html", terms, [(line, term_hit) for line in range(1, 5)]),
        ("Write `<strong>Zeta</strong> Corp` here.\n```\n<!--\n```\n\nWe met Zeta<br>Corp.\n\n```\n-->\n```", "page.md",
         terms, [(1, term_hit), (6, term_hit)]),
        ("Ze\U000e0041ta Corp.\nZe\u034fta Corp.\nZeta\ufe0f Corp.\nWe met O\u02bcBrien.", "page.md", terms,
         [(line, term_hit) for line in range(1, 5)]),
        ("We met Jose Perez and jose-perez.", "page.md", [(1, "José Pérez")], [(1, term_hit)]),
        ("We met José Pérez.", "page.md", [(1, "Jose Perez")], [(1, term_hit)]),
        ("Kestrelnet runs.", "page.md", [(1, "Kestrel\u00adnet")], [(1, term_hit)]),
        ("The XKX-200 and KX-2000 rigs.", "page.md", terms, []),   # no letter or digit may touch either end
        # round 7: marks NFKD would turn into letters, raw-only forms, stroke letters, commas, brackets, plurals
        # an entity in each line keeps the raw text from matching, so only the before-NFKD fill can
        ("The Kestrel&shy;net™ board.\nThe Kestrel&shy;net&trade; board.\nThe Zeta&nbsp;Corp℠ team.\n"
         "Zeta&nbsp;Corp¹ left.\nTwo KX&#8209;200² units.\nZeta&nbsp;Corp⁴ left.\nZeta&nbsp;Corpª left.\n"
         "Zeta&nbsp;Corpº left.\nZeta&nbsp;Corp³ left.", "page.md", [(1, "Kestrelnet"), (2, "Zeta Corp"), (3, "KX-200")],
         [(line, term_hit) for line in range(1, 10)]),
        ("We met Kestrelnet.\nWe met GROẞMANN.", "page.md", [(1, "Kestrelnet®"), (2, "Grossmann")],
         [(1, term_hit), (2, term_hit)]),   # a "®" in the term file, a capital sharp s
        ("We ran Project 7.\nWe ran Project#7.\nSee /reports/project-7 now.\nWe ran Project #70.\nWe met TICKET-4521.",
         "page.md", [(1, "Project #7"), (2, "Ticket #4521")], [(1, term_hit), (2, term_hit), (3, term_hit),
                                                            (5, term_hit)]),   # "#70" is another number
        ("We ran Project #7.", "page.md", [(1, "Project 7")], [(1, term_hit)]),
        ("Two ties.", "page.md", [(1, "Ty")], []),   # a short "-y" word takes no "-ies"
        # an apostrophe typed as an accent, a backtick or a space; "Oscar" is another word
        ("We met O´Varnley.\nWe met O`Varnley.\nWe met O Varnley.\nWe met Oscar Varnley.", "page.md",
         [(1, "O'Varnley")], [(1, term_hit), (2, term_hit), (3, term_hit)]),
        ("We met O'Varnley.", "page.md", [(1, "O´Varnley")], [(1, term_hit)]),
        # spaces around "&" are optional both ways; "at the" has no "&"
        ("We met AT&T.\nWe met AT & T.\nWe met R & D.\nWe met at the mall.\nSee docs/AT_&_T.md and R-&-D.md.\n"
         "[notes](docs/Johnson_%26_Varnley.pdf)", "page.md", [(1, "AT & T"), (2, "R&D"), (3, "Johnson & Varnley")],
         [(1, term_hit), (2, term_hit), (3, term_hit), (5, term_hit), (5, term_hit), (6, term_hit)]),
        ("We met O'Varnley.", "page.md", [(1, "O`Varnley")], [(1, term_hit)]),   # a backtick typed in the term file
        ("<p>See <sup>KX-200</sup> here.</p>\n<p>Note [^kx-200] there.</p>", "page.html", terms,
         [(1, term_hit), (2, term_hit)]),   # every view drops these; only the raw text keeps them
        ("We met Lukasz Nowak, Soren, Grossmann and Aesir.", "page.md",
         [(1, "Łukasz Nowak"), (2, "Søren"), (3, "Großmann"), (4, "Æsir")], [(1, term_hit)] * 4),
        ("We met Łukasz Nowak.", "page.md", [(1, "Lukasz Nowak")], [(1, term_hit)]),
        ("The Kestrel&shy;net™ board.", "page.md", [(1, "Kestrelnet")], [(1, term_hit)]),   # two forms at once
        ("See https://example.com/jos%C3%A9-perez first.\nThen www.example.com/jos%C3%A9-p%C3%A9rez too.", "page.md",
         [(1, "José Pérez")], [(1, term_hit), (2, term_hit)]),
        ("Acme, Inc. signed. Call (555) 010-0199.", "page.md", [(1, "Acme Inc"), (2, "555 010-0199")],
         [(1, term_hit), (1, term_hit)]),
        ("Two Agencies and three Monkeys.", "page.md", [(1, "Agency"), (2, "Monkey")], [(1, term_hit), (1, term_hit)]),
        ("[s](/search?q=zeta+corp)\n<a href=\"/search?q=zeta+corp\">s</a>\nSee docs/zeta%5fcorp.md.\n"
         "https://example.com/a%0Ab\nWe met Zeta Corp.\nZe\U000e0100ta Corp.", "page.md", terms,
         [(1, term_hit), (2, term_hit), (3, term_hit), (5, term_hit), (6, term_hit)]),   # a decoded %0A shifts no line
        ("[bio](/team/Jos%C3%A9-P%C3%A9rez)\nSee docs/a%0Ab.md.\nWe met Zeta Corp.", "page.md",
         [(1, "José Pérez"), (2, "Zeta Corp")], [(1, term_hit), (3, term_hit)]),   # any escape, outside a full URL too
        ("See https://example.com/t/zeta+corp now.\nSee www.example.com/t/zeta+corp now.", "page.md", terms,
         [(1, term_hit), (2, term_hit)]),   # a "+" in a full URL's path reads as a space
        ("<pre><code>a: b, running\nc: d\n</code></pre>\n<p>The fix: a search.</p>", "page.html", [], [(4, colon)]),
        ("<script>a: b, running</script>\n<style>c: d, running</style>", "page.html", [], []),
    ]
    failures = 0
    # one long word stays fast: the trailing-ing regex is quadratic on it without its leading \b
    started = time.perf_counter()
    check_text("Hex dump " + "a" * LONG_WORD_CHARS + " and no comma after it.", "page.md", [])
    if time.perf_counter() - started > MAX_LONG_WORD_SECONDS:
        failures += 1
        print(f"FAIL a {LONG_WORD_CHARS}-character word took over {MAX_LONG_WORD_SECONDS} s")
    for text, filename, sample_terms, expected in samples:
        found = [(line, kind) for line, kind, _ in check_text(text, filename, sample_terms)]
        if found != expected:
            failures += 1
            print(f"FAIL {text[:60]!r} in {filename}: expected {expected}, found {found}")
    # with a term list, a grammar hit carries no text from the file, even when the scan misses a term
    missed_form = "On the Ze\u0396ta rig we tuned the planner: a lattice search, running at 10 Hz."   # a look-alike letter
    with_terms = check_text(missed_form, "page.md", terms)
    if not with_terms or any(snippet for _, kind, snippet in with_terms if kind != term_hit):
        failures += 1
        print("FAIL a grammar hit printed text from the file while a term list was given")
    without_terms = check_text(missed_form, "page.md", [])
    if not without_terms or not all(snippet for _, _, snippet in without_terms):
        failures += 1
        print("FAIL a grammar hit lost its snippet without a term list")
    # a hit names the term's line in the term file
    if check_text("The KX-200 rig.", "page.md", terms)[0][2] != "(term on line 5 of the term file)":
        failures += 1
        print("FAIL a hit does not name the term's line in the term file")
    # comments and pasted-in decoration are dropped from the term file; a "#" before a digit is part of the term;
    # a line with a note, a letter marker or an odd first or last character is unclear
    # (lines 11, 13 to 27, 29 to 39, 45 to 48, 56 to 63, 65 and 66)
    parsed = parse_terms(
        "# clients\nZeta Corp   # main client\n\n  # hardware\nKX-200\n#KX-300\nProject #7\n"
        "- \"Bluefin Works\",\n1. Quill;\n• Lumen Labs\nOrca Ltd (main client)\nAcme Co.\n"
        "Delta: supplier\nNova\tWorks\nZeta Corp, Bluefin Works\nZeta Corp -- note\nZeta Corp / note\nZeta Corp = note\n"
        "Zeta Corp [note]\nZeta Corp  note\na. Zeta Corp\n● Zeta Corp\n«Zeta Corp»\nZeta Corp…\n"
        "<Zeta Corp>\nZeta Corp #client\n[x] Zeta Corp\nKestrelnet™\n__\n"
        "Zeta Corp - note\nZeta Corp – note\nZeta Corp | note\nZeta Corp; Quill\niv. Zeta Corp\nZeta Corp#internal\n"
        "Zeta Corp—client\nClients > Zeta Corp\nClients → Zeta Corp\nClients • Zeta Corp\n"
        "\"Zeta Corp.\"\nKestrelnet®\nKX–200\nLumen Labs\u2028Bluefin Works\x0bNova\x0cOrca\x1cDelta\x1dAcme Co\x1eZephyr\x85Kestrel\u2029Quill\nQuillmere\n"
        "Zeta Corp -> client\nZeta Corp // client\nZeta Corp--client\nZeta Corp ... client\nC++\n@quillon\nAT & T\n"
        "“Bluefin Works”\nBluefin Works #\nVarnley℠\nZeta Corp ®\nZeta Corp|client\n"
        "Zeta Corp->client\nZeta Corp ->client\nZeta Corp→client\nZeta Corp//client\nZeta Corp (a)\u2028Bluefin (b)\nZeta Corp=>client\nZeta Corp<-client\nC#\nAT&&T\nQ&_&R")
    # line 29 leaves nothing to match; the eight rare line breaks in line 43 end a term there but shift no later line
    expected_terms = [(2, "Zeta Corp"), (5, "KX-200"), (7, "Project #7"), (8, "Bluefin Works"), (9, "Quill"),
                      (10, "Lumen Labs"), (12, "Acme Co"), (28, "Kestrelnet™"), (40, "Zeta Corp"),
                      (41, "Kestrelnet®"), (42, "KX–200"), (43, "Lumen Labs"), (43, "Bluefin Works"), (43, "Nova"), (43, "Orca"), (43, "Delta"), (43, "Acme Co"), (43, "Zephyr"), (43, "Kestrel"), (43, "Quill"),
                      (44, "Quillmere"), (49, "C++"), (50, "@quillon"), (51, "AT & T"), (52, "Bluefin Works"),
                      (53, "Bluefin Works"), (54, "Varnley℠"), (55, "Zeta Corp ®"), (64, "C#")]
    if parsed != (expected_terms, [11, *range(13, 28), *range(29, 40), *range(45, 49), *range(56, 64), 65, 66]):
        failures += 1
        print(f"FAIL term file parsed as {parsed}")
    checks = len(samples) + 5
    print(f"self-test: {checks - failures}/{checks} checks behave as expected")
    return failures


def main():
    """Parse the arguments, read every input up front, print each hit and return the exit code."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")   # Windows consoles default to cp1252
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
                                     allow_abbrev=False)
    parser.add_argument("files", nargs="*")
    # append, so a second --terms (a file planted as "--terms=x" in a shell-expanded glob) is caught, not obeyed
    parser.add_argument("--terms", action="append",
                        help="confidential term list, one term per line; # starts a comment at a line start, and "
                             "' # ' starts one after a term")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        if args.files or args.terms:   # a planted file named "--self-test" must not turn a scan into a pass
            parser.error("--self-test takes no other arguments")   # exits with EXIT_USAGE
        return EXIT_CLEAN if self_test() == 0 else EXIT_SELF_TEST_FAILED
    if args.terms and len(args.terms) > 1:
        parser.error("--terms given more than once")
    if args.terms and not args.terms[0].strip():
        parser.error("--terms needs a file name")   # an unset variable in a hook must not mean "no term list"
    term_file = args.terms[0] if args.terms else None
    files = expand(args.files)
    if not files:
        parser.error("no files given")
    try:   # read everything first, so a typo or an unreadable file is a usage error, not a pass or a "term found"
        terms, unclear_lines = read_terms(term_file)
        contents = {filename: Path(filename).read_text(encoding="utf-8-sig") for filename in files}
    except (OSError, UnicodeDecodeError) as error:
        parser.error(f"can't read input: {error}")
    if unclear_lines:   # such a line would never match, so the run would pass silently
        parser.error(f"the term file has a note, a list marker, stray punctuation or extra spacing on line(s) "
                     f"{', '.join(map(str, unclear_lines))}; "
                     "put one plain term on each line, with any note after ' # '")
    if term_file and not terms:   # parse_terms already reported any line that yields no pattern
        parser.error("the term file has no usable terms")   # an empty list would pass every draft silently
    total, term_found = 0, False
    for filename in files:
        for number, kind, snippet in check_text(contents[filename], filename, terms):
            print(f"{filename}:{number}: {kind}" + (f": {' '.join(snippet.split())}" if snippet else ""))
            total += 1
            term_found |= kind == "confidential-term"
    summary = f"--- {total} candidate(s) in {len(files)} file(s)"
    if term_found:
        summary += "; CONFIDENTIAL TERM FOUND"
    elif not term_file:
        summary += "; no term list given"
    print(summary)
    return EXIT_TERM_FOUND if term_found else EXIT_CLEAN


if __name__ == "__main__":
    sys.exit(main())
