# Claude Auto Continue

Version 0.3.3 (history in `CHANGELOG.md`). Status: it presses the button (`DRY_RUN = False` in `Claude_Auto_Continue.py`; set it to `True` for a dry run that only logs). It also visits the other tabs and the sidebar chats of every profile window.

## Goal
When a Claude chat stops because the free usage limit was reached, claude.ai shows a banner with a button. Two forms are known:

| Banner text | Button |
|---|---|
| Paused when your free usage ran out. Continue to pick up where Claude stopped. | Continue |
| Stopped by a usage limit. You can try again now. | Try again |

The finished tool will find those buttons in every chat of every Chrome profile window and press them, without moving the mouse and
without bringing a window to the front, so the user's own work is not interrupted.

## Separate from Chrome Manager
This is its own project (own folder, own version, own changelog, own git tags `auto-continue-vX.Y.Z`). It runs on its own. It does not use,
change or depend on `Chrome_Opener.py`; both can run at the same time.

## What is known (from screenshots of two real windows)
- The chat list in the left sidebar has a heading that differs between windows/accounts: "Chats and tasks" in one, "Recents" in another.
  Each list shows a few chats and a "View all" entry. A blue dot next to a chat appears in some chats.
- The window title is the chat title; the address is `claude.ai/chat/<id>`.
- Not known yet, and the reason for the inspection stage: the exact names and actions (for example "Invoke") with which Chrome exposes the
  buttons and the sidebar links to Windows UI Automation.

## Stages
1. **0.1.x: inspection (read-only).** `Claude_Auto_Continue_Inspect.bat` writes `inspect_report.txt` next to it (git-ignored, contains chat
   titles). Send its content (at least sections A and C) to learn the real names.
2. **0.2.x, now: dry run.** `Claude_Auto_Continue.bat` finds the buttons and writes `auto_continue_log.txt` (git-ignored) with what it would press, without pressing. Only chats whose tab is the open/visible page of a window are seen; visiting other sidebar chats comes later (0.3.x).
3. **1.0.0: pressing.** Only after the dry run was checked on the real computer.

## Rules planned for the pressing stage
- Press only a button whose exact name is known and which sits next to the known banner text. Never "Continue with Google" or other buttons.
- A limit per chat (maximum presses and a pause between them), so a chat that is still limited cannot cause an endless loop.
- Use UI Automation actions only: no mouse movement, no keyboard input, no focus change.
- Low CPU/RAM: look at one chat at a time, and not continuously.

## How to run the dry run (Windows)
1. Double-click `Claude_Auto_Continue.bat` and leave the window open (Ctrl+C to stop).
2. When a chat shows "Continue" / "Try again", look in `auto_continue_log.txt` for `DRY-RUN: would press ...` and send the content.

## How to run the inspection (Windows)
1. Open the Claude chat window that shows "Continue" or "Try again".
2. Double-click `Claude_Auto_Continue_Inspect.bat` and press a key when asked. It reads all windows of the targeted Google Chrome; this can take up to a minute.
3. Open `inspect_report.txt` and send its content.
