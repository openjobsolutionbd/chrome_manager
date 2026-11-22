"""Claude Auto Continue -- finds the "Continue" / "Try again" button of a Claude chat that stopped at the
usage limit and (when DRY_RUN is False) presses it. Version 0.2.0 runs in DRY-RUN mode: it only writes to
auto_continue_log.txt what it WOULD press. Nothing is clicked.

How it stays light: every SCAN_INTERVAL_SECONDS it asks each Claude window ONE cheap question ("is a known
banner text on this page?"). Only when the answer is yes does it look for the button. Pressing uses the
UI Automation "Invoke" action: no mouse movement, no keyboard input, no focus change.
Safety: a button is used only together with ITS banner text (Continue <-> "Paused when your free usage ran
out", Try again <-> "Stopped by a usage limit"), never while the page still shows an active limit message,
and each chat has a pause between presses and an hourly maximum, so it can never loop.
Separate project from Chrome Manager (see README.md in this folder)."""
import ctypes
import json
import os
import time
from datetime import datetime, timedelta
from pathlib import Path

try:
    import psutil
except ImportError:
    print("psutil is required. Run: py -m pip install psutil")
    input("\nPress Enter to exit...")
    raise SystemExit(1)

try:
    import uiautomation as auto
except ImportError:
    print("uiautomation is required. Run: py -m pip install uiautomation")
    input("\nPress Enter to exit...")
    raise SystemExit(1)

# Project version (see CHANGELOG.md). Bump with every merged change to this project.
# Claude_Auto_Continue_Inspect.py carries the same number; keep both equal.
VERSION = "0.2.0"
PROJECT_NAME = "Claude Auto Continue"

DRY_RUN = True                    # True: only log what would be pressed. False: really press the button.
SCAN_INTERVAL_SECONDS = 30        # how often every Claude window is checked
WINDOW_GAP_SECONDS = 0.2          # small pause between two windows, so the checks never pile up
MIN_GAP_MINUTES = 10              # per chat: at least this long between two presses
MAX_PRESSES_PER_HOUR = 3          # per chat: never more presses than this in one hour
REPEAT_LOG_MINUTES = 10           # the same situation is written to the log again only after this long
LIST_SIDEBAR_CHATS = True         # log the chat list of the sidebar (information for the next version)
SIDEBAR_LIST_EVERY_MINUTES = 30
MAX_LINKS_SCANNED = 150
MAX_SIDEBAR_NAMES_LOGGED = 20
REQUIRE_CLAUDE_IN_TITLE = True    # only windows whose title contains "Claude" are looked at
HISTORY_KEEP_HOURS = 2

# (banner text, name of ITS button). The button is only used when its own banner text is on the page.
BANNERS = (
    ("Paused when your free usage ran out", "Continue"),
    ("Stopped by a usage limit", "Try again"),
)
# While one of these is on the page the limit has NOT been reset yet: nothing is pressed.
LIMIT_ACTIVE_PHRASES = ("free messages return", "your usage limit resets", "out of free", "Upgrade to keep chatting")

LOG_RETENTION_DAYS = 3
LOG_MAX_BYTES = 1_000_000
LOG_CLEANUP_INTERVAL_SECONDS = 3600

BROWSER_LABEL = "Google Chrome"
SCRIPT_DIR = Path(__file__).resolve().parent
LOG_FILE = SCRIPT_DIR / "auto_continue_log.txt"
STATE_FILE = SCRIPT_DIR / "auto_continue_state.json"


def find_target_executable():
    candidates = [
        Path(os.environ.get("PROGRAMFILES", "")) / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("PROGRAMFILES(X86)", "")) / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe",
    ]
    return next((p for p in candidates if p.exists()), None)

TARGET_EXE = find_target_executable()

def normalized_path(value):
    try:
        return os.path.normcase(os.path.abspath(os.path.expandvars(str(value))))
    except (TypeError, ValueError, OSError):
        return ""

def is_target_executable(executable):
    return bool(TARGET_EXE and executable) and normalized_path(executable) == normalized_path(TARGET_EXE)

if TARGET_EXE is None:
    print(f"{BROWSER_LABEL} executable was not found.")
    input("\nPress Enter to exit...")
    raise SystemExit(1)

user32 = ctypes.windll.user32
EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
user32.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
user32.GetWindowThreadProcessId.restype = ctypes.c_ulong
user32.GetWindowTextW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]
user32.GetWindowTextW.restype = ctypes.c_int

_target_pid_cache = {}   # pid -> (is_target, checked_at)

