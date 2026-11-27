# Claude Limit Closer v1.2 - handoff notes

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
3. Chat opened -> wait 3 s -> click "Continue" (up to 12 s search for slow internet).
4. After Continue -> wait 6.75 s -> click "View all" again -> next chat.
5. Last chat done -> launcher waits 10 s -> tells extension to close Chrome.
Limit message seen at any time -> close the profile's windows immediately.
Waiting is done by background.js (covered windows slow down page timers).

## How the two talk
Launcher opens `https://claude.ai/new#cm=<profile>`; the extension reads the profile
name from the address and talks to `http://127.0.0.1:8765` (/ping, /limit, /log).

## Install / run
Load `extension/` in every profile (chrome://extensions -> Developer mode -> Load unpacked).
Remove the old claude_background_continue extension (double clicks). Close Chrome, run `launcher.py`.
First test with `BATCH_SIZE = 2` in launcher.py, then send `launcher.log` for review.

## Status / known risks
- v1.2 was NOT yet tested in real Chrome. Limit text is matched in English only.
- Covered windows (10 at once) may still run slowly; check the log.
- Old files (Chrome_Opener.bat, Stop_All, Shut_Down, claude_background_continue) were
  removed on purpose on 2026-11-27; they remain in git history. Other branches untouched.
