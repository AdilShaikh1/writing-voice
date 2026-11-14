# One repo per skill

Each of the author's skills lives in its own public repo (`writing-voice`, `readme-format`, `repo-tidy` and so on) rather than in one shared collection.

A skill then has its own history, issues, releases and install command, and a change to one skill never ships another. People can install exactly the skill they want, with `npx skills add AdilShaikh1/<name>` or as a Claude Code plugin from that repo.

The cost is that shared conventions (this repo's CLAUDE.md rules, the README format, the plugin manifest) are repeated in every repo. Skills that work together refer to each other by name and call each other through the Skill tool, so no repo depends on another's files.