def is_target_window(hwnd):
    """The window must belong to the targeted Chrome. The answer is cached per process for 30 s."""
    try:
        pid = ctypes.c_ulong(0)
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value:
            return False
        now_ts = time.time()
        cached = _target_pid_cache.get(pid.value)
        if cached is not None and now_ts - cached[1] < 30:
            return cached[0]
        result = is_target_executable(psutil.Process(pid.value).exe())
        if len(_target_pid_cache) > 256:
            _target_pid_cache.clear()
        _target_pid_cache[pid.value] = (result, now_ts)
        return result
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess, OSError):
        return False

def target_windows():
    found = []
    def cb(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            buf = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, buf, 256)
            if buf.value == "Chrome_WidgetWin_1" and is_target_window(hwnd):
                found.append(hwnd)
        return True
    user32.EnumWindows(EnumWindowsProc(cb), 0)
    return found

def window_title(hwnd):
    buf = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(hwnd, buf, 512)
    return buf.value


# ---------- small helpers ----------

def short(value, limit=60):
    value = " ".join(str(value if value is not None else "").split())
    return value if len(value) <= limit else value[:limit - 3] + "..."

def safe(getter, default=None):
    try:
        return getter()
    except Exception:
        return default

def should_scan_title(title):
    return (not REQUIRE_CLAUDE_IN_TITLE) or "claude" in (title or "").casefold()


# ---------- log (3 days, size cap) ----------

