# chrome_manager

Chrome Manager (Windows). Opens many Chrome profiles on claude.ai/new, detects the free-limit message, closes the window and reopens it
at the reset time. It does NOT press "Continue" -- for that use the Chrome extension in the folder `claude_background_continue`.

| File | What it does |
|---|---|
| `Chrome_Opener.bat` | Starts Chrome Manager (open profiles, watch for the limit message, reopen at reset time). |
| `Stop_All.bat` | Stops Chrome Manager and closes the Chrome windows. |
| `Chrome_Opener_Close_All.bat` | Closes all Chrome windows of this Chrome. |
| `Chrome_Opener_Shut_Down.py` (`Shout_Down.py` is an identical copy) | Stops Chrome Manager, closes Chrome, then shuts the PC down. |

Version: `VERSION` in `Chrome_Opener.py`, history in `CHANGELOG.md`. Personal runtime files (`activity_log.txt`, `profile_state.json`) stay on your computer.
