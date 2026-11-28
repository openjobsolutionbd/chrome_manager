# Section 4: Chrome Opener "simple" (no memory) - notes (v1.0.0)

Shared rules (how to work in this repo, how to talk to the owner): `../NOTES.md`. File paths below are relative to this folder. This section is independent of sections 1 and 2; never mix their files. (Section 3 `3-only-chrome-opener/` is another independent tool added by another session.)

## What it does
- Windows Python tool (`Chrome_Opener.py`, one file, ~1700 lines). Needs `py -m pip install psutil uiautomation`.
- Opens the owner's Chrome profiles one at a time, reads claude.ai with Windows UI Automation. Limit message on screen -> closes that profile's window (`WM_CLOSE` on the tracked window only, no kill) and moves on. Otherwise goes to `claude.ai/chats` in the SAME tab, opens EVERY chat, clicks "Continue" / "Try again" where they appear, then the next profile. After the last profile it prints a summary, writes `report.txt` and stops.
- `Chrome_Opener_Shut_Down.py`: copy of the owner's separate helper (closes app windows normally, then shuts Windows down). Never started by the opener.

## Owner decisions (2026-11-28)
- This is the 4th independent section. Built from the `Chrome_Opener.py` the owner attached in chat ("this version works well"); everything else stays as it was, only the memory parts were removed.
- NOTHING is remembered: no reset time, no list of chats seen/clicked, no state file. Every run opens every chat of every profile and just clicks. Seeing a limit message -> close that profile; the reset time is not kept.
- "Click" means the in-chat `Continue` / `Try again` buttons only.
- After one pass over all profiles the tool stops. It does not wait for reset times and does not retry failed profiles by itself.
- (2026-11-28, later) Time cap: a running profile must be closed after a fixed time if it cannot do the wanted work. `PROFILE_MAX_SECONDS` = 5 min (owner's number, 2026-11-28; raise it if profiles with many chats get cut). Counts from the start of the visit (open + load + all chats). `_wait_for_stable_window_content` and `wait_until_page_loaded` never wait past it. Then `close_profile_window` (WM_CLOSE on the tracked window, repeated 3 times, never a kill; if it still stays open the tool moves on) and status `timeout`. Owner also wants: fast when the connection is good, patient when it is slow - the waits already depend on the page state (see Slow internet), the cap is the only fixed limit. A page that never becomes readable (`unreadable`, 300 s) is closed too. A profile that is not signed in is still left open for the owner (asked? not decided - ask).
- (2026-11-28, later) Owner's idea: open profiles straight on `https://claude.ai/chats` (`TARGET_URL`). Tested in the owner's 22:25 run: the limit message was NOT detected at first load on /chats (profile 4: "no usage limit", found only later in a chat dialog). So `TARGET_URL` is back to `https://claude.ai/new` (see `CHANGELOG.md`). The scan reuses the page when it is already the chat list (caption contains "chats" / "recents").
- A profile found limited is simply opened and closed again on every run (accepted by the owner).
- The old AI documentation file the owner showed (`AI_TOOLKIT_DOCUMENTATION.md`, describes v2.0.x with memory) was shown only as background. Do NOT use it to bring memory features back.

## Slow internet (owner's standing decision in this repo: wait until it has really loaded, never hurry)
Same waits as section 2 (now clamped by `PROFILE_MAX_SECONDS`): profile page up to `PAGE_LOAD_MAX_SECONDS` (300 s), chat list `CHAT_LIST_LOAD_TIMEOUT_SECONDS` (180 s), each chat `CHAT_PAGE_LOAD_SECONDS` (90 s); nothing is clicked before the page has settled. Section 1 follows the same idea (chat load up to 90 s, button search 12 s). On a slow connection raise these constants; do not shorten them. Difference to section 2: a profile that did not load in time (`unreadable`) or a chat that did not load is NOT retried automatically after a pause; it is tried once more inside the same visit (chats only) and otherwise waits for the next run.

## Private runtime files (next to the script)
`activity_log.txt`, `report.txt`. NEVER commit them and never paste them anywhere (the script copies text it reads from chats into the log). `.gitignore` hides them. Never write tokens or passwords into this repo or these notes.

## What was removed from the owner's attached file
`AUTO_RESUME` and its helpers (`_due_time`, `_next_due`, `_wait_until`, `_retry_counts`, retry/revisit constants), `STATE_FILE`, `load_state`, `save_state`, `_parse_dt`, `JUNK_CHAT_TITLES`, `CHAT_SCAN_REVISION`, `parse_reset_time_today`, `compute_reopen_time`, the reset regexes and constants, `--new-pass`, `pass_done`, `reopen_at`, `limit_detected`, `last_visit_at`. `record_limit(profile, info)` now only logs and closes the window.
Kept (in memory for ONE run only, they are not memory between runs): `chat_scan_seen`, `chat_action_clicked`, `chat_action_missing`, `chat_scan_completed` inside `new_info()`. They are needed so the scroll loop does not open the same chat twice and so the second scan attempt of a visit re-opens only chats that failed. `info` is created fresh by `new_info()` in `main()` every run.

## Settings (top of `Chrome_Opener.py`)
`PROFILE_MAX_SECONDS` (300), `USER_IDLE_RESUME_SECONDS` (3), `CLOSE_WINDOW_WHEN_DONE` (True), `TARGET_URL` (`https://claude.ai/new`), `PAGE_LOAD_MAX_SECONDS` (300), `CHAT_SCAN_ATTEMPTS` (2), `CHAT_ACTION_MISSING_LIMIT` (2: pause text but no button in 2 tries of one run = normal chat), `SAFE_CPU_PERCENT` (65) / `SAFE_RAM_PERCENT` (80), `CHAT_LIST_URL`, `TOOLKIT_VERSION`.

## How the code is organised
- `main()`: fresh `state` dict -> reconnect to windows already tagged / recognised by profile name -> for each profile `visit_profile` -> `print_summary` -> `write_report` -> stop. Ctrl+C prints the summary and stops.
- `_visit_profile`: open window (`launch_profile`, or reuse an existing one) -> `wait_until_page_loaded` -> limit? `record_limit` : not signed in? skip : `scan_chats_for_profile` (up to `CHAT_SCAN_ATTEMPTS`) -> `_recheck_limit` (a Continue click can bring the limit dialog back) -> close the window if the script opened it.
- `scan_chats_for_profile`: opens the chat list with the sidebar "View all" first (backup: types `claude.ai/chats` in the address bar) -> loop { `_on_chat_list` -> `_chat_entry_controls` -> open a chat -> `_find_chat_action` -> `_click_control` -> `_return_to_chat_list` }.
- `_return_to_chat_list` here is the owner's attached version: sidebar "View all", backup `Alt+Left`. Section 2 v2.1.0 differs: its backup types the chat-list address instead. Which one the owner wants is not settled; ask before changing.
- Pause on user input: `wait_for_user_idle()` before every click / key press / focus / launch; `mark_own_input()` after the script's own input.

## Testing (important)
Windows UI Automation cannot run on Linux. The time cap was checked with stubs too (cap during a scan, cap before a scan, normal run, unreadable page). The cap is checked between chats and between scan attempts, and the load waits are clamped to it; a call that hangs inside UI Automation cannot be interrupted. Done on Linux: `py_compile`, pyflakes (only old unused-variable warnings), and a stubbed run of `main()` and `_visit_profile` (fake `uiautomation`, fake `ctypes.windll`): one pass, stops at the end, no `profile_state.json` is created, limit path closes the window, limit after a click closes the window, `report.txt` is written. NOT tested in real Chrome. Always say so, and ask the owner to run it and send `activity_log.txt`. Read that log first when something fails.

## Status / known
- Run on the owner's PC on 2026-11-28 (logs of 22:25 and 23:09). In the 23:09 log (34 profiles; the log shown stops during profile 16) the first 16 profiles ended: clear 4, limited 6, window_closed 6. Why the windows were closed is not known (the owner sometimes closes windows by hand while testing).
- Seen in that log (profile 2): the owner moved the mouse right before a click; after the pause the log says "found Continue, but the button could not be clicked; leaving this chat pending". Probably the guard in `_click_control` that cancels a click when the page may have changed during a pause; not verified.
- Chats are identified by title inside one run; two chats with the same title in one profile are opened once (the second is skipped).
