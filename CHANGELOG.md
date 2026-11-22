# Chrome Manager - changelog

This is the changelog of the project "Chrome Manager" (repository root). The other project in this repository, "Claude Auto Continue",
has its own version and changelog in `claude_auto_continue/CHANGELOG.md`.

Version number is `VERSION` in `Chrome_Opener.py`. It is printed at the start of every session in `activity_log.txt`
(`... LIMIT WATCHER vX.Y.Z -- session started`), so a log line can always be matched to a version.

Rules: every merged change that alters how Chrome Manager's tools behave bumps `VERSION`, adds an entry here, and gets a git tag
`vX.Y.Z` on the merge commit. Patch (1.2.2) = bug fix, minor (1.3.0) = new behaviour.
Changes that do not alter the tools' behaviour (documentation, the other project) keep the version.

Known limit: the log keeps only 3 days. If one session runs longer than 3 days, its start line (and so its version)
is cleaned out of the log. Only `Chrome_Opener.py` carries the version; the other scripts do not write to the log.

## 1.2.1
Shut_Down fix (`Chrome_Opener_Shut_Down.py`, and `Shout_Down.py` which stays an identical copy). No change to Chrome_Opener.py itself.
- Stops Chrome_Opener first. Before, Chrome_Opener reopened every window the shutdown script closed, so Chrome never fully closed and the shutdown was cancelled or worked only sometimes.
- Waits only as long as Chrome needs to exit. If no window is left and only the same background processes remain for 3 seconds (Chrome's "keep running in the background" setting), it shuts down anyway instead of cancelling. Before, those processes caused a cancel after 30 seconds.
- Checks for another Chrome channel (Beta/Canary) before closing anything, not after.
- Shutdown starts immediately (no countdown). If it cancels, windows that Chrome_Opener had made transparent are made visible again, and the message says Chrome_Opener was stopped.

## 1.2.0
All changes after v1.1.0, in order of the git history:
- Log the first covered-window check per window (#1).
- Replace repository contents with the new file set (#2).
- Detect limit messages faster with much lower CPU/RAM use (#3).
- Keep covered Chrome windows readable without stealing focus (#4).
- Cap activity log size in addition to 3-day retention (#5).
- Keep new Chrome windows transparent until their page has loaded (#6).
- Remove personal runtime files (`activity_log.txt`, `profile_state.json`) from the public repository.
- Add version number to the session-start log line, and this changelog.

## 1.1.0
- Detect the limit message in windows covered by other windows.
