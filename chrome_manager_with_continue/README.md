# chrome_manager_with_continue

Chrome Manager + Claude Auto Continue, together (Windows). The version without the Continue presser is the separate folder `chrome_manager`.

## One-click use
- **`Start_All.bat`** starts Chrome Manager (opens the profiles, closes a window at the limit and reopens it at reset time) and Claude Auto Continue
  (presses "Continue" / "Try again" in the chats that stopped at the limit; it also visits the other tabs and the sidebar chats of every profile window).
  Chrome must not be open before; if it is, the script offers to restart it, so that windows hidden behind others stay readable.
- **`Stop_All.bat`** stops both tools and closes the Chrome windows.

| Project | Where | Version and history | Git tags |
|---|---|---|---|
| **Chrome Manager** | this folder (`Chrome_Opener*.py`, `*.bat`, `Shout_Down.py`) | `VERSION` in `Chrome_Opener.py`, `CHANGELOG.md` | `vX.Y.Z` |
| **Claude Auto Continue** | `claude_auto_continue/` | `VERSION` in `claude_auto_continue/Claude_Auto_Continue.py`, `claude_auto_continue/CHANGELOG.md` | `auto-continue-vX.Y.Z` |

Personal runtime files (`activity_log.txt`, `profile_state.json`, `claude_auto_continue/inspect_report.txt`, `auto_continue_log.txt`,
`auto_continue_state.json`) stay on your computer and are git-ignored.
