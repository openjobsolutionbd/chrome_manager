# Claude Auto Continue - changelog

Version is `VERSION` in `Claude_Auto_Continue.py`; `Claude_Auto_Continue_Inspect.py` carries the same number. It is printed when the script
starts and written at the top of the log / `inspect_report.txt`, so a report can always be matched to a version.

Rules: every merged change to this project bumps `VERSION`, adds an entry here, updates the version line in `README.md`, and gets a git tag
`auto-continue-vX.Y.Z` on the merge commit. While the tool is unfinished the major number stays 0 (0.1.x inspection, 0.2.x dry run);
1.0.0 is the first version that presses buttons, after it was checked on the real computer.

## 0.3.3
Fixes the start-up stop of 0.3.2 ("RuntimeError: This version of uiautomation is not supported").
- Cause: in uiautomation 2.0.x the client class `_AutomationClient` lives in the submodule `uiautomation.uiautomation`; `from .uiautomation import *` does not copy names that start with an underscore, so 0.3.2 never found it on the package.
- It is now looked up in the submodule first, then on the package under both names; as a last resort the COM object is created directly (what the client class does internally).
- Checked with a fake package that has the same layout (client only in the submodule); not yet run on the real Windows computer.

## 0.3.2
Fixes a crash at start-up (`AttributeError: module 'uiautomation' has no attribute 'AutomationClient'`) with the installed uiautomation 2.0.x, which left every "Continue" banner unpressed.
- The UI Automation client is looked up under both names (`_AutomationClient`, `AutomationClient`); a clear message is shown when neither exists.
- `auto.TreeScope.Descendants` (not present in uiautomation 2.0.x) is replaced by the constant `TREE_DESCENDANTS = 4`.
- `auto.CreateControlFromElement` (only `Control.CreateControlFromElement` in 2.0.x) is reached through `create_control()`; without it no button could be pressed.
- Checked against the source of uiautomation 2.0.29 only; not yet run on the real Windows computer.

## 0.3.1
- Only one copy can run at a time (the second stops with a message). `Stop_All.bat` in the repository root stops it.

## 0.3.0
Visits the other tabs and the sidebar chats, because the "Continue" banner is often not in the chat on screen.
- Every `VISIT_EVERY_MINUTES` (5) per window: switches to each other Claude tab (UI Automation Select), looks for the banner, switches back;
  then opens up to `MAX_CHATS_PER_ROUND` (8) sidebar chats one by one (UI Automation Invoke on the chat link) and returns to the first chat.
- Never while the user works in that window (it is in front) or while it is minimized; at most `MAX_VISIT_SECONDS` (90) per round.
- After a press in a chat the window is left alone for `HOLD_AFTER_PRESS_MINUTES` (5), so the chat is not navigated away from while it restarts.
- Press counters are per chat id (from the page address) and survive a restart.
- If the sidebar links have no readable address, sidebar visiting is switched off for that window (written to the log).
- Known limit: if the window was on a page that is not a chat (for example a new empty chat), it stays on the last visited chat.
- Tested with a mock browser only (tabs, sidebar, decoy button, active limit, hold, rate limit); NOT yet on real Windows/Chrome.

## 0.2.2
- `DRY_RUN = False`: the button is really pressed now (safety limits stay: 10 min gap, 3 per hour per window). Set `DRY_RUN = True` to go back.
- New `Start_All.bat` in the repository root: one click starts Chrome Opener and Claude Auto Continue (offers to restart Chrome once).
- The launchers `pause` at the end so an error stays visible.

## 0.2.1
Fixes for "only the first Chrome profile works" and for the press safety rules (still DRY RUN).
- Covered or minimized windows: Chrome freezes their pages, so the banner can not be seen. The log now says so per window
  ("window is MINIMIZED" / "page is EMPTY/FROZEN" / "page readable, no banner"), and at start the tool checks whether Chrome runs with the
  keep-awake switches and writes a WARNING with the fix when it does not (close all Chrome, start Chrome_Opener.bat).
- Everything is searched inside the web page (Document), not in Chrome's toolbar and tab strip.
- The button is searched only in the container of ITS banner text (up to 5 levels up), not in the whole window.
- Counters (10 min gap, 3 per hour) are kept per window, so a changed chat title or a switched tab can not reset them; old counters are not
  loaded after a restart (window handles change).
- A dry run no longer counts as a press, so it can not block the first real press later.

## 0.2.0
- `Claude_Auto_Continue.py` / `.bat`: DRY RUN (`DRY_RUN = True`). Every 30 s it looks at the Claude chat windows of the targeted Chrome, finds the
  known banner ("Paused when your free usage ran out" / "Stopped by a usage limit") and its exact button ("Continue" / "Try again"), and writes to
  `auto_continue_log.txt` what it WOULD press (position, whether Invoke is supported). It presses nothing.
- Safety logic already in place for 1.0.0: button must match its own banner, skipped while the limit is still active, 10 min gap and at most
  3 presses per hour per chat (kept in `auto_continue_state.json`), log pruned (3 days / 1 MB), one broken window never stops the pass.
- Lists the sidebar chat links (names only) every 30 min, for the later "visit every chat" stage.
- Tested with mocks only (40 checks); NOT yet tried on real Windows/Chrome.
- `.gitignore`: log and state files.

## 0.1.0
- New project, separate from Chrome Manager.
- `Claude_Auto_Continue_Inspect.py` / `.bat`: READ-ONLY inspection. It never clicks, types, closes or navigates. It writes `inspect_report.txt`
  (git-ignored, contains chat titles) with the controls named Continue / Try again / Paused / Stopped / usage limit / sidebar entries, all buttons
  and all links (the sidebar chat list) of the open Chrome windows, with the exact names and actions Chrome exposes.
- `README.md`: goal, known banner texts and sidebar headings, stages, and the safety rules planned for the pressing stage.
