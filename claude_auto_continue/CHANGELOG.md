# Claude Auto Continue - changelog

Version is `VERSION` in `Claude_Auto_Continue.py`; `Claude_Auto_Continue_Inspect.py` carries the same number. It is printed when the script
starts and written at the top of the log / `inspect_report.txt`, so a report can always be matched to a version.

Rules: every merged change to this project bumps `VERSION`, adds an entry here, updates the version line in `README.md`, and gets a git tag
`auto-continue-vX.Y.Z` on the merge commit. While the tool is unfinished the major number stays 0 (0.1.x inspection, 0.2.x dry run);
1.0.0 is the first version that presses buttons, after it was checked on the real computer.

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
