<h1 align="center">Writing Voice</h1>

<p align="center"><strong>A house style for prose that&nbsp;reads&nbsp;once&nbsp;and&nbsp;lands.</strong></p>

<p align="center">An agent skill for Claude Code, Codex and other coding agents.<br>It writes site copy, case studies and READMEs in plain subject-plus-verb sentences, with an owner voice for the author and a project-first voice for open-source docs.</p>

<p align="center"><a href="#install">Install</a>&nbsp;&nbsp; &nbsp;&nbsp;<a href="#usage">Usage</a>&nbsp;&nbsp; &nbsp;&nbsp;<a href="#what-the-check-reports">What&nbsp;the&nbsp;check&nbsp;reports</a>&nbsp;&nbsp; &nbsp;&nbsp;<a href="#common-questions">Common&nbsp;questions</a>&nbsp;&nbsp; &nbsp;&nbsp;<a href="#license">License</a></p>

<br />

> A style rule only helps if it holds on every page, not just the line someone complained about. The skill states each rule with a flagged example and its fix, and a small script finds the same patterns across every file in scope. The model then judges each hit in context, so one quoted bad line gets fixed everywhere it repeats.

<br />

## What it does

The skill rewrites prose so each sentence has one subject, one verb and one point. Colon reveals, tacked-on participle clauses and absolute clauses become separate sentences. Text about the author uses owner verbs such as designed, shipped, led and own. Open-source READMEs make the project the subject, with no first person and no "What I did".

A rewrite changes the wording and never the claim. A stronger verb, an added explanation, or a colon list upgraded into ownership all count as new claims. The skill keeps the source's claim and asks the user before writing anything it can't confirm.

A check script finds the same patterns in every file in scope and scans each draft against the project's own list of confidential terms. The scan is built to catch accidental leaks in normal writing. It reads through Markdown and HTML markup, entities, URL encoding, invisible characters, accents and dash or apostrophe variants, and it matches a term written with spaces, `-`, `_`, `,` or an apostrophe between its parts, with or without a `#` before a number or separators around `&`. It is not a defence against deliberate disguise, such as look-alike letters from another alphabet.

With a term list, the report shows only the file, line and kind of each hit, never text from the file, so it can't print a term even when the scan misses one. It does print file names as given, and `**` skips dot folders. A term written as one run-together word, with a dot or slash between its parts, or split by a line-end hyphen isn't matched, and neither is `&` written as "and" or dropped from a URL slug. List those spellings as their own terms. The script's `--help` lists the rarer misses, such as a double-encoded URL.

## When to reach for it

Ask for it by name ("use writing-voice on the About section"), or the agent reaches for it on its own when you write or edit prose that someone else will read. That includes a single line you quote back as bad grammar or "reads AI-generated".

