# chrome_manager repository

Two separate projects live in this repository. Each has its own name, version, changelog and git tags. Both are Windows tools that run on
the owner's own computer.

| Project | Where | What it does | Version and history | Git tags |
|---|---|---|---|---|
| **Chrome Manager** | repository root (`Chrome_Opener*.py`, `Chrome_Opener*.bat`, `Shout_Down.py`) | Opens many Chrome profiles on claude.ai/new, detects the free-limit message, closes the window and reopens it at the reset time. Includes the Close All and Shut Down scripts. | `VERSION` in `Chrome_Opener.py`, history in `CHANGELOG.md` | `vX.Y.Z` |
| **Claude Auto Continue** | `claude_auto_continue/` | Finds the "Continue" / "Try again" button in Claude chats that stopped at the usage limit and presses it. In development: dry-run stage. | `VERSION` in `claude_auto_continue/Claude_Auto_Continue.py`, history in `claude_auto_continue/CHANGELOG.md` | `auto-continue-vX.Y.Z` |

## One-click use (Windows)
- `Start_All.bat` starts Chrome Opener and Claude Auto Continue together (Chrome must not be open before; if it is, the script offers to restart it).
- `Stop_All.bat` stops both tools and closes the Chrome windows.

Personal runtime files (`activity_log.txt`, `profile_state.json`, `claude_auto_continue/inspect_report.txt`, `auto_continue_log.txt`, `auto_continue_state.json`) stay on the owner's computer and are
git-ignored.

Changes go through a separate branch and a pull request, never straight to `main`.
