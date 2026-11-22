# Claude Auto Continue - changelog

Version is `VERSION` in `Claude_Auto_Continue_Inspect.py`. It is printed when the script starts and written at the top of `inspect_report.txt`,
so a report can always be matched to a version.

Rules: every merged change to this project bumps `VERSION`, adds an entry here, updates the version line in `README.md`, and gets a git tag
`auto-continue-vX.Y.Z` on the merge commit. While the tool is unfinished the major number stays 0 (0.1.x inspection, 0.2.x dry run);
1.0.0 is the first version that presses buttons, after it was checked on the real computer.

## 0.1.0
- New project, separate from Chrome Manager.
- `Claude_Auto_Continue_Inspect.py` / `.bat`: READ-ONLY inspection. It never clicks, types, closes or navigates. It writes `inspect_report.txt`
  (git-ignored, contains chat titles) with the controls named Continue / Try again / Paused / Stopped / usage limit / sidebar entries, all buttons
  and all links (the sidebar chat list) of the open Chrome windows, with the exact names and actions Chrome exposes.
- `README.md`: goal, known banner texts and sidebar headings, stages, and the safety rules planned for the pressing stage.
