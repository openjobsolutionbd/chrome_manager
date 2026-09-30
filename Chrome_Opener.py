import ctypes
import json
import os
import re
import subprocess
import time
from ctypes import wintypes
from datetime import datetime, timedelta
from pathlib import Path

try:
    import psutil
except ImportError:
    print("psutil is not installed.")
    print("Run: py -m pip install psutil")
    input("\nPress Enter to exit...")
    raise SystemExit(1)

try:
    import uiautomation as auto
except ImportError:
    print("uiautomation is not installed.")
    print("Run: py -m pip install uiautomation")
    input("\nPress Enter to exit...")
    raise SystemExit(1)

MAX_PROFILES = 35
MAX_CONCURRENT_PROFILES = 10   # never more than this many open at the same time
MAX_WAIT_FOR_WINDOW = 60
CHECK_INTERVAL_SECONDS = 0.5
TARGET_URL = "https://claude.ai/new"
# "out of free" catches "You are out of free messages until <time>" too --
# the time changes every time, so we only match the fixed part of the text.
TARGET_PHRASES = ["Upgrade to keep chatting", "out of free"]
MAX_TREE_DEPTH = 30
WM_CLOSE = 0x0010
HWND_BOTTOM = 1
SWP_NOMOVE = 0x0002
SWP_NOSIZE = 0x0001
GWL_EXSTYLE = -20
WS_EX_TOPMOST = 0x00000008
WS_EX_TRANSPARENT = 0x00000020
SWP_NOACTIVATE = 0x0010
HWND_TOPMOST = -1
HWND_NOTOPMOST = -2
GW_HWNDPREV = 3
GA_ROOT = 2
WS_EX_LAYERED = 0x00080000
LWA_ALPHA = 0x2
DEFAULT_REOPEN_WAIT_HOURS = 5  # fallback if a reset time can't be read from the message
RESET_BUFFER_MINUTES = 10      # actual reset sometimes lags a few minutes behind the stated time
RETRY_BACKOFF_MINUTES = 5      # if still limited shortly after the stated reset time, retry again this soon
STALE_THRESHOLD_MINUTES = 30   # how far in the past counts as "just lagging" vs "must mean tomorrow"
BACKOFF_BASE_MINUTES = 5       # a profile that fails to open waits this long before the next attempt...
BACKOFF_CAP_MINUTES = 60       # ...doubling each consecutive failure, up to this ceiling
IDENTIFY_MANUAL_EVERY_N_CYCLES = 10  # how often to look for manually-opened windows we haven't tagged

# Chrome freezes the page of any window fully covered by other windows, so the
# limit message never shows up in its UI tree until the user brings it forward.
# For covered windows we briefly wake them before reading, then restore them.
WAKE_MODE = "invisible"        # "invisible": wake while fully transparent + click-through (no flicker)
                               # "visible":   wake for real (brief flicker) -- switch to this if
                               #              "invisible" does not make Chrome refresh the page
WAKE_SETTLE_SECONDS = 0.5      # time given to Chrome to repaint/update after the wake
WAKE_EVERY_SECONDS = 15        # a covered window is woken and checked at most this often

# Matches "resets at 4:30 PM" or "until 2:50 AM" and captures the time.
RESET_TIME_RE = re.compile(r'(?:resets at|until)\s+(\d{1,2}:\d{2}\s*[AP]M)', re.IGNORECASE)

SCRIPT_DIR = Path(__file__).resolve().parent
LOG_FILE = SCRIPT_DIR / "activity_log.txt"
STATE_FILE = SCRIPT_DIR / "profile_state.json"

pf = os.environ.get("PROGRAMFILES", "")
pfx86 = os.environ.get("PROGRAMFILES(X86)", "")
candidates = [
    Path(pf) / "Google/Chrome/Application/chrome.exe",
    Path(pfx86) / "Google/Chrome/Application/chrome.exe",
    Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe",
]
CHROME = next((p for p in candidates if p.exists()), None)
USER_DATA = Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/User Data"

