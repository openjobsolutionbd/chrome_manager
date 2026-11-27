# Claude Limit Closer - handoff notes (extension v1.4, launcher.py v1.2.1)

**RULE: Every time you make a new version, or change `extension/`, `launcher.py` or a decision, update `README.md` and this file in the SAME commit. Also write here whatever the owner said in chat that another session would need (decisions, problems seen, test results). The owner does NOT rely on Claude's own memory: if a chat is deleted, this repo must still hold everything. Never leave these files out of date.**

Owner is non-technical: explain simply, keep replies short, propose extras before building.

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
- v1.4 also writes `DIAG:` lines to `launcher.log` when the limit text is on the page but no Continue button is found (lists the real buttons it sees). If the click still fails, READ THESE LINES FIRST: they show what the real page contains.
- Logs only reach `launcher.log` while `launcher.py` is running.
- Slow internet (v1.3): the walk waits for every chat and the chat list to load (up to 90 s); load times are logged ("loaded after N s").
- Open: a profile has a 15-minute cap in launcher.py (`PROFILE_MAX_SECONDS`); with very slow internet a profile may be closed before all chats are done. Owner has not asked to change it.
- Next check: owner runs `launcher.bat` with `BATCH_SIZE = 2` and sends `launcher.log`.

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
