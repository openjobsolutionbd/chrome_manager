# Chrome Manager - changelog

This is the changelog of the project "Chrome Manager" (repository root). The "Continue" button presser is the Chrome extension in the separate folder `claude_background_continue`.

Version number is `VERSION` in `Chrome_Opener.py`. It is printed at the start of every session in `activity_log.txt`
(`... LIMIT WATCHER vX.Y.Z -- session started`), so a log line can always be matched to a version.

Rules: every merged change that alters how Chrome Manager's tools behave bumps `VERSION`, adds an entry here, and gets a git tag
`vX.Y.Z` on the merge commit. Patch (1.2.2) = bug fix, minor (1.3.0) = new behaviour.
Changes that do not alter the tools' behaviour (documentation, the other project) keep the version.

Known limit: the log keeps only 3 days. If one session runs longer than 3 days, its start line (and so its version)
is cleaned out of the log. Only `Chrome_Opener.py` carries the version; the other scripts do not write to the log.

## 1.5.0
Resource limits, so the PC does not hang with many windows open:
- New limits for opening a window: average CPU at most 70% (was 80%), RAM in use at most 80% (was 90%), at least 2 GB of RAM free (`MIN_FREE_RAM_MB`). Once launching is paused it resumes only when the load is clearly lower (10 points CPU, 5 points RAM, 512 MB more free RAM), so it does not switch on and off around the limit. Windows that are already open are never closed because of these limits.
- CPU load is the average of the last 6 checks, taken once per cycle without waiting (before, one reading of 0.25 s was taken, and waited for, at every launch), so one spike while a window opens does not pause launching and the watching is not delayed.
- At least 3 seconds between the starts of two windows (`LAUNCH_SPACING_SECONDS`), so each window finishes loading before the next one starts.
- Chrome runs at "below normal" CPU priority (`LOWER_CHROME_PRIORITY`, re-applied every 20 s because Chrome keeps starting processes). When the PC is busy, the user's other programs get the CPU first; when it is idle, Chrome still uses all of it. This tool itself keeps normal priority, so the limit message is still noticed quickly.
- The pause message in the log now also shows the number of open windows and the free RAM.
- Not tried on real Windows. What these limits can not do: stop windows that are already open from growing (a very long chat uses more and more RAM). If the PC still struggles, lower `MAX_CONCURRENT_PROFILES` (or tell Claude the number you want).

## 1.4.0
Windows that are not in front keep working at full speed, minimized ones included:
- A minimized Chrome window is brought back to its normal size at once, without taking the focus, and put behind all other windows (`keep_window_restored`, switch `KEEP_WINDOWS_RESTORED`). Chrome treats a minimized window as hidden whatever its start switches say: the page is not drawn, timers slow down to one tick a minute, and the limit message (and the extension) can not be read reliably. Windows that are only covered by other windows were already handled in 1.1.0.
- More Chrome start switches for windows that are not in front: `--disable-renderer-backgrounding`, `--disable-background-timer-throttling`, and `IntensiveWakeUpThrottling` added to the (single) `--disable-features` switch. Chrome reads only one `--disable-features` switch, so all names are in the same one. A Chrome that is already running was started without them: the log says so at the start (close it once with `Chrome_Opener_Close_All.bat`, then start again).
- Not tried on real Windows. If a minimized window does not come back, the log says "STILL minimized"; `KEEP_WINDOWS_RESTORED = False` switches the feature off.

## 1.3.2
- All profiles (up to 35) may be open at the same time (was 10), so profiles without a limit can not keep the others from opening. The CPU/RAM safety pause for new launches stays, now at CPU 80% / RAM 90% (was 65% / 80%).

## 1.3.1
- At most 10 profiles are open at the same time (was 7): `MAX_CONCURRENT_PROFILES`.

## 1.3.0
Fixes found in a code review (not yet tried on real Windows):
- "Is this profile already open?" no longer reads Chrome's command line (all profiles share ONE browser process, so that check was wrong:
  the first profile could look "open" forever and later ones never). It looks for a window carrying this tool's profile tag instead.
- The profile tag on a window is now derived from the profile folder name ("Default", "Profile N"), not from the position in the list, so adding or
  deleting a profile can not attach a window to the wrong profile after a restart.
- `Enter` for a "Leave site?" question is sent only when the window really is in front (Chrome_Opener and Close_All); before, it could land in another program.
- An unexpected error in the main loop is written to the log (with details) and the tool keeps running (stops after 20 errors in a row). Before, the window just disappeared.
- The end-of-pass retry no longer counts as a second failure, so the backoff grows as documented.
- Only one Chrome_Opener can run at a time.
- New `Stop_All.bat` / `Stop_All.py` (stops the tool, then closes the Chrome windows politely).

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