if CHROME is None:
    print("Chrome executable was not found.")
    input("\nPress Enter to exit...")
    raise SystemExit(1)

user32 = ctypes.windll.user32
EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

# Correct signatures (ctypes defaults to 32-bit int otherwise, which
# truncates HWND/HANDLE values on 64-bit Windows).
user32.SetPropW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_void_p]
user32.SetPropW.restype = ctypes.c_bool
user32.GetPropW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]
user32.GetPropW.restype = ctypes.c_void_p
user32.GetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int]
user32.GetWindowLongW.restype = ctypes.c_long
user32.SetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_long]
user32.SetWindowLongW.restype = ctypes.c_long
user32.SetLayeredWindowAttributes.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_ubyte, ctypes.c_uint]
user32.SetLayeredWindowAttributes.restype = ctypes.c_bool

user32.GetWindow.argtypes = [ctypes.c_void_p, ctypes.c_uint]
user32.GetWindow.restype = ctypes.c_void_p
user32.GetAncestor.argtypes = [ctypes.c_void_p, ctypes.c_uint]
user32.GetAncestor.restype = ctypes.c_void_p
user32.WindowFromPoint.argtypes = [wintypes.POINT]
user32.WindowFromPoint.restype = ctypes.c_void_p
user32.GetWindowRect.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.RECT)]
user32.GetWindowRect.restype = ctypes.c_bool

PROFILE_TAG_PROP = "ClaudeAutomationProfileIndex"


# ---------- logging + persistence ----------

def log(message):
    """Prints AND appends a timestamped line to activity_log.txt, so the
    history survives even if this console window is closed or crashes."""
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {message}"
    print(line)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass  # logging must never crash the main script

def load_state(plist):
    """Restores each profile's reopen_at/backoff schedule from disk, if
    present. hwnd is never restored here -- reconnect_existing_windows()
    handles finding still-open windows separately."""
    state = {p: {"hwnd": None, "reopen_at": None, "fail_count": 0, "backoff_until": None} for p in plist}
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
            restored = 0
            for profile, info in saved.items():
                if profile not in state:
                    continue
                if info.get("reopen_at"):
                    state[profile]["reopen_at"] = datetime.fromisoformat(info["reopen_at"])
                    restored += 1
                if info.get("backoff_until"):
                    state[profile]["backoff_until"] = datetime.fromisoformat(info["backoff_until"])
                state[profile]["fail_count"] = info.get("fail_count", 0)
            if restored:
                log(f"Restored {restored} pending reopen schedule(s) from {STATE_FILE.name}.")
        except Exception as exc:
            log(f"Could not read {STATE_FILE.name} ({exc}); starting with a clean schedule.")
    return state

def save_state(state):
    try:
        serializable = {
            profile: {
                "reopen_at": info["reopen_at"].isoformat() if info["reopen_at"] else None,
                "backoff_until": info["backoff_until"].isoformat() if info["backoff_until"] else None,
                "fail_count": info["fail_count"],
            }
            for profile, info in state.items()
        }
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(serializable, f, indent=2)
    except Exception as exc:
        log(f"Could not save state ({exc}).")


# ---------- window helpers ----------

def chrome_windows():
    found = []
    def cb(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            buf = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, buf, 256)
            if buf.value == "Chrome_WidgetWin_1":
                found.append(hwnd)
        return True
    user32.EnumWindows(EnumWindowsProc(cb), 0)
    return found


def set_window_opacity(hwnd, alpha):
    """alpha: 0 (fully invisible) to 255 (fully opaque). Uses a layered
    window so nothing is actually painted on screen, WITHOUT minimizing
    or hiding it -- Chrome still considers the window normally 'shown',
    so it keeps rendering/loading at full speed instead of being
    background-throttled."""
    ex_style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    user32.SetWindowLongW(hwnd, GWL_EXSTYLE, ex_style | WS_EX_LAYERED)
    user32.SetLayeredWindowAttributes(hwnd, 0, alpha, LWA_ALPHA)


