# Section 3: Only Chrome Opener - notes (v1.0.0)

Shared rules (how to work in this repo, how to talk to the owner): `../NOTES.md`. File paths below are relative to this folder. This section is independent of sections 1 and 2; never mix their files.

## What it does
- Windows Python tool (`Chrome_Opener.py`, one file, ~950 lines). Needs `py -m pip install psutil uiautomation` (`Chrome_Opener.bat` installs them when missing).
- It ONLY opens the owner's Chrome profiles (each at `https://claude.ai/new`, `TARGET_URL`) and watches them for the free-usage limit message. It does NOT open chats and does NOT click "Continue" / "Try again" (that is section 2).
- Flow: `watch_open_windows` (scan every tracked window) -> if free slots exist, `due_profiles` + `launch_batch` (up to `BATCH_SIZE`, never more than `MAX_CONCURRENT_PROFILES` open) -> heartbeat line -> sleep `CHECK_INTERVAL_SECONDS`.
- When the limit message is seen: `handle_limit_hit` closes the window (`close_window`: WM_CLOSE, and Enter on Chrome's "Leave site?" prompt) and saves `reopen_at` = the reset time in the message + `RESET_BUFFER_MINUTES` (`compute_reopen_time`; if the message has no readable time the default is `DEFAULT_REOPEN_WAIT_HOURS` = 5 h).
- Unreadable pages are never counted as "clear": the window stays open, is marked `unverified_since`, logged, and re-scanned every cycle. After `UNREADABLE_NUDGE_SECONDS` it is "nudged" (`nudge_windows`: made fully transparent, raised to top without activating, held `NUDGE_HOLD_SECONDS`, then sent back to the bottom and made opaque), at most once per `NUDGE_REPEAT_SECONDS`.
- Windows are matched to profiles by a window property (`ClaudeAutomationProfileIndex`, `tag_window_with_profile_index`), so a restarted script reconnects to windows it opened earlier (`reconnect_existing_windows`). Manually opened windows are recognised by the profile display name found in the window text (`identify_manual_windows`, every `IDENTIFY_MANUAL_EVERY_N_CYCLES` cycles).
- New windows open behind the window the owner was using and focus is handed back (`launch_profile`, `restore_focus_to`); the new window is transparent while it loads.
- Only the Chrome executable found by the script is touched (`is_target_executable`); other Chrome channels are left alone.

## Files
- `Chrome_Opener.py` main tool; `Chrome_Opener.bat` launcher.
- `Chrome_Opener_Close_All.py` / `.bat`: closes every window of that Chrome (posts WM_CLOSE, confirms the "Leave site?" dialog with Enter, up to 4 rounds). This section's own copy; there is no shut-down script here (the shut-down helper lives only in section 2, owner decided not to join it with an opener).
- Private runtime files next to the script: `activity_log.txt` (entries older than `LOG_RETENTION_DAYS` = 3 are removed), `profile_state.json` (per profile: `reopen_at`, `backoff_until`, `fail_count`). NEVER commit them (`.gitignore` hides them) and never paste them anywhere. Never write tokens or passwords into this repo or these notes.

## Owner decisions
- (2026-11-28) Open 10 profiles together as a batch at the start. No need to open one by one in the background (before: max 7 open, one launch per cycle, with a full scan of all open windows before every launch).
- (2026-11-28) The limit-finished detection must work strongly in the background (several steps taken, see CHANGELOG 1.0.0).
- (2026-11-28) Added as section 3 under the folder name `3-only-chrome-opener` (owner wrote "3. only-chrome-opener"); the owner asked for documentation that lets any session understand it.
- (2026-11-28) Refilling: when windows close because of limits, the free slots are filled with the next due profiles, again as one batch (no waiting for all 10 to be free). This is my reading of the owner's wish; the owner has not been asked about it.

## What the owner's log showed (2026-11-25 to 2026-11-28, 79 limit closures)
- The main weakness was pages that could not be read: 167 "opened, but its page could not be read" lines (99 of them with `page_nodes=0`) and 77 "still unreadable after 5+ min" warnings. Some windows stayed unreadable 30-40 minutes (e.g. Profile 35 on 2026-11-25 from 19:08 to at least 19:48, Profile 11 on 2026-11-27 01:08-01:54).
- Unverified theory (NOT tested on the owner's PC): windows sent to the bottom (`HWND_BOTTOM`) are treated as hidden by Chrome, which then does not render/expose their page. That is why v1.0.0 adds the Chrome flags and the nudge. If the next log still shows many unreadable pages, look at the `diag:` part of those lines first.
- 5 closures had "no reset time in message, defaulted to 5h" (Profile 28 and 38 on 2026-11-25, Profile 15 and 38 on 2026-11-27 02:xx, Profile 9 on 2026-11-27 19:54): the reset time was not found in the text around the message (`RESET_TIME_RE` looks for "resets at / returns at / until H:MM AM/PM"). Cause not investigated.
- The old loop scanned all open windows before every single launch, which made opening slow when many windows were open.
- One run (2026-11-28 01:07) could not read Chrome's `Local State` file ("No such file"), so manually opened windows were not recognised by name in that run.

## Settings (top of `Chrome_Opener.py`)
`MAX_PROFILES` (35), `MAX_CONCURRENT_PROFILES` (10), `BATCH_SIZE` (10), `BATCH_LAUNCH_GAP_SECONDS` (0.15), `MAX_WAIT_FOR_WINDOW` (20), `CHECK_INTERVAL_SECONDS` (0.5), `TARGET_URL`, `TARGET_PHRASES` (case-insensitive substring match; includes "Upgrade to keep chatting", "out of free", "free messages return", "your usage limit resets" and 6 newer wordings), `CHROME_EXTRA_FLAGS`, `UNREADABLE_NUDGE_SECONDS` (20), `NUDGE_REPEAT_SECONDS` (60), `NUDGE_HOLD_SECONDS` (1.0), `HEARTBEAT_SECONDS` (300), `READABILITY_CHECK`, `MIN_PAGE_NODES` (3), `UNREADABLE_FLAG_SECONDS` (10), `UNREADABLE_WARN_MINUTES` (5), `DEFAULT_REOPEN_WAIT_HOURS` (5), `RESET_BUFFER_MINUTES` (10), `RETRY_BACKOFF_MINUTES` (5), `STALE_THRESHOLD_MINUTES` (30), `BACKOFF_BASE_MINUTES` / `BACKOFF_CAP_MINUTES` (5 / 60), `SAFE_CPU_PERCENT` (65), `SAFE_RAM_PERCENT` (80), `TOOLKIT_VERSION`.

## Things to know before changing the code
- A page counts as readable only when at least `MIN_PAGE_NODES` named nodes are found under the UI Automation Document node (`scan_window`). A limit phrase is checked on every node name; after a hit it reads 25 more names (`EXTRA_NODES_AFTER_HIT`) because the reset time is in a sibling control, not in the heading that matched.
- The Chrome flags only work when this script starts the Chrome browser process; if Chrome is already running Chrome ignores them. Hence the README tells the owner to run `Chrome_Opener_Close_All.bat` first. `--force-renderer-accessibility` makes Chrome use more CPU/RAM with 10 windows.
- A true parallel launch (all `Popen` calls first, windows matched afterwards) was NOT done: a new window can only be matched to its profile reliably by launching one profile and waiting for the new window handle (`wait_for_new_window`). The batch is therefore launched back-to-back (about 1 s per window) with no scanning in between.
- `resources_safe_for_launch()` is checked once before a batch, not inside it. The CPU spike caused by the batch itself can make the next check report "load high" for a moment; this only delays the next batch.

## Testing (important)
Windows UI Automation and `ctypes.windll` cannot run on Linux. Version 1.0.0 was only checked with `py_compile` and `pyflakes` (syntax, undefined names), never run on Windows or in real Chrome. Always say so, and ask the owner to run it and send `activity_log.txt`. Read that log first when something fails.

## Status / next steps
- First real run of 1.0.0 is pending. Check in the log: does the first batch show 10 "opening" lines within seconds, do "page could not be read" lines drop, do the nudge lines help, do the 5-minute "Heartbeat" lines look right.
- Open questions for the owner (not asked yet): refill behaviour (above); whether `Chrome_Opener_Close_All` should be called automatically at start.
