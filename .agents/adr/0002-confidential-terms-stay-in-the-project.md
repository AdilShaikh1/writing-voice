# Confidential terms stay in the user's project

The skill scans drafts against a list of confidential terms, but the list never lives in this repo. Each project keeps its own list in a gitignored file, usually `INTERNAL/nda_terms.txt`, and passes it with `--terms`.

The scan is built to catch accidental leaks in normal writing, such as a term with Markdown or HTML markup around it, a pasted en dash, curly apostrophe or accent, or an invisible character copied from another document. It is not a defence against deliberate disguise, such as look-alike letters from another alphabet. Pattern matching can't close that class, and several review rounds kept finding new members of it.

So the report doesn't depend on the scan being complete. With a term list, a grammar hit shows only its file, line and kind, never text from the file, and a confidential-term hit names the term by its line in the term file. The report can then be shared without leaking the list, even when the scan misses a term.

These limits stay, and the docs name them:

- The script prints file names as given, so a term in a file name shows up in the report.
- `**` skips dot folders.
- A term written as one run-together word, with a dot or slash between its parts, or split by a line-end hyphen isn't matched, and neither is `&` written as "and" or dropped from a URL slug.
- A note glued to a term line, or with a space on one side only (`Zeta Corp/client`, `Zeta Corp -client`), isn't caught, so notes go after ` # `.
- Rarer misses are a double-encoded or Latin-1 percent escape, a `+` in a relative link's path, a NUL byte inside a word, and a space or a second `#` after a number sign ("Project # 7"). The script's help lists them.

A term line that carries a note, such as `Zeta Corp (main client)`, would never match, so it is a usage error instead of a silent pass. Only a note written as `Zeta Corp # note` is a comment. A `#` right before a digit belongs to the term, so `Project #7` stays a term. It also acts as a separator, so `Project #7`, "Project 7" and "project-7" match each other.

A grammar hit is advice, so it never fails a run. A confidential term exits 1. A usage error exits 2, such as no files given, an input that can't be read, `--terms` given twice or empty, a term file with no usable terms or a note on a term line, or `--self-test` given with other arguments. A pre-push gate then blocks on a leak or a typo and never on a judgment call.
