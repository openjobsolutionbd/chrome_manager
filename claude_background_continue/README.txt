Claude Background Continue -- Version 2.0.0

ONE JOB
Open every chat in the Claude sidebar once. If a chat shows a usage-limit notice with a
"Continue" or "Try again" button beside it, click that button. Nothing else.

HOW IT RUNS
- A scan starts by itself when a Claude tab finishes loading in front, or is switched to.
  (Chrome Opener opens each profile on claude.ai/new, so a scan starts in every profile it opens.)
  You can also start one from the extension popup: "Scan all sidebar chats". Stop cancels it.
- The scan uses a separate inactive tab in the same window, so your current chat stays open.
  It collects the chat links from the sidebar ("View all" and scrolling included), then opens
  each chat once, waits until it has loaded, and clicks Continue / Try again if there is one.
- When the scan is finished the extra tab is closed. The original tab is reloaded once, but only
  if at least one button was clicked. That reload does not start another scan.
- All waiting happens in the extension's background part, not inside the page, so the scan runs at
  the same speed when the Chrome window is minimized or behind other windows. (Chrome Opener also
  brings minimized windows back to normal size, behind the others, without taking the focus.)

INSTALL / UPDATE (once per Chrome profile)
1. Open chrome://extensions.
2. Turn on Developer mode.
3. Click Load unpacked and select this folder (claude_background_continue).
4. Make sure the extension has site access to claude.ai (not "On click").
When the files in the folder are replaced by a newer version, Chrome reads them again the next time it
starts. If a profile still shows an old version in the popup, press the reload button of this extension
on chrome://extensions.

IMPORTANT LIMITATIONS
- Only chats listed in the sidebar are checked. If the window is so small that the sidebar collapses,
  chats behind "View all" can be missed.
- Claude may change its page. If the usage-limit wording or the /chat/ link format changes, detection
  may need an update (LIMIT_MARKERS in content.js).
- "clicked" in the log means the extension clicked; it does not prove Claude accepted the click.
- A "Try again" click may redo the previous answer and use up usage.
- Tested against a mock Claude site in Chromium, not yet on the real claude.ai or on Windows.
  Try one profile first.

PRIVACY
The extension requests access only to https://claude.ai/*. It does not send chat contents or chat
URLs anywhere. Chat URLs and the log stay in Chrome's local extension storage.

More detail (in Bengali): DOCUMENTATION.md
