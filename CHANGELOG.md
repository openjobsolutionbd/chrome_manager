# Changelog

Version number is `VERSION` in `Chrome_Opener.py`. It is printed at the start of every session in `activity_log.txt`
(`... LIMIT WATCHER v1.2.0 -- session started`), so a log line can always be matched to a version.

Rules: every merged change bumps `VERSION`, adds an entry here, and gets a git tag `vX.Y.Z` on the merge commit.
Patch (1.2.1) = bug fix, minor (1.3.0) = new behaviour.

## 1.2.0
Everything merged since v1.1.0:
- Detect limit messages faster with much lower CPU/RAM use (#3).
- Keep covered Chrome windows readable without stealing focus (#4).
- Cap activity log size in addition to 3-day retention (#5).
- Keep new Chrome windows transparent until their page has loaded (#6).
- Remove personal runtime files (`activity_log.txt`, `profile_state.json`) from the public repository.
- Add version number to the session-start log line and this changelog.

## 1.1.0
- Detect the limit message in windows covered by other windows.