The skill calls [no-ai-slop](https://github.com/petergyang/no-ai-slop) for the general AI patterns (banned words, binary contrasts, puffery) and adds the rules above. It works alongside `readme-format` and `repo-tidy` (when installed), which apply this voice to READMEs and repo metadata.

## Install

As a Claude Code plugin, add this repo as a marketplace and install from it:

```text
/plugin marketplace add AdilShaikh1/writing-voice
/plugin install writing-voice@writing-voice
```

For Codex, Cursor and other agents, use the [skills](https://github.com/vercel-labs/skills) CLI from npm. Its README lists the options for choosing which agents to install for.

```bash
npx skills add AdilShaikh1/writing-voice -g
```

To edit the skill and have changes apply at once, clone the repo and link the skill folder into your skills directory instead. Use your own clone folder in place of `<clone-dir>`.

On macOS or Linux:

```bash
git clone https://github.com/AdilShaikh1/writing-voice <clone-dir>
mkdir -p ~/.claude/skills
ln -s <clone-dir>/skills/writing-voice ~/.claude/skills/writing-voice
```

On Windows, a directory junction needs no admin rights:

```powershell
git clone https://github.com/AdilShaikh1/writing-voice <clone-dir>
New-Item -ItemType Directory -Force $HOME\.claude\skills
New-Item -ItemType Junction -Path $HOME\.claude\skills\writing-voice -Target <clone-dir>\skills\writing-voice
```

The check script needs Python 3.8 or later and uses only the standard library. Its self-test passes on Windows and Linux.

## Usage

To run the check yourself:

```bash
python skills/writing-voice/scripts/check_voice.py --terms INTERNAL/nda_terms.txt -- "site/*.html" README.md
python skills/writing-voice/scripts/check_voice.py --self-test
```

The script expands wildcards itself, so the quoted pattern also works in PowerShell, and `**` reaches subfolders. Quote every pattern and put `--` before the file names, so the shell can't turn a stray file name into an option.

The term file holds one plain confidential term per line. A line that starts with `#` is a comment, and so is a note written as `Zeta Corp # main client`. A `#` right before a digit belongs to the term, so `Project #7` is a term, and it also matches "Project 7" and "project-7". Pasted list bullets, quotes around a term and a trailing comma or period are dropped. Most other notes or punctuation on a term line, such as `Zeta Corp (main client)`, `Zeta Corp - client`, `Zeta Corp->client` or `Acme, Inc.`, stop the run and name the line, because that line would never match. Write the plain form instead. `Acme Inc` still matches "Acme, Inc.", `Zeta Corp` matches "Zeta Corp (UK)", and a host name such as `build.zeta.example` matches inside a URL. A note glued to the term without spaces can still slip through, so keep notes after ` # `. Keep the file in a gitignored folder such as `INTERNAL/`.

It exits 0 when no confidential term is found and 1 when one is. It exits 2 on a usage error, such as `--terms` given twice or empty, no files given, an input that can't be read, a term file with no usable terms or a note on a term line, or `--self-test` given with other arguments. A run without `--terms` says so in its last line. Grammar hits are advice, so they never fail a run, and a pre-push gate blocks only on a leak or a typo.

## What the check reports

| Kind | Example it catches | What to do |
| --- | --- | --- |
| `colon-reveal` | "Designed the planner: a lattice search" | Split into plain sentences |
| `trailing-ing` | "…fuses lidar and odometry, running at 10 Hz" | Give the clause its own subject and verb |
| `banned-word` | "builder", "put together" | Use an owner verb |
| `first-person-in-readme` | "I trained the detector" in a README | Make the project the subject |
| `confidential-term` | any term from the term file | Replace it with a generic description |

The script leaves code, quoted text, labels such as "**Build a new index:**", a colon at the end of a line before a list or a block, and list items that end in "-ing" alone. It reads hard-wrapped sentences whole. General AI-pattern words belong to no-ai-slop, so this script only flags the two this style adds.

## Common questions

**Is every colon a problem?** No. A colon that ends a line before a list is fine, and so is one in a label, a time, a key, code or a quote. The skill rewrites the colon in the middle of a sentence that introduces the sentence's real content.

**Why doesn't a grammar hit fail the check?** Each hit is a candidate. Some are labels or deliberate lists, and only a reader can tell. A confidential term is never a judgment call, so it is the only hit that fails a run.

**How can a change note name a removed term without leaking it?** It names the term by its line in the term file, the way the script reports it ("line 3 of the term file").

**Does it work outside Claude Code?** Yes. `agents/openai.yaml` gives Codex its name and description, the `skills` CLI installs it for other agents, and the check script runs anywhere Python 3.8 does.

## It's working if

- One quoted bad line comes back fixed on every page where the pattern appears, and the reply lists the other lines it changed.
- Every page in scope gets checked, not just the edited ones, and gitignored folders are left out. A hit outside the text you named is listed with its file and line, and the agent asks before changing it.
- Rewrites keep every fact and add none. When a claim needs confirming, the agent asks.
- Open-source READMEs have no "I", no "What I did" and no author named in the body.
- Change notes and reports never quote a confidential term.

## Tests

`skills/writing-voice/evals/` holds five test cases in the folder layout that `claude plugin eval` reads:

- a flagged portfolio line to fix
- a first-person README section to rewrite for people who build on the repo
- a draft to clean against a confidential term list
- one quoted bad line whose pattern repeats on other pages
- a content edit on one page, while another page in the site has a hit the agent must report and not fix

Each case has a prompt, an expected outcome and one file per check. Cases with input files copy them in with a small bash script, so on Windows run them from Git Bash or WSL. To run them with Claude Code (these are real, billed model runs):

```bash
claude plugin eval skills/writing-voice --scaffold --allow-tools Write,Edit,Bash
```

## Repository layout

- `skills/writing-voice/SKILL.md`: the skill
- `skills/writing-voice/scripts/check_voice.py`: the check script and its self-test
- `skills/writing-voice/agents/openai.yaml`: the skill's name and description for Codex
- `skills/writing-voice/evals/`: test cases
- `.claude-plugin/`: the plugin and marketplace manifests
- `.agents/adr/`: decision records
- `CLAUDE.md` and `AGENTS.md`: rules for agents working on this repo
- `CHANGELOG.md`: release notes

## License

This repo is MIT licensed (see LICENSE). Issues are welcome. Please describe what you ran, what the skill did and what you expected.