def wait_for_new_window(before_handles):
    started = time.time()
    while time.time() - started < MAX_WAIT_FOR_WINDOW:
        current = chrome_windows()
        new_ones = [h for h in current if h not in before_handles]
        if new_ones:
            return new_ones[0]
        time.sleep(0.05)
    return None


def tag_window_with_profile_index(hwnd, index):
    """Stamps the window itself (at the OS level, not in our script's
    memory) with which profile it belongs to. This survives our script
    restarting -- a later run can read it straight off the window."""
    user32.SetPropW(hwnd, PROFILE_TAG_PROP, ctypes.c_void_p(index + 1))  # +1: 0 means "not found"

def get_profile_index_for_window(hwnd):
    value = user32.GetPropW(hwnd, PROFILE_TAG_PROP)
    if not value:
        return None
    return value - 1

def reconnect_existing_windows(state, plist):
    """After a restart, re-links any still-open windows we tagged in a
    previous run back to their profiles, so monitoring resumes on them
    immediately instead of treating them as untracked."""
    reconnected = 0
    for hwnd in chrome_windows():
        idx = get_profile_index_for_window(hwnd)
        if idx is None or not (0 <= idx < len(plist)):
            continue
        profile = plist[idx]
        if state[profile]["hwnd"] is None:
            state[profile]["hwnd"] = hwnd
            state[profile]["reopen_at"] = None
            reconnected += 1
    if reconnected:
        log(f"Reconnected to {reconnected} already-open window(s) from a previous session.")
    return reconnected


