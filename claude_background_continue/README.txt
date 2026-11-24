Claude Background Continue — Version 1.5.0

WHAT'S NEW
- Continues to automatically monitor the currently open Claude page for usage-limit notices.
- Automatically starts one sidebar scan when you open or switch to a Claude tab.
- Adds "Scan all sidebar chats" in the extension popup for a manual re-scan.
- Opens a separate inactive Claude tab, collects chat links exposed by the sidebar,
  then checks those chats one by one. Your original tab is not navigated away.
- Scrolls sidebar containers to discover additional loaded chat links and tries the
  visible "View all" control before collecting links.
- Automatically attempts the matching Continue or Try again action when a usage-limit
  notice and its associated button are detected.
- Includes Stop, progress status, and per-chat log entries.
- When the scan of all sidebar chats is finished, the original Claude tab is reloaded once.

INSTALL / UPDATE
1. Extract this ZIP into a new folder.
2. Open chrome://extensions.
3. Remove the older Claude Background Continue copy to avoid duplicate extensions.
4. Turn on Developer mode.
5. Click Load unpacked and select the extracted claude-background-continue-v1.5.0 folder.
6. Make sure the extension has site access to claude.ai (not "On click").
7. Reload your Claude tab once after installation.

HOW SIDEBAR SCANNING STARTS
- The extension starts a sidebar scan automatically when a Claude tab is opened or
  selected. The reload at the end of a scan does not start another scan.
- To run it again manually, click the extension icon and choose "Scan all sidebar chats".
- The extension opens a separate inactive tab, gathers chat links it can access from
  the sidebar, and visits those chats in sequence. Your current chat stays open.
- Use Stop to cancel a running scan.

IMPORTANT LIMITATIONS
- This scans chat links exposed in the currently available Claude sidebar/list. It cannot
  guarantee that archived chats, chats hidden behind unsupported UI states, or chats not
  loaded/exposed by Claude are included.
- Claude may change its page structure. If its sidebar markup or route format changes,
  chat discovery may need an update.
- The scan is sequential and waits for each chat to load; it is not an instantaneous
  server-side search.
- "Click attempted" means the extension issued a click; it does not prove Claude accepted
  the action or that a response was generated.
- Test on a small set of chats first. A Try again action may retry the previous response.

PRIVACY
The extension requests access only to https://claude.ai/*. It does not send chat contents
or collected chat URLs to any external service. Chat URLs and diagnostic logs remain in
Chrome's local extension storage.
