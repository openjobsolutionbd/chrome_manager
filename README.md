# chrome_manager

Two separate parts. They do not depend on each other.

| Folder | What it is | Start / stop |
|---|---|---|
| [`chrome_manager/`](chrome_manager/) | **Chrome Manager** only: opens the Chrome profiles on claude.ai/new (up to 10 at the same time), closes a window at the free limit, reopens it at the reset time. | `Chrome_Opener.bat` / `Stop_All.bat` |
| [`claude_background_continue/`](claude_background_continue/) | **Chrome extension** "Claude Background Continue": clicks "Continue" / "Try again" in chats that stopped at the usage limit, scans the sidebar chats one by one, then reloads the original tab once. Install it in each Chrome profile (Load unpacked). | Chrome `chrome://extensions` |

Changes go through a separate branch and a pull request, never straight to `main`. Each section has its own README and changelog.