def load_profile_display_names(plist):
    """Reads Chrome's own 'Local State' file to map each profile FOLDER
    name (e.g. 'Profile 3') to its DISPLAY name (the name/avatar label
    shown in Chrome's UI) -- so we can try to recognize windows the user
    opened manually, which we never tagged ourselves."""
    local_state_path = USER_DATA / "Local State"
    display_to_folders = {}
    try:
        with open(local_state_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        info_cache = data.get("profile", {}).get("info_cache", {})
        for folder, info in info_cache.items():
            name = info.get("name")
            if name and folder in plist:
                display_to_folders.setdefault(name, []).append(folder)
    except Exception as exc:
        log(f"Could not read Chrome's Local State file ({exc}); "
            f"manually-opened profiles won't be auto-recognized by name.")
    return display_to_folders

def identify_manual_windows(state, plist, display_to_folders):
    """Looks at every open Chrome window we haven't tagged, and tries to
    match its visible content against a known (unambiguous) profile
    display name. Best-effort: skips any name shared by more than one
    profile, since that can't be told apart this way."""
    found = 0
    tracked_hwnds = {s["hwnd"] for s in state.values() if s["hwnd"] is not None}
    for hwnd in chrome_windows():
        if hwnd in tracked_hwnds or get_profile_index_for_window(hwnd) is not None:
            continue  # already tracked or already tagged by us
        texts = window_texts(hwnd)
        if not texts:
            continue
        for display_name, folders in display_to_folders.items():
            if len(folders) != 1:
                continue  # ambiguous -- more than one profile uses this name
            folder = folders[0]
            if state[folder]["hwnd"] is not None:
                continue
            if any(display_name in t for t in texts):
                idx = plist.index(folder)
                tag_window_with_profile_index(hwnd, idx)
                state[folder]["hwnd"] = hwnd
                state[folder]["reopen_at"] = None
                found += 1
                log(f"[{folder}] recognized a manually-opened window by profile name '{display_name}'.")
                break
    return found


# ---------- profile helpers ----------

def chrome_processes():
    out = []
    for p in psutil.process_iter(["name", "cmdline"]):
        try:
            if (p.info["name"] or "").lower() == "chrome.exe":
                out.append(p.info)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return out

def profile_running(profile):
    target = f"--profile-directory={profile}".lower()
    for info in chrome_processes():
        cmdline = info["cmdline"] or []
        if any(arg.lower() == target for arg in cmdline):
            return True
    return False

def profiles():
    result = []
    if (USER_DATA / "Default").is_dir():
        result.append("Default")
    numbered = []
    for p in USER_DATA.glob("Profile *"):
        if p.is_dir():
            try:
                numbered.append((int(p.name.split()[-1]), p.name))
            except ValueError:
                pass
    numbered.sort()
    result.extend(name for _, name in numbered)
    return result


# ---------- limit-message reading ----------

def window_texts(hwnd):
    """All visible text in the window, read via UI Automation (the same
    tree screen readers use) -- works regardless of which profile owns it."""
    try:
        control = auto.ControlFromHandle(hwnd)
        return tuple(
            c.Name for c, _d in auto.WalkControl(control, includeTop=True, maxDepth=MAX_TREE_DEPTH)
            if c.Name
        )
    except Exception:
        return None

def find_phrase(texts, phrases):
    if not texts:
        return None
    for n in texts:
        for phrase in phrases:
            if phrase in n:
                return n  # the actual matching text, so we can parse the reset time from it
    return None

EXTRA_NODES_AFTER_HIT = 25  # how many more control names to read once a phrase
                             # is found, so the reset-time sentence -- which
                             # lives in a sibling control, not the matched
                             # heading itself -- gets captured too

def scan_window(hwnd):
    """Walks the window's UI Automation tree, checking for a limit phrase
    as it goes. Once a phrase is found, keeps reading EXTRA_NODES_AFTER_HIT
    more names (instead of stopping immediately) and returns them all
    joined together, because the actual reset-time text ("It resets at
    1:00 AM...") is a separate control from the phrase that matched (e.g.
    the dialog heading "Upgrade to keep chatting") -- returning just the
    matched node's own text means compute_reopen_time() never sees the
    time and silently falls back to the default wait every time. Returns
    (hit_text_or_None, names_tuple). names_tuple is only built when no
    phrase was found (used for page-settle stability comparisons)."""
    names = []
    hit_index = None
    try:
        control = auto.ControlFromHandle(hwnd)
        for c, _d in auto.WalkControl(control, includeTop=True, maxDepth=MAX_TREE_DEPTH):
            name = c.Name
            if not name:
                continue
            names.append(name)
            if hit_index is None:
                for phrase in TARGET_PHRASES:
                    if phrase in name:
                        hit_index = len(names) - 1
                        break
            elif len(names) - hit_index > EXTRA_NODES_AFTER_HIT:
                break
    except Exception:
        return None, None
    if hit_index is not None:
        return " ".join(names[hit_index:]), None
    return None, tuple(names)

_last_wake = {}  # hwnd -> time of last wake-and-scan of that (covered) window

def is_window_covered(hwnd):
    """True if another window sits on top of this window's centre point.
    (Best-effort check; minimized windows are not handled here.)"""
    if user32.IsIconic(hwnd):
        return False
    rect = wintypes.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return False
    point = wintypes.POINT((rect.left + rect.right) // 2, (rect.top + rect.bottom) // 2)
    top = user32.WindowFromPoint(point)
    if not top:
        return False
    return user32.GetAncestor(top, GA_ROOT) != hwnd

def _nearest_normal_window_above(hwnd):
    """The closest non-topmost window directly above hwnd in the z-order,
    used to put hwnd back exactly where it was after a wake."""
    cur = user32.GetWindow(hwnd, GW_HWNDPREV)
    while cur:
        if not (user32.GetWindowLongW(cur, GWL_EXSTYLE) & WS_EX_TOPMOST):
            return cur
        cur = user32.GetWindow(cur, GW_HWNDPREV)
    return None

def scan_window_awake(hwnd):
    """Like scan_window(), but works for windows that are covered by other
    windows. Chrome stops updating the page of a fully covered window, so a
    plain scan would never see the limit message. For such windows we raise
    them (invisibly, without taking focus), scan, and restore the original
    z-order / styles. Covered windows are only checked every
    WAKE_EVERY_SECONDS; in between this returns (None, None) = no news."""
    if not user32.IsWindow(hwnd):
        return None, None
    if user32.GetForegroundWindow() == hwnd or not is_window_covered(hwnd):
        return scan_window(hwnd)
    now = time.time()
    if now - _last_wake.get(hwnd, 0) < WAKE_EVERY_SECONDS:
        return None, None
    _last_wake[hwnd] = now

    orig_ex = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    was_layered = bool(orig_ex & WS_EX_LAYERED)
    above = _nearest_normal_window_above(hwnd)
    flags = SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE
    try:
        if WAKE_MODE == "invisible":
            user32.SetWindowLongW(hwnd, GWL_EXSTYLE, orig_ex | WS_EX_LAYERED | WS_EX_TRANSPARENT)
            user32.SetLayeredWindowAttributes(hwnd, 0, 0, LWA_ALPHA)
        user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, flags)
        time.sleep(WAKE_SETTLE_SECONDS)
        return scan_window(hwnd)
    finally:
        if user32.IsWindow(hwnd):
            user32.SetWindowPos(hwnd, HWND_NOTOPMOST, 0, 0, 0, 0, flags)
            if above and user32.IsWindow(above):
                user32.SetWindowPos(hwnd, above, 0, 0, 0, 0, flags)
            if WAKE_MODE == "invisible":
                user32.SetWindowLongW(hwnd, GWL_EXSTYLE, orig_ex)
                if was_layered:
                    user32.SetLayeredWindowAttributes(hwnd, 0, 255, LWA_ALPHA)

def parse_reset_time_today(text):
    """Extracts e.g. '4:30 PM' or '2:50 AM' from the limit message and
    returns (TODAY's datetime for that time, the raw matched string) --
    the datetime may be in the past; the caller decides what that means.
    Returns (None, None) if no time was found in the text."""
    match = RESET_TIME_RE.search(text)
    if not match:
        return None, None
    raw_matched = match.group(1).strip()
    raw = raw_matched.upper().replace(" ", "")
    try:
        parsed = datetime.strptime(raw, "%I:%M%p")
    except ValueError:
        return None, None
    now = datetime.now()
    candidate = now.replace(hour=parsed.hour, minute=parsed.minute, second=0, microsecond=0)
    return candidate, raw_matched

def compute_reopen_time(hit_text):
    """Decides when to retry this profile. Adds a small buffer past the
    stated reset time (the real reset sometimes lags a few minutes behind
    it). If the stated time already passed recently, treats that as lag
    and retries soon instead of waiting until tomorrow.
    Returns (reset_at, reason) -- reason is a short human-readable string
    logged alongside the decision, so it's always visible from the log
    whether a real reset time was read from the message or the fallback
    kicked in (audit trail for how accurate this actually is in practice)."""
    now = datetime.now()
    candidate, matched_str = parse_reset_time_today(hit_text)
    if candidate is None:
        return (now + timedelta(hours=DEFAULT_REOPEN_WAIT_HOURS),
                f"no reset time in message, defaulted to {DEFAULT_REOPEN_WAIT_HOURS}h")
    if candidate > now:
        return (candidate + timedelta(minutes=RESET_BUFFER_MINUTES),
                f"message said {matched_str}")
    if now - candidate <= timedelta(minutes=STALE_THRESHOLD_MINUTES):
        return (now + timedelta(minutes=RETRY_BACKOFF_MINUTES),
                f"message said {matched_str}, already just passed -- retrying soon")
    return (candidate + timedelta(days=1, minutes=RESET_BUFFER_MINUTES),
            f"message said {matched_str}, treated as tomorrow")

def wait_for_page_or_limit(hwnd, stable_reads_required=2,
                            poll_seconds=0.3, max_wait_seconds=30):
    """Polls the window's rendered content instead of guessing a fixed
    delay. Returns the matching text the moment any of `phrases` appears.
    If it never appears, returns None once the page's content stops
    changing between reads, or after max_wait_seconds as a fallback."""
    last_signature = None
    stable_streak = 0
    started = time.time()
    while time.time() - started < max_wait_seconds:
        hit, names = scan_window(hwnd)
        if hit:
            return hit
        if names is not None and names == last_signature:
            stable_streak += 1
        else:
            stable_streak = 0
        last_signature = names
        if stable_streak >= stable_reads_required:
            return None
        time.sleep(poll_seconds)
    return None

def close_window(hwnd, poll_interval=0.1, wm_close_wait=0.6, confirm_wait=0.6):
    """Closes the whole window (every tab in that profile) as fast as
    possible: polls every poll_interval instead of blocking on a fixed
    sleep, so it returns the moment the window actually closes. Falls
    back to confirming Chrome's native 'Leave site?' prompt (if any) with
    Enter, for up to 4 attempts."""
    for _attempt in range(4):
        if not user32.IsWindow(hwnd):
            return True
        user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
        deadline = time.time() + wm_close_wait
        while time.time() < deadline:
            if not user32.IsWindow(hwnd):
                return True
            time.sleep(poll_interval)
        # Still open -- a "Leave site?" confirmation may be blocking it.
        # Its default button responds to Enter -- bring the window to the
        # foreground and confirm it.
        user32.SetForegroundWindow(hwnd)
        user32.keybd_event(0x0D, 0, 0, 0)  # VK_RETURN down
        user32.keybd_event(0x0D, 0, 2, 0)  # VK_RETURN up
        deadline = time.time() + confirm_wait
        while time.time() < deadline:
            if not user32.IsWindow(hwnd):
                return True
            time.sleep(poll_interval)
    return not user32.IsWindow(hwnd)

def launch_profile(profile, index, restore_focus_to=None):
    """Opens one profile at TARGET_URL and returns (hwnd, matched_limit_text).
    matched_limit_text is None if the profile opened cleanly.

    If restore_focus_to is given (the window the user was using right
    before this call), the new window is pushed behind it and focus is
    handed straight back -- so it opens "in the background" instead of
    interrupting whatever the user is doing."""
    before_handles = set(chrome_windows())
    try:
        subprocess.Popen(
            [str(CHROME), f"--profile-directory={profile}", "--new-window", TARGET_URL],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW
        )
    except Exception as exc:
        log(f"[{profile}] launch failed: {exc}")
        return None, None
    hwnd = wait_for_new_window(before_handles)
    if hwnd is None:
        log(f"[{profile}] window did not appear.")
        return None, None
    tag_window_with_profile_index(hwnd, index)
    hiding = restore_focus_to is not None and user32.IsWindow(restore_focus_to)
    if hiding:
        set_window_opacity(hwnd, 0)  # suppress the white flash while it loads
        user32.SetWindowPos(hwnd, HWND_BOTTOM, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE)
        user32.SetForegroundWindow(restore_focus_to)
    hit = wait_for_page_or_limit(hwnd)
    if hiding and user32.IsWindow(hwnd) and not hit:
        set_window_opacity(hwnd, 255)  # done loading and not limited -- reveal it normally
    return hwnd, hit


def close_any_limited_now(state):
    """Re-checks every currently-open window for the limit message right
    before opening a new one. Without this, a profile that hits its limit
    while the script is busy opening other profiles could sit open and
    unnoticed for a while -- its own turn in the loop might be minutes
    away. Closes and reschedules any hit immediately."""
    for profile, info in state.items():
        hwnd = info["hwnd"]
        if hwnd is None:
            continue
        if not user32.IsWindow(hwnd):
            info["hwnd"] = None
            continue
        hit, _ = scan_window_awake(hwnd)
        if hit:
            reset_at, reason = compute_reopen_time(hit)
            log(f'[{profile}] limit message found -> closing. Will reopen at {reset_at:%Y-%m-%d %H:%M} ({reason}).')
            if close_window(hwnd):
                info["hwnd"] = None
                info["reopen_at"] = reset_at
                save_state(state)
            else:
                log(f"[{profile}] could not fully close -- a tab may be blocking it.")


# ================= main: open + watch + auto-reopen, all in one loop =================

plist = profiles()[:MAX_PROFILES]

log("=" * 64)
log("SMART CHROME PROFILE OPENER + LIMIT WATCHER -- session started")
log(f"Detected profiles={len(plist)} max_concurrent={MAX_CONCURRENT_PROFILES} "
    f"check_interval={CHECK_INTERVAL_SECONDS}s")

state = load_state(plist)
reconnect_existing_windows(state, plist)
display_to_folders = load_profile_display_names(plist)
save_state(state)

print("\nOpening profiles and watching continuously. Press Ctrl+C to stop.\n")

cycle_count = 0

try:
    while True:
        now = datetime.now()
        cycle_count += 1
        if display_to_folders and cycle_count % IDENTIFY_MANUAL_EVERY_N_CYCLES == 0:
            if identify_manual_windows(state, plist, display_to_folders):
                save_state(state)
        for idx, profile in enumerate(plist):
            info = state[profile]
            hwnd = info["hwnd"]

            if hwnd is not None:
                if not user32.IsWindow(hwnd):
                    info["hwnd"] = None  # closed by the user, or something else
                    continue
                hit, _ = scan_window_awake(hwnd)
                if hit:
                    reset_at, reason = compute_reopen_time(hit)
                    log(f'[{profile}] limit message found -> closing. Will reopen at {reset_at:%Y-%m-%d %H:%M} ({reason}).')
                    if close_window(hwnd):
                        info["hwnd"] = None
                        info["reopen_at"] = reset_at
                        save_state(state)
                    else:
                        log(f"[{profile}] could not fully close -- a tab may be blocking it.")
                continue

            reopen_at = info["reopen_at"]
            if reopen_at is not None and now < reopen_at:
                continue  # still waiting for the reset time

            backoff_until = info["backoff_until"]
            if backoff_until is not None and now < backoff_until:
                continue  # this profile has been failing -- waiting out its backoff

            if profile_running(profile):
                continue  # already open outside our tracking -- leave it alone

            open_count = sum(1 for s in state.values() if s["hwnd"] is not None)
            if open_count >= MAX_CONCURRENT_PROFILES:
                continue  # at the concurrency cap -- wait for a slot to free up

            close_any_limited_now(state)  # catch anything that just hit its limit before we open another

            log(f"[{profile}] opening...")
            any_open = any(s["hwnd"] is not None for s in state.values())
            keep_focus_on = user32.GetForegroundWindow() if any_open else None
            new_hwnd, hit = launch_profile(profile, idx, restore_focus_to=keep_focus_on)
            if new_hwnd is None:
                info["fail_count"] += 1
                minutes = min(BACKOFF_BASE_MINUTES * (2 ** (info["fail_count"] - 1)), BACKOFF_CAP_MINUTES)
                info["backoff_until"] = datetime.now() + timedelta(minutes=minutes)
                log(f"[{profile}] failed to open (attempt {info['fail_count']}) -- "
                    f"backing off {minutes} min, until {info['backoff_until']:%H:%M}.")
                save_state(state)
                continue

            info["fail_count"] = 0
            info["backoff_until"] = None
            if hit:
                new_reset_at, reason = compute_reopen_time(hit)
                log(f"[{profile}] still limited -> closing again. Will reopen at {new_reset_at:%Y-%m-%d %H:%M} ({reason}).")
                close_window(new_hwnd)
                info["reopen_at"] = new_reset_at
                save_state(state)
            else:
                info["hwnd"] = new_hwnd
                info["reopen_at"] = None
                log(f"[{profile}] open and clear.")
                save_state(state)

        print(f"\r  Last check: {now:%H:%M:%S}   ", end="", flush=True)
        time.sleep(CHECK_INTERVAL_SECONDS)
except KeyboardInterrupt:
    log("Session stopped by user (Ctrl+C).")
    save_state(state)

input("\nPress Enter to close...")
