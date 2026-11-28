# chrome_manager - handoff notes (section 1 Claude Limit Closer: extension v1.5, launcher.py v1.2.1; section 2 Chrome Opener v2.1.0; section 3 Only Chrome Opener v1.0.1; section 4 Chrome Opener simple v1.0.0)

**RULE: Every time you make a new version, or change `1-claude-limit-closer-with-extention/`, `2-chrome-opener-with-py/`, `3-only-chrome-opener/`, `4-chrome-opener-simple/` or a decision, update the root `README.md` (version table), the changed section's own `README.md`, `CHANGELOG.md` and `NOTES.md` (and this file if a shared rule changed) in the SAME commit. Also write in the section's `NOTES.md` whatever the owner said in chat that another session would need (decisions, problems seen, test results). The owner does NOT rely on Claude's own memory: if a chat is deleted, this repo must still hold everything. Never leave these files out of date.**

Owner is non-technical: explain simply, keep replies short, propose extras before building.

## Repo layout: four independent sections (owner's decision 2026-11-28)
- `1-claude-limit-closer-with-extention/` - section 1: Chrome extension + `launcher.py` + `launcher.bat` (+ its own `README.md`).
- `2-chrome-opener-with-py/` - section 2: `Chrome_Opener.py` (Python/UI Automation tool) + `Chrome_Opener_Shut_Down.py` (+ its own `README.md`).
- `3-only-chrome-opener/` - section 3 (added 2026-11-28 at the owner's request): `Chrome_Opener.py` (Python/UI Automation tool that ONLY opens profiles in batches of 10 and watches for the limit message) + `Chrome_Opener.bat` + `Chrome_Opener_Close_All.py/.bat` + `Chrome_Opener_Shut_Down.py` (+ its own `README.md`). It is a different program from section 2's `Chrome_Opener.py` even though the file name is the same.
- `4-chrome-opener-simple/` - section 4 (added 2026-11-28 at the owner's request, built from the `Chrome_Opener.py` the owner attached in chat): the section-2-style opener WITHOUT any memory (no reset times, no state file, one pass then stop, 5-minute cap per profile) + `Chrome_Opener_Shut_Down.py` (+ its own `README.md`). Different program from sections 2 and 3 even though the file name is the same.
**The four sections are TOTALLY independent (owner's rule, 2026-11-28).** Each section folder must hold its own copy of every file it needs (e.g. `Chrome_Opener_Shut_Down.py` exists in sections 2, 3 AND 4, and they may differ). Never make a section import, call or point to another section's files, never move a file to a shared place, and never mix their files. When you fix something in a copy, change it only in that section and record it in that section's `CHANGELOG.md`. This file (`NOTES.md`), the root `README.md` and `.gitignore` are shared. Each section has its own `NOTES.md` (owner's decision 2026-11-28) with that section's details; this root file has only the shared rules.
- Folder names start with the section number (1-, 2-, 3-, 4-). The version of each section is written in 3 places that must always agree: the title of the section's `README.md`, the top entry of its `CHANGELOG.md`, and the version table in the root `README.md` (plus the version inside the code: `extension/manifest.json`, `launcher.py` header, `TOOLKIT_VERSION` in each section's `Chrome_Opener.py`). Each released version also gets a git tag: `claude-limit-closer-vX.Y` / `chrome-opener-vX.Y.Z` / `only-chrome-opener-vX.Y.Z` / `chrome-opener-simple-vX.Y.Z` (the old tag `v1.1.0` belongs to the project before the 2026-11-27 replacement).
- `.gitignore` hides `__pycache__/` and the private runtime files (`activity_log.txt`, `profile_state.json`, `report.txt`, `launcher.log`). Never force-add them.
Section details: `1-claude-limit-closer-with-extention/NOTES.md`, `2-chrome-opener-with-py/NOTES.md` and `3-only-chrome-opener/NOTES.md` and `4-chrome-opener-simple/NOTES.md` (read the one for the section you work on).


## Owner's rules (apply to every section)
- How to talk to the owner: no lectures. Say only what blocks what the owner wants and what the OWNER must do to remove it (not how you fix it). Never give half information: on a subject give the full facts briefly so the owner can decide. Verify with evidence before advising. Nothing unverified or wrong goes into the repo.
- Owner wants simple things; propose extras first, do not build them before the owner agrees.
- The owner asked (2026-11-28) that the important facts are also kept in Claude's own memory, but the repo stays the main source: it must always hold everything another session needs.

## Working together (several sessions use this repo)
So that one session's work never breaks another's:
1. Start: `git pull` main and read this file first, then the `NOTES.md` of the section you work on.
2. Work on your own branch named `work/<topic>`, never directly on someone else's branch.
3. Before merging into main: pull main again. If main changed meanwhile, merge main into your branch and KEEP both sides' changes. Never overwrite or delete another session's work.
4. Touch only the files your task needs. If two tasks need the same file, the later one waits for the first to be merged.
5. Update `README.md`, `CHANGELOG.md` and the section's `NOTES.md` (and this file if a shared rule changed) in the same merge. When something becomes old or wrong, delete it.
6. Push to main only finished, working changes. Do not rewrite history (no force push).
7. Put the task you are doing under "Active work" below when you start, and remove the line when you finish.

## Active work
- (none)
