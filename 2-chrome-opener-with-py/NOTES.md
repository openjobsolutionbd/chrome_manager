# Section 2: Chrome Opener - notes (v2.1.0)

Shared rules (how to work in this repo, how to talk to the owner): `../NOTES.md`. File paths below are relative to this folder. This section is independent of section 1; never mix their files.

## What it does
- Windows Python tool (`Chrome_Opener.py`, one file, ~1900 lines). Needs `py -m pip install psutil uiautomation`.
- Opens the owner's ~35 Chrome profiles one at a time, reads claude.ai with Windows UI Automation, goes to `claude.ai/chats` in the SAME tab (address bar; sidebar "View all" is the backup and is used to come back from a chat), opens each chat, clicks "Continue" / "Try again" on paused chats, closes the profile window when the free-usage limit message shows (the reset time is saved in `profile_state.json`), and comes back at the reset time.
- `Chrome_Opener_Shut_Down.py`: owner's separate helper (closes app windows normally, then shuts Windows down). Owner decided NOT to join it with the opener.

## Private runtime files (next to the script)
`activity_log.txt`, `profile_state.json`, `report.txt`. NEVER commit them and never paste them anywhere (the script copies text it reads from chats into the log; a GitHub token once ended up in a log). `.gitignore` hides them. Never write tokens or passwords into this repo or these notes.

## Owner decisions
- (2026-11-28) One profile at a time; the next opens only after the previous one's work is finished. When its work is done the window THIS script opened is closed (windows the owner opened himself are never closed).
- (2026-11-28) Work in the main tab, no extra tab; go straight to `claude.ai/chats`.
- (2026-11-28) Owner moves mouse / types -> the script pauses and resumes after 3 quiet seconds (`USER_IDLE_RESUME_SECONDS`). The script's own clicks are not counted (Windows "last input" stamp is compared with the stamp taken right after the script's own action).
- (2026-11-28) After a pass the script waits for the saved reset times (+2 min) and visits those profiles again (`AUTO_RESUME`); profiles that failed or whose window was closed are retried after 5 min, at most 2 times; the PC is kept awake while waiting.
- (2026-11-28) `report.txt` (Bengali, one line per profile) after every pass. Old wrong names saved in `profile_state.json` are removed at start.
- (2026-11-28) The script must never click sidebar buttons ("Upgrade", the filter button, the "+" template button, "Dismiss upgrade banner") as if they were chats.
- (2026-11-28) Owner decided NOT to join the shut-down script with the opener.
- (2026-11-28) Owner closes profile windows by hand while testing; this makes the profile show "window closed" in the log (not a bug).

## Settings (top of `Chrome_Opener.py`)
`AUTO_RESUME` (True), `RESUME_MARGIN_SECONDS` (120), `RETRY_FAILED_AFTER_SECONDS` (300), `MAX_FAILED_RETRIES` (2), `MIN_REVISIT_SECONDS` (600), `USER_IDLE_RESUME_SECONDS` (3), `CHAT_ACTION_MISSING_LIMIT` (3), `CLOSE_WINDOW_WHEN_DONE` (True), `PAGE_LOAD_MAX_SECONDS` (300), `CHAT_LIST_URL` (`https://claude.ai/chats`), `CHAT_LIST_LOAD_TIMEOUT_SECONDS` (180), `SAFE_CPU_PERCENT` (65) / `SAFE_RAM_PERCENT` (80: no new profile is opened while the PC is busier), `CHAT_SCAN_REVISION` (3: changing it resets the saved chat scans), `TOOLKIT_VERSION`.

## How the code is organised (for the next session)
- `main()`: load state -> loop { visit every profile with `pass_done` False via `_visit_profile` -> `print_summary` -> `write_report` -> `_next_due` / `_wait_until` the earliest reset time -> mark due profiles again }. Ctrl+C saves the state and stops.
- `_visit_profile`: open window (`launch_profile`, or reuse an existing one) -> wait until the page is readable -> limit message? `record_limit` + `close_profile_window` : `scan_chats_for_profile` -> `_recheck_limit` -> close the window if the script opened it (`info["script_launched"]`).
- `scan_chats_for_profile`: types `claude.ai/chats` in the address bar -> loop { `_on_chat_list` check -> `_chat_entry_controls` (only rows right of the sidebar; the left edge comes from the page heading via `_main_pane_left`) -> open a chat -> find "Continue" / "Try again" (`_find_chat_action`) -> click (`_click_control`) -> `_return_to_chat_list` (View all, backup: address bar) }.
- Pause on user input: `wait_for_user_idle()` is called before every click, key press, window focus and window launch; `mark_own_input()` after the script's own input.
- State file (`profile_state.json`), per profile: `reopen_at`, `limit_detected`, `chat_scan_completed`, `chat_scan_revision`, `chat_scan_seen`, `chat_action_clicked`, `chat_action_missing`, `pass_done`, `last_status`, `last_visit_at`; plus `_meta.toolkit_version`. Status words in `last_status`: `clear`, `limited`, `window_closed`, `unreadable`, `launch_failed`, `not_signed_in`, `error` (the failing ones are `FAILED_STATUS_KEYS`).

## Testing (important)
Windows UI Automation cannot run on Linux. Changes so far were tested by running single functions with fake controls (rectangles taken from the owner's screenshots), fake Chrome windows and a fake clock - never in real Chrome. Always say so, and ask the owner to run it and send `activity_log.txt`. Read that log first when something fails.

## Bugs found in the owner's logs and fixed (v2.1.0)
- Sidebar buttons "Upgrade", "Group and sort", "New from a template", "Dismiss upgrade banner" were clicked as chats in narrow windows (sidebar wider than 19% of the window) -> the list area is now found from the page heading.
- Text of an OPEN chat was read as chat rows (a pause let the page change) -> rows are only read when the page is the chat list, otherwise it goes back to the list or stops that profile's scan.
- Chat text such as "could not" looked like a pause message -> after 3 visits without a button the chat counts as a normal chat.
- Returning to the list took up to 3 minutes when "View all" failed -> address-bar backup.
- Finished profiles' windows stayed open, so several windows piled up -> they are closed when the work is done.

## Status / known
- Owner's real run on 2026-11-28 10:06 shows a complete pass (clear=27, limited=7); mouse pause works in the log.
- Profiles that end "clear: some chats still pending" are not revisited automatically; windows left open by older runs are not closed by the script.
