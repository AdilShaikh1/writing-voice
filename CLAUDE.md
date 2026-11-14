# Working on this repo

This repo holds one skill, `writing-voice`, in `skills/writing-voice/`. It is public, so everything in it is written for strangers to read.

## Keep these in step

- When the skill's behaviour changes, update `SKILL.md`, the README sections "What it does", "When to reach for it", "Usage", "What the check reports", "Common questions" and "It's working if", ADR 0002 and the check script's docstring in the same change. The exit codes appear in all of them.
- The skill is model-invoked. Its `description` is written for the model, with trigger phrases. `agents/openai.yaml` carries the Codex picker name and one-line description, and it has no `policy` block. If the skill ever becomes user-invoked, set `disable-model-invocation: true` in `SKILL.md` and `policy.allow_implicit_invocation: false` in `agents/openai.yaml` together.
- A step that needs another skill tells the agent to call the Skill tool with that skill's name, as in "Call the Skill tool with no-ai-slop".
- Every release bumps `version` in `.claude-plugin/plugin.json` and adds a `CHANGELOG.md` entry with the same number. Run `claude plugin validate .` after touching either manifest. It warns that CLAUDE.md at the root is not loaded as plugin context. That is intended, because this file is for maintainers, not plugin users. It also warns that the plugin has no icon, which matters only for a public catalog.
- Decisions that shape the repo get a short record in `.agents/adr/`.

## Before every commit

- Run `python skills/writing-voice/scripts/check_voice.py --self-test`. Every new detection rule gets a self-test sample. So does every bug found in real text, written with invented content.
- Run the check script over `README.md`, `SKILL.md`, this file and `"skills/writing-voice/evals/**/*.md"`, and read the `case.yaml` files. The repo follows its own style.
- Use no em dashes in any prose. Rewrite the sentence with a comma, a period, parentheses or a conjunction instead.

## Public safety

- No real employer, client, interviewer, colleague, phone number or private figure appears anywhere, including test fixtures. Fixtures use invented names and invented numbers.
- No job-search wording.
- Confidential term lists live in each user's own project, never here. The fixture term list under `evals/` is invented.
- When a subagent runs a test or a review, start it with a fresh context window.