def parse_log_time(line):
    """The time at the start of a log line '[YYYY-MM-DD HH:MM:SS] ...', or None."""
    if not line.startswith("["):
        return None
    try:
        return datetime.strptime(line[1:20], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None

def prune_lines(lines, now, retention_days=LOG_RETENTION_DAYS, max_bytes=LOG_MAX_BYTES):
    """Returns (kept_lines, changed). Drops lines older than the retention, then drops the oldest lines
    until about 70% of max_bytes remain. Lines without a time stamp are kept. The newest line is ALWAYS
    kept (shortened if it alone is too big), so one huge line can never wipe the whole log."""
    cutoff = now - timedelta(days=retention_days)
    kept = []
    changed = False
    for line in lines:
        stamp = parse_log_time(line)
        if stamp is not None and stamp < cutoff:
            changed = True
            continue
        kept.append(line)
    if sum(len(l.encode("utf-8")) for l in kept) > max_bytes:
        target = int(max_bytes * 0.7)
        total = 0
        start = len(kept)
        while start > 0:
            size = len(kept[start - 1].encode("utf-8"))
            if total + size > target:
                break
            total += size
            start -= 1
        if start == len(kept) and kept:
            last = kept[-1]
            while len(last.encode("utf-8")) > target:
                last = last[: max(1, len(last) // 2)]
            kept = [last if last.endswith("\n") else last + "\n"]
        else:
            kept = kept[start:]
        changed = True
    return kept, changed

_last_log_cleanup = 0.0

def prune_log(force=False):
    global _last_log_cleanup
    now_ts = time.time()
    if not force and now_ts - _last_log_cleanup < LOG_CLEANUP_INTERVAL_SECONDS:
        return
    _last_log_cleanup = now_ts
    try:
        if not LOG_FILE.exists():
            return
        with open(LOG_FILE, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        kept, changed = prune_lines(lines, datetime.now())
        if changed:
            with open(LOG_FILE, "w", encoding="utf-8", newline="") as f:
                f.writelines(kept)
    except Exception:
        pass  # cleaning the log must never stop the tool

def log(message):
    """Prints and appends one time-stamped line to auto_continue_log.txt."""
    prune_log()
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {message}"
    try:
        print(line)
    except UnicodeEncodeError:
        print(line.encode("ascii", "replace").decode("ascii"))
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass  # logging must never stop the tool

history = {}        # chat key -> times of earlier presses (real or dry-run)
_last_logged = {}   # chat key -> (text, time): the same situation is not written again and again
_next_sidebar = {}  # window -> time of the next sidebar listing

def log_changed(key, text, now):
    previous = _last_logged.get(key)
    if previous is not None and previous[0] == text and now - previous[1] < timedelta(minutes=REPEAT_LOG_MINUTES):
        return
    _last_logged[key] = (text, now)
    log(text)


# ---------- press decision and state (pure logic) ----------

def decide_press(past_presses, now, min_gap_minutes=None, max_per_hour=None):
    """May this chat be pressed now? Returns (allowed, reason)."""
    min_gap_minutes = MIN_GAP_MINUTES if min_gap_minutes is None else min_gap_minutes
    max_per_hour = MAX_PRESSES_PER_HOUR if max_per_hour is None else max_per_hour
    if past_presses:
        since_last = now - max(past_presses)
        if since_last < timedelta(minutes=min_gap_minutes):
            return False, f"waiting between presses (minimum gap {min_gap_minutes} min)"
    recent = [t for t in past_presses if now - t < timedelta(hours=1)]
    if len(recent) >= max_per_hour:
        return False, f"hourly maximum reached ({len(recent)} presses in the last hour)"
    return True, f"press {len(recent) + 1} of at most {max_per_hour} in this hour"

def trim_history(now, keep_hours=HISTORY_KEEP_HOURS):
    cutoff = now - timedelta(hours=keep_hours)
    for key in list(history):
        history[key] = [t for t in history[key] if t >= cutoff]
        if not history[key]:
            del history[key]

def history_to_json(data):
    return {key: [t.isoformat() for t in times] for key, times in data.items()}

def history_from_json(raw):
    out = {}
    for key, values in (raw or {}).items():
        times = []
        for value in values:
            try:
                times.append(datetime.fromisoformat(value))
            except (TypeError, ValueError):
                pass
        if times:
            out[key] = times
    return out

def load_state():
    try:
        if STATE_FILE.exists():
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                history.update(history_from_json(json.load(f).get("presses")))
    except Exception as exc:
        log(f"Could not read {STATE_FILE.name} ({exc}); starting with an empty press history.")

def save_state():
    try:
        temp_file = STATE_FILE.with_suffix(STATE_FILE.suffix + ".tmp")
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump({"presses": history_to_json(history)}, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_file, STATE_FILE)   # atomic: an interrupted write cannot leave a broken file
    except Exception as exc:
        log(f"Could not save state ({exc}).")


# ---------- reading the page (UI Automation) ----------

def build_conditions(uia):
    """The UI Automation questions, built once. Names are compared without regard to letter case."""
    def name_cond(text, flags):
        return uia.CreatePropertyConditionEx(auto.PropertyId.NameProperty, text, flags)  # 3 = ignore case + substring, 1 = ignore case + exact
    def any_of(conds):
        out = conds[0]
        for extra in conds[1:]:
            out = uia.CreateOrCondition(out, extra)
        return out
    button_type = uia.CreatePropertyCondition(auto.PropertyId.ControlTypeProperty, auto.ControlType.ButtonControl)
    return {
        "any_banner": any_of([name_cond(p, 3) for p, _b in BANNERS]),
        "banner": {p: name_cond(p, 3) for p, _b in BANNERS},
        "limit": any_of([name_cond(p, 3) for p in LIMIT_ACTIVE_PHRASES]),
        "button": {b: uia.CreateAndCondition(button_type, name_cond(b, 1)) for _p, b in BANNERS},
        "link": uia.CreatePropertyCondition(auto.PropertyId.ControlTypeProperty, auto.ControlType.HyperlinkControl),
    }

def banner_hit(root, conds):
    """(banner text, its button name) when a known banner is on the page, else None. One cheap question
    first; the individual banners are only asked about when that first answer is yes."""
    if root.FindFirst(auto.TreeScope.Descendants, conds["any_banner"]) is None:
        return None
    for phrase, button in BANNERS:
        if root.FindFirst(auto.TreeScope.Descendants, conds["banner"][phrase]) is not None:
            return phrase, button
    return None

def button_control(element):
    return auto.CreateControlFromElement(element)

def has_invoke(control):
    return control is not None and safe(lambda: control.GetInvokePattern()) is not None

def press(control):
    """Presses the button through the UI Automation Invoke action. Returns (done, text)."""
    pattern = safe(lambda: control.GetInvokePattern())
    if pattern is None:
        return False, "the button offers no Invoke action"
    try:
        try:
            pattern.Invoke(waitTime=0)
        except TypeError:
            pattern.Invoke()
        return True, "pressed"
    except Exception as exc:
        return False, f"pressing failed ({exc})"

def rect_text(element):
    def get():
        r = element.CurrentBoundingRectangle
        return f"x={r.left} y={r.top} w={r.right - r.left} h={r.bottom - r.top}"
    return safe(get, "position unknown")

def handle_window(uia, conds, hwnd, title, now):
    """One check of one window. Writes to the log when there is something to say."""
    key = f"{hwnd}|{title}"
    root = uia.ElementFromHandle(hwnd)
    if root is None:
        return
    hit = banner_hit(root, conds)
    if hit is None:
        _last_logged.pop(key, None)   # nothing on the page any more: a later banner is news again
        return
    phrase, button = hit
    label = f"[window {hwnd} '{short(title, 50)}']"
    if root.FindFirst(auto.TreeScope.Descendants, conds["limit"]) is not None:
        log_changed(key, f"{label} banner '{phrase}' found, but the limit is still active on this page -> not pressing.", now)
        return
    found = root.FindAll(auto.TreeScope.Descendants, conds["button"][button])
    if found is None or found.Length == 0:
        log_changed(key, f"{label} banner '{phrase}' found, but no button named exactly '{button}' -> not pressing.", now)
        return
    element = found.GetElement(0)
    several = "" if found.Length == 1 else f" ({found.Length} buttons have that name; the first is used)"
    allowed, reason = decide_press(history.get(key, []), now)
    if not allowed:
        log_changed(key, f"{label} '{button}' button present -> not pressing: {reason}.{several}", now)
        return
    control = safe(lambda: button_control(element))
    supported = has_invoke(control)
    where = rect_text(element)
    if DRY_RUN:
        history.setdefault(key, []).append(now)
        save_state()
        log_changed(key, f"{label} DRY-RUN: would press '{button}' under '{phrase}' ({reason}; Invoke supported: "
                         f"{'yes' if supported else 'NO'}; {where}){several}", now)
        return
    if not supported:
        log_changed(key, f"{label} '{button}' button found but it offers no Invoke action -> cannot press ({where}).", now)
        return
    done, info = press(control)
    if done:
        history.setdefault(key, []).append(now)
        save_state()
    log_changed(key, f"{label} '{button}' under '{phrase}': {info} ({reason}; {where}){several}", now)

def list_sidebar_chats(uia, conds, hwnd, title, now):
    """Information only: writes the chats of the sidebar to the log (every SIDEBAR_LIST_EVERY_MINUTES).
    Nothing is opened or clicked. Needed to plan the next version (visiting each chat)."""
    due = _next_sidebar.get(hwnd)
    if due is not None and now < due:
        return
    _next_sidebar[hwnd] = now + timedelta(minutes=SIDEBAR_LIST_EVERY_MINUTES)
    root = uia.ElementFromHandle(hwnd)
    if root is None:
        return
    links = root.FindAll(auto.TreeScope.Descendants, conds["link"])
    total = 0 if links is None else links.Length
    names = []
    for i in range(min(total, MAX_LINKS_SCANNED)):
        element = links.GetElement(i)
        control = safe(lambda: button_control(element))
        address = safe(lambda: control.GetLegacyIAccessiblePattern().Value, "") or ""
        if "/chat/" in address:
            names.append(short(safe(lambda: element.CurrentName, ""), 40))
    shown = " | ".join(f"'{n}'" for n in names[:MAX_SIDEBAR_NAMES_LOGGED]) or "(none recognised)"
    log(f"[window {hwnd} '{short(title, 50)}'] sidebar: {total} links on the page, {len(names)} of them chat links: {shown}")

def check_everything(uia, conds):
    """One pass over all Claude windows. An error in one window never stops the others."""
    now = datetime.now()
    trim_history(now)
    for hwnd in target_windows():
        title = window_title(hwnd)
        if not should_scan_title(title):
            continue
        try:
            handle_window(uia, conds, hwnd, title, now)
            if LIST_SIDEBAR_CHATS:
                list_sidebar_chats(uia, conds, hwnd, title, now)
        except Exception as exc:
            log_changed(f"error|{hwnd}", f"[window {hwnd}] could not be checked: {exc}", now)
        time.sleep(WINDOW_GAP_SECONDS)

def main():
    prune_log(force=True)
    log("=" * 64)
    log(f"{PROJECT_NAME} v{VERSION} -- started. mode={'DRY-RUN (nothing is pressed)' if DRY_RUN else 'PRESSING'} "
        f"interval={SCAN_INTERVAL_SECONDS}s gap={MIN_GAP_MINUTES}min max_per_hour={MAX_PRESSES_PER_HOUR}")
    load_state()
    uia = auto.AutomationClient.instance().IUIAutomation
    conds = build_conditions(uia)
    print("\nWatching Claude windows. Press Ctrl+C to stop.\n")
    try:
        while True:
            started = time.time()
            check_everything(uia, conds)
            time.sleep(max(1.0, SCAN_INTERVAL_SECONDS - (time.time() - started)))
    except KeyboardInterrupt:
        log("Stopped by user (Ctrl+C).")
        save_state()
    input("\nPress Enter to close...")

if __name__ == "__main__":
    main()
