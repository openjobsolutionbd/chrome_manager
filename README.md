# chrome_manager

Two separate, independent sections (Windows tools that run on your own computer). Each folder is complete on its own and does not depend on the other; use only one of them.

| Folder | What it is | Start / stop |
|---|---|---|
| [`chrome_manager/`](chrome_manager/) | **Chrome Manager** only: opens the Chrome profiles on claude.ai/new, closes a window at the free limit, reopens it at the reset time. | `Chrome_Opener.bat` / `Stop_All.bat` |
| [`chrome_manager_with_continue/`](chrome_manager_with_continue/) | **Chrome Manager + Claude Auto Continue**: the same, and in addition presses "Continue" / "Try again" in the chats that stopped at the limit (also in other tabs and sidebar chats). | `Start_All.bat` / `Stop_All.bat` |

Changes go through a separate branch and a pull request, never straight to `main`. Each section has its own README and changelog.
