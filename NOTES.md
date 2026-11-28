# chrome_manager - handoff notes (section 1 Claude Limit Closer: extension v1.5, launcher.py v1.2.1; section 2 Chrome Opener v2.1.0)

**RULE: Every time you make a new version, or change `1-claude-limit-closer-with-extention/`, `2-chrome-opener-with-py/` or a decision, update the root `README.md` (version table), the changed section's own `README.md` and `CHANGELOG.md`, and this file in the SAME commit. Also write here whatever the owner said in chat that another session would need (decisions, problems seen, test results). The owner does NOT rely on Claude's own memory: if a chat is deleted, this repo must still hold everything. Never leave these files out of date.**

Owner is non-technical: explain simply, keep replies short, propose extras before building.

## Repo layout: two independent sections (owner's decision 2026-11-28)
- `1-claude-limit-closer-with-extention/` - section 1: Chrome extension + `launcher.py` + `launcher.bat` (+ its own `README.md`).
- `2-chrome-opener-with-py/` - section 2: `Chrome_Opener.py` (Python/UI Automation tool) + `Chrome_Opener_Shut_Down.py` (+ its own `README.md`).
The two do not depend on each other; never mix their files. This file (`NOTES.md`), the root `README.md` and `.gitignore` are shared.
- Folder names start with the section number (1-, 2-). The version of each section is written in 3 places that must always agree: the title of the section's `README.md`, the top entry of its `CHANGELOG.md`, and the version table in the root `README.md` (plus the version inside the code: `extension/manifest.json`, `launcher.py` header, `TOOLKIT_VERSION` in `Chrome_Opener.py`). Each released version also gets a git tag: `claude-limit-closer-vX.Y` / `chrome-opener-vX.Y.Z` (the old tag `v1.1.0` belongs to the project before the 2026-11-27 replacement).
- `.gitignore` hides `__pycache__/` and the private runtime files (`activity_log.txt`, `profile_state.json`, `report.txt`, `launcher.log`). Never force-add them.
Everything from "What it does" down to "Current problems" below is about section 1; file paths there are relative to `1-claude-limit-closer-with-extention/`. Section 2 notes are in their own part further down.

## What it does
~35 Chrome profiles are logged in to claude.ai. The tool opens them in batches of 10,
continues paused chats, and closes each profile when the free limit is hit.

