---
name: writing-voice
description: >
  House style for prose that other people will read. It covers site copy, case studies, About text, README
  sections, docs, repo descriptions and profile text. Plain subject-plus-verb sentences, no colon reveals, no
  tacked-on "-ing" clauses, owner verbs when the text is about the author, and project-centric wording in
  open-source READMEs, plus a scan against the project's confidential term list. Use it whenever you write or edit
  such prose, including a single line the user quotes back as bad grammar or "reads AI-generated", and before
  showing any copy change. Run the no-ai-slop skill alongside it.
license: MIT
---

# Writing voice

Write so a busy expert reads each sentence once and keeps going. General AI patterns (banned words, binary
contrasts, puffery) belong to the `no-ai-slop` skill, so call the Skill tool with "no-ai-slop" as well. This skill
adds the rules below on top of it.

## 1. One subject, one verb, one point per sentence

Each sentence names who did what. When a sentence carries two ideas, split it.

- **No colon reveals.** A noun phrase, a colon, then the real content is a stage trick. Write the sentence plainly.
  - Flagged: "Designed and shipped the planner: a lattice search combined with a learned cost map."
  - Fixed: "I designed and shipped the planner. It combines a lattice search with a learned cost map."
  - Flagged: "I came to tooling through support: two years on the help desk, then a move to the build team."
  - Fixed: "I came to tooling through support. I spent two years on the help desk, then moved to the build team."
- A colon is fine at the end of a line that introduces a list or a block, in a label such as "**Build a new index:**",
  and before a quote, a time, a key or code. A mid-sentence colon followed by a list is usually a reveal.
- **No tacked-on participle clauses.** A trailing ", running on ROS 2" hangs a second claim off the first without
  a subject. Give it its own sentence.
  - Flagged: "The tracker fuses lidar and odometry, running at 10 Hz on the vehicle."
  - Fixed: "The tracker fuses lidar and odometry. It runs at 10 Hz on the vehicle."
- **No absolute clauses either.** They hide a second claim in the same way.
  - Flagged: "The detector publishes a pose for each object, its output feeding the planner."
  - Fixed: "The detector publishes a pose for each object. The planner reads that pose."

## 2. Pick the voice for the reader

**Text about the author** (portfolio pages, case studies, About, a profile) is written as the author taking charge.

- Use owner and leader verbs such as designed, shipped, own, led, set, established, delivered and decided.
- Never call the author a "builder". Avoid "built" and "put together", which undersell ownership.
- Leader wording adds no facts. If a stronger verb would claim more than happened, keep the weaker verb.

**Open-source READMEs and repo docs** are written for the people who will build on the code.

- The project is the subject. Write "It sorts parcels by weight and size", not "I built sorting".
- Avoid first-person narrative and "What I did" sections. Authorship lives in the LICENSE and the commit history.
- Avoid naming the author in third person in the body. Write "This repo is MIT licensed", not "<Name>'s work is
  MIT licensed".
- Say what a reader can do with each part, such as build it, run it or extend it.

## 3. Stay inside cleared facts

- Use only facts the user has given or that the source material shows. When a sentence needs an inference (a date,
  a result, what a test proved), ask the user instead of writing it as fact.
- A rewrite changes the wording, never the claim. Three slips add claims without looking like it:
  - Swapping a verb for a stronger or more specific one. Changing "trained" to "stores" is a new claim.
  - Adding an explanation, benefit or consequence the source doesn't state, such as "so any node can look it up".
  - Upgrading a list into ownership when you split a colon list. Carry the list over with a neutral verb such as
    covers, includes or handles. "I lead the team: mapping and routing" becomes "I lead the team. It covers
    mapping and routing", not "The team owns mapping and routing", unless the source says so.
- Some projects keep a list of confidential terms (internal names, codes, clients, people). The usual place is
  `INTERNAL/nda_terms.txt`, one term per line, with any note after ` # ` (a note glued to the term isn't caught).
  When it exists, confirm the file is gitignored, then scan every draft against it before showing anything. The
  scan reads code, attributes and comments too. Read the term file when you need to know what to replace, but never
  put a term into your reply, a note or any other message.
- Never copy a confidential term into a commit, a public file or a message that leaves the project. That includes
  your own change notes. Describe a removed term by its line in the term file ("line 3 of the term file"), as
  the script reports it, not by quoting it.
- Respect any disclosure limit the project states, such as wording the author has ruled out for a public page.

## 4. Check before showing

Run the check script from this skill's folder over every page or file in scope, not only the ones you changed.
Scope is the published prose of the site, docs set or repo the change belongs to, so a pattern on a page nobody
edited still surfaces. Leave out gitignored folders such as `INTERNAL/` and `node_modules/`, and test fixtures.
In a git repo, `git ls-files` lists what ships. The script's `**` skips dot folders but not gitignored ones.
If `python` isn't on the PATH, use `python3` or `uv run --no-project python`. Quote each pattern and put `--`
before the file names, so no file name can turn into an option.

```bash
python <this skill's folder>/scripts/check_voice.py [--terms INTERNAL/nda_terms.txt] -- "<files or globs>"...
```

It reports five kinds of hit:
- colon reveals
- trailing "-ing" clauses
- this skill's banned words ("builder", "put together")
- first person in README files
- confidential terms

Prose checks skip code and read wrapped sentences whole. With `--terms`, a hit shows only its file, line and
kind, never text from the file, so read the flagged line in the file itself. File names are printed as given, so
never name a file after a confidential term. The term scan catches accidental leaks, not deliberate disguise such
as look-alike letters. It also misses a term written as one run-together word, with a dot or slash between its
parts, split by a line-end hyphen or with "&" spelled "and", so reread anything that will go public. The script
exits 0 when no confidential term is found and 1 when one is. It exits 2 on a usage error, such as no files
given, an input that can't be read, `--terms` given twice or empty, a term file with no usable terms or a note on
a term line, or `--self-test` with other arguments. When it names a term-file line with a note, tell the user
which line it is; don't edit their term file without asking. A grammar hit never blocks a push, and a typo never
passes silently.
Treat every grammar hit as a candidate and read it in context. The task is the text the user named. A named line
is that line, a named section is that section, and a page or file is the whole page only when the user asks for
work on all of it. A page named only to say where an edit goes ("on the home page, change X") makes that edit the
task. In the task, fix each hit, or keep it on purpose when it really is a label, a list intro or a quote. A hit
anywhere else, including another sentence on a page you are editing, goes in your reply with its file and line,
and you ask before editing it. The user then knows about it without finding unasked changes in the diff. With a
term list, name such a line by file and line number only and never quote it, because it may hold a term the scan
missed.

The one exception is a quoted bad line. When the user quotes one, the same pattern almost always appears
elsewhere, so that pattern is part of the task on every page in scope. Fix it everywhere in the same pass and
tell the user which other lines you changed, by file and line. Other kinds of hit on those pages stay outside the
task, so list them and ask, as above. Edit each file in place and keep its line endings and encoding, so a diff
shows only the sentences you changed. Then reread the edited text. If a sentence needs a second read, split it.

## Works with

- `no-ai-slop` for general AI-pattern editing (call the Skill tool with "no-ai-slop").
- `readme-format` and `repo-tidy` (when installed), which apply this voice to READMEs and repo metadata.