## Division of work (decided by the owner)
- `extension/` acts like a human (as in the owner's video) and closes the profile's Chrome
  when the limit / reset-time message shows ("You are out of free messages until ...").
- `launcher.py` does everything else: opens profiles (10 at a time, then the next 10,
  no rounds), keeps time, writes `launcher.log` (one file), starts the next batch.

## Extension flow (timings measured from the owner's video)
1. Page fully loaded -> wait 2.7 s -> click "View all".
2. Chat list: wait 3.25 s (first) / 2.5 s (later) -> click a chat (max 20 chats, in order).
3. Chat opened -> stay until it has loaded (title changed + page text unchanged for 3 s; up to 90 s; slow internet) -> wait 1 s -> click "Continue" (up to 12 s search). Load time of every chat is written to the log.
4. After Continue -> wait 6.75 s -> click "View all" again -> next chat.
5. Last chat done -> launcher waits 10 s -> tells extension to close Chrome.
Limit message seen at any time -> close the profile's windows immediately.
Waiting is done by background.js (covered windows slow down page timers).

## How the two talk
Launcher opens `https://claude.ai/new#cm=<profile>`; the extension reads the profile
name from the address and talks to `http://127.0.0.1:8765` (/ping, /limit, /log).

## Install / run
Load `extension/` in every profile (same folder for all; after replacing its files, the log line `walk started (extension vX)` shows which version really ran) (chrome://extensions -> Developer mode -> Load unpacked).
Remove the old claude_background_continue extension (double clicks). Close Chrome, then double-click `launcher.bat` (it runs `py launcher.py` in its own folder and keeps the window open so errors stay visible; same `py` command the old .bat used).
First test with `BATCH_SIZE = 2` in launcher.py, then send `launcher.log` for review.

## Status / known risks
- `launcher.bat` was written from the old .bat's pattern and not run on Windows yet. Not yet tested in real Chrome. Limit text is matched in English only.
- Covered windows (10 at once) may run slowly; check the log.

## Owner's rules (said in chat)
- Profiles opened one at a time, maximized, in front. Batches of 10, no rounds.
- Limit message seen -> close that profile at once. No limit -> all clicks done, wait 10 s, close.
- No extension popup / log UI. All logs in ONE file (`launcher.log`) that the owner can show to Claude.
- Send only changed files, not the whole zip. Final package name: ClaudeLimitCloser-vX.Y.zip.
- Extension is installed by hand, once per profile (owner decided 2026-11-27). Do NOT build auto-loading from one folder.
- How to talk to the owner: no lectures. Say only what blocks what the owner wants and what the OWNER must do to remove it (not how you fix it). Never give half information: on a subject give the full facts briefly so the owner can decide. Verify with evidence before advising. Nothing unverified or wrong goes into the repo.
- Owner wants simple things; propose extras first, do not build them before the owner agrees.

## Current problems (2026-11-27)
- Owner reports: the Continue / Try again click after the free limit "does not work at all" (also with extension 1.3 installed and enabled, screenshot of a paused chat).
  Cause not found: in a simulated copy of that page v1.3 did click. So v1.4 changes two things, tested only in the simulated page (jsdom), not in real Chrome:
  1. Button matching now uses the same rules as the old extension (name from text / aria-label / title, invisible characters ignored, limit text up to 12 levels above the button).
  2. Clicking sends pointer + mouse events and then click (old code sent a bare click only).
- Owner screenshot: "You are out of free messages until tomorrow at 12:50 AM" was not detected (the profile's windows did not close; the extension closes them itself, launcher not needed).
  v1.5: limit-text matching now ignores invisible characters (a simulated page with such characters was NOT detected before the fix, detected after). Not confirmed as the real cause.
  Not testable in the simulation: the text split over separate blocks (jsdom has no real innerText).
- Owner's sample video (claude_chat_continue_click_1.mp4) shows the wanted flow: /new -> "View all" -> open a chat -> "Continue" in the "Paused when your free usage ran out" bar -> chat runs -> "View all" -> next chat. It matches the walk below.
- v1.4 also writes `DIAG:` lines to `launcher.log` when the limit text is on the page but no Continue button is found (lists the real buttons it sees). If the click still fails, READ THESE LINES FIRST: they show what the real page contains.
- Logs only reach `launcher.log` while `launcher.py` is running.
- Slow internet (v1.3): the walk waits for every chat and the chat list to load (up to 90 s); load times are logged ("loaded after N s").
- Open: a profile has a 15-minute cap in launcher.py (`PROFILE_MAX_SECONDS`); with very slow internet a profile may be closed before all chats are done. Owner has not asked to change it.
- Next check: owner runs `launcher.bat` with `BATCH_SIZE = 2` and sends `launcher.log`.

## Section 2: Chrome Opener (`2-chrome-opener-with-py/`, v2.1.0) - separate from section 1
- What: Windows Python tool. Opens the owner's ~35 Chrome profiles one at a time, reads claude.ai with UI Automation (`py -m pip install psutil uiautomation`), goes to `claude.ai/chats` in the SAME tab (address bar; sidebar "View all" is the backup and is used to come back from a chat), opens each chat, clicks "Continue" / "Try again" on paused chats, closes the profile window when the free-usage limit message shows (reset time is saved in `profile_state.json`).
- `Chrome_Opener_Shut_Down.py`: owner's separate helper (closes app windows normally, then shuts Windows down). Owner decided NOT to join it with the opener.
- Runtime files next to the script: `activity_log.txt`, `profile_state.json`, `report.txt`. They are private: NEVER commit them and never paste them anywhere (the script copies text it reads from chats; a GitHub token once ended up in a log). Never write tokens or passwords into this repo or these notes.
- Owner decisions (2026-11-28):
  1. One profile at a time; when its work is done the window THIS script opened is closed (windows the owner opened himself are never closed).
  2. Work in the main tab, no extra tab; go straight to `claude.ai/chats`.
  3. Owner moves mouse / types -> script pauses, resumes after 3 quiet seconds (`USER_IDLE_RESUME_SECONDS`). The script's own clicks are not counted (Windows "last input" stamp is compared with the stamp taken right after the script's own action).
  4. After a pass the script waits for the saved reset times (+2 min) and visits those profiles again (`AUTO_RESUME`); profiles that failed or whose window was closed are retried after 5 min, at most 2 times; the PC is kept awake while waiting.
  5. `report.txt` (Bengali, one line per profile) is written after every pass.
  6. Old wrong names saved in `profile_state.json` are removed at start.
- Bugs found in the owner's logs and fixed: (a) sidebar buttons "Upgrade", "Group and sort", "New from a template", "Dismiss upgrade banner" were clicked as chats in narrow windows (sidebar wider than 19% of the window) -> the list area is now found from the page heading; (b) text of an OPEN chat was read as chat rows (a pause of the script let the page change) -> rows are only read when the page is the chat list, otherwise it goes back to the list or stops; (c) chat text such as "could not" looked like a pause message -> after 3 visits without a button the chat counts as a normal chat; (d) coming back to the list now has an address-bar backup.
- Status: tested only with simulated pages and a fake clock (no real Windows/Chrome in the test). Owner's real run on 2026-11-28 10:06 shows a complete pass (clear=27, limited=7). If something fails, read `activity_log.txt` first.
- Known: profiles that end "clear: some chats still pending" are not revisited automatically; windows left open by older runs are not closed by the script.

## Working together (several sessions use this repo)
So that one session's work never breaks another's:
1. Start: `git pull` main and read this file first.
2. Work on your own branch named `work/<topic>`, never directly on someone else's branch.
3. Before merging into main: pull main again. If main changed meanwhile, merge main into your branch and KEEP both sides' changes. Never overwrite or delete another session's work.
4. Touch only the files your task needs. If two tasks need the same file, the later one waits for the first to be merged.
5. Update `README.md` and this file in the same merge. When something becomes old or wrong, delete it.
6. Push to main only finished, working changes. Do not rewrite history (no force push).
7. Put the task you are doing under "Active work" below when you start, and remove the line when you finish.

## Active work
- (none)
