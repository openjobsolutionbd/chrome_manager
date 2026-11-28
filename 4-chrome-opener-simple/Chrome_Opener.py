import ctypes
import json
import os
import re
import subprocess
import time
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

TOOLKIT_VERSION = "1.0.0"

# ---------------------------------------------------------------------------
# Section 4 ("simple", NO MEMORY): ONE profile at a time, ONE pass over all profiles, then stop.
#   open profile -> wait until its Claude page has fully loaded -> check usage
#   limit -> (if clear) open EVERY chat and click Continue / Try again ->
#   next profile. Limit message seen -> close that profile's window.
# Nothing is remembered between runs: no state file, no reset times, no list of
# chats seen/clicked. Every run starts from zero. No reopening, no waiting.
# ---------------------------------------------------------------------------
MAX_PROFILES = 200             # every profile found is visited (once per run)
MAX_WAIT_FOR_WINDOW = 45       # wait for the OS window of a launched profile
TARGET_URL = "https://claude.ai/new"   # the free-usage limit message is detected reliably on this page (it was NOT detected on /chats at first load)

LAUNCH_ATTEMPTS = 2            # tries to open a profile window before giving up on it
PAGE_LOAD_MAX_SECONDS = 300    # patience for slow internet: wait this long for a page to load
PAGE_STABLE_READS = 2          # identical readable snapshots in a row = page finished loading
PAGE_POLL_SECONDS = 0.4
PAGE_READABLE_FALLBACK_SECONDS = 12  # readable this long without settling = accept as loaded
CLOSE_WINDOW_WHEN_DONE = True   # close a profile's window when its work is done (only windows this script opened)
LIMIT_RECHECK_AFTER_CLICK_SECONDS = 15  # after a Continue click the limit dialog can appear late
PROFILE_MAX_SECONDS = 5 * 60   # time cap per profile (open + load + all chats); when it is up the profile's window is closed and the next one starts
CHAT_SCAN_ATTEMPTS = 2         # chat scan tries per profile visit (chats not opened yet are tried again)
REPORT_FILE_NAME = "report.txt"
CHAT_ACTION_MISSING_LIMIT = 2     # message text but no button this many times (within one run) -> treat as a normal chat
USER_IDLE_RESUME_SECONDS = 3   # you touch mouse/keyboard -> script pauses; resumes after this many quiet seconds

# Usage-limit phrases. "usage ran out" was REMOVED in v2.0.0: the old paused-chat banner
# "Paused when your free usage ran out" is shown in old chats and is not a current limit.
TARGET_PHRASES = [
    "Upgrade to keep chatting",
    "Keep chatting with Claude Pro",  # subscription/usage-limit modal heading
    "out of free",
    "free messages return",           # may appear in one node or across adjacent UIA nodes
    "your usage limit resets",
]
# A profile showing these is not signed in to Claude: nothing to scan, move on.
NOT_SIGNED_IN_MARKERS = ("continue with google", "continue with email")

READABILITY_CHECK = True
MIN_PAGE_NODES = 3
MAX_TREE_DEPTH = 30
HWND_BOTTOM = 1
SWP_NOMOVE = 0x0002
SWP_NOSIZE = 0x0001
GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
LWA_ALPHA = 0x2

# Load protection: before opening a profile / starting a chat scan, wait (bounded) for calm.
SAFE_CPU_PERCENT = 65.0
SAFE_RAM_PERCENT = 80.0
RESOURCE_SAMPLE_SECONDS = 0.25
RESOURCE_WAIT_MAX_SECONDS = 90
CHAT_SCAN_RESOURCE_WAIT_SECONDS = 30

SCRIPT_DIR = Path(__file__).resolve().parent
LOG_FILE = SCRIPT_DIR / "activity_log.txt"

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
    print("Google Chrome executable was not found.")
    input("\nPress Enter to exit...")
    raise SystemExit(1)

user32 = ctypes.windll.user32
WM_CLOSE = 0x0010
EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

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
user32.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
user32.GetWindowThreadProcessId.restype = ctypes.c_ulong

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
kernel32.CreateMutexW.restype = ctypes.c_void_p
ERROR_ALREADY_EXISTS = 183
_instance_mutex = None

PROFILE_TAG_PROP = "ClaudeAutomationProfileIndex"
PLIST = []
state = {}

# Chat scan settings (v2.0.0: faster polling, fewer stable reads).
CHAT_LIST_URL = "https://claude.ai/chats"
CHAT_SCAN_MAX_ITEMS = 1000
CHAT_LIST_IDLE_PAGES = 3
CHAT_LIST_SCROLL_WAIT_SECONDS = 0.6
CHAT_LIST_LOAD_TIMEOUT_SECONDS = 180
CHAT_PAGE_LOAD_SECONDS = 90
CHAT_READY_FALLBACK_SECONDS = 8
CHAT_LOAD_POLL_SECONDS = 0.3
CHAT_STABLE_READS_REQUIRED = 2
CHAT_ACTION_SETTLE_SECONDS = 0.5
CHAT_ACTION_VERIFY_SECONDS = 8.0
CHAT_ACTION_VERIFY_POLL_SECONDS = 0.2
CHAT_CONTINUE_CONTEXTS = (
    "paused when your free usage ran out",
    "continue to pick up where claude stopped",
)
CHAT_BLOCKING_DIALOG_PHRASES = (
    "keep chatting with claude pro",
    "upgrade to keep chatting",
)
CHAT_ERROR_CONTEXTS = (
    "something went wrong", "there was an error", "an error occurred",
    "error generating", "network error", "request failed", "unable to",
    "could not", "couldn't", "failed to",
)

# Visit outcomes counted as "problems" in the summary and report.
FAILED_STATUS_KEYS = {"launch_failed", "unreadable", "window_closed", "timeout", "error"}
_profile_deadline = None  # set by visit_profile(); when passed, the profile is closed


def _profile_time_up():
    return _profile_deadline is not None and time.time() >= _profile_deadline


# ---------- logging + persistence ----------

LOG_RETENTION_DAYS = 3
LOG_CLEANUP_INTERVAL_SECONDS = 3600
_last_log_cleanup = 0.0


def prune_old_logs(force=False):
    """Keep only timestamped activity-log entries from the last three days."""
    global _last_log_cleanup
    now_ts = time.time()
    if not force and now_ts - _last_log_cleanup < LOG_CLEANUP_INTERVAL_SECONDS:
        return
    _last_log_cleanup = now_ts
    try:
        if not LOG_FILE.exists():
            return
        cutoff = datetime.now() - timedelta(days=LOG_RETENTION_DAYS)
        kept = []
        changed = False
        with open(LOG_FILE, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    timestamp = datetime.strptime(line[1:20], "%Y-%m-%d %H:%M:%S")
                    if line.startswith("[") and timestamp < cutoff:
                        changed = True
                        continue
                except (ValueError, IndexError):
                    pass
                kept.append(line)
        if changed:
            with open(LOG_FILE, "w", encoding="utf-8", newline="") as f:
                f.writelines(kept)
    except Exception:
        pass


def log(message):
    """Prints AND appends a timestamped line to activity_log.txt."""
    prune_old_logs()
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {message}"
    print(line)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def acquire_single_instance():
    """True if this is the only copy running. A second copy would close the first
    copy's windows (the 01:03 'window closed' chat-scan timeouts came from that)."""
    global _instance_mutex
    ctypes.set_last_error(0)
    _instance_mutex = kernel32.CreateMutexW(None, False, "Local\\ChromeProfileOpenerSingleInstance")
    return ctypes.get_last_error() != ERROR_ALREADY_EXISTS


def wait_until_calm(max_wait):
    """Sequential flow: simply wait (bounded) until CPU/RAM are within limits."""
    deadline = time.time() + max_wait
    announced = False
    while True:
        cpu = psutil.cpu_percent(interval=RESOURCE_SAMPLE_SECONDS)
        ram = psutil.virtual_memory().percent
        if cpu <= SAFE_CPU_PERCENT and ram <= SAFE_RAM_PERCENT:
            if announced:
                log(f"System load is back within limits (CPU={cpu:.0f}%, RAM={ram:.0f}%); continuing.")
            return True
        if not announced:
            log(f"System load is high (CPU={cpu:.0f}% / limit {SAFE_CPU_PERCENT:.0f}%, "
                f"RAM={ram:.0f}% / limit {SAFE_RAM_PERCENT:.0f}%). Waiting up to {max_wait}s.")
            announced = True
        if time.time() >= deadline:
            log("System load is still high; continuing anyway.")
            return False
        time.sleep(1.0)


# ---------- pause while the user is using the mouse / keyboard ----------

class _LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]


user32.GetLastInputInfo.argtypes = [ctypes.POINTER(_LASTINPUTINFO)]
user32.GetLastInputInfo.restype = ctypes.c_bool
kernel32.GetTickCount.argtypes = []
kernel32.GetTickCount.restype = ctypes.c_uint
_own_input_tick = None  # Windows' "last input" stamp right after the script's OWN click/keys


def _last_input_tick():
    info = _LASTINPUTINFO()
    info.cbSize = ctypes.sizeof(info)
    try:
        if not user32.GetLastInputInfo(ctypes.byref(info)):
            return None
    except Exception:
        return None
    return info.dwTime


def mark_own_input():
    """Call right after the script itself clicked/typed, so that is not mistaken for the user."""
    global _own_input_tick
    _own_input_tick = _last_input_tick()


def wait_for_user_idle():
    """Block while the user is moving the mouse / typing. Returns True if it had to wait."""
    global _own_input_tick
    started = None
    while True:
        last = _last_input_tick()
        if last is None or last == _own_input_tick:
            break  # no input at all since the script's own last action
        idle_ms = (kernel32.GetTickCount() - last) & 0xFFFFFFFF
        if idle_ms >= USER_IDLE_RESUME_SECONDS * 1000:
            _own_input_tick = last  # the user's input is old enough; carry on
            break
        if started is None:
            started = time.time()
            log("Mouse/keyboard in use: paused until you stop for "
                f"{USER_IDLE_RESUME_SECONDS}s.")
        time.sleep(0.25)
    if started is not None:
        log(f"Resumed after pausing {time.time() - started:.0f}s.")
        return True
    return False


def _focus_window(hwnd):
    wait_for_user_idle()
    user32.SetForegroundWindow(hwnd)



def close_profile_window(profile, info):
    """Close only this profile's Chrome window (WM_CLOSE); never kill Chrome processes."""
    hwnd = info.get("hwnd")
    if hwnd is None or not user32.IsWindow(hwnd):
        info["hwnd"] = None
        return True
    try:
        for _attempt in range(3):  # a stubborn window gets the close request again
            user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
            deadline = time.time() + 2.0
            while time.time() < deadline:
                if not user32.IsWindow(hwnd):
                    info["hwnd"] = None
                    return True
                time.sleep(0.05)
    except Exception as exc:
        log(f"[{profile}] error while requesting Chrome window close: {exc}")
    log(f"[{profile}] Chrome window did not close after 3 close requests (6 s); moving on, it stays open (never force-killed).")
    return False


def record_limit(profile, info):
    """A limit message is on screen: close only this profile's window. Nothing about it
    (not even the reset time) is remembered."""
    log(f"[{profile}] limit message found; closing its Chrome window.")
    close_profile_window(profile, info)


def new_info():
    """Bookkeeping for one profile. It lives only in memory during this run and is never
    written to disk, so every run starts from zero."""
    return {"hwnd": None, "chat_scan_completed": False, "chat_scan_seen": set(),
            "chat_action_clicked": set(), "chat_action_missing": {},
            "last_status": None}


# ---------- window helpers ----------

def _normalized_path(value):
    try:
        return os.path.normcase(os.path.abspath(os.path.expandvars(str(value))))
    except (TypeError, ValueError, OSError):
        return ""


def is_target_executable(executable):
    return bool(executable) and _normalized_path(executable) == _normalized_path(CHROME)


def is_target_window(hwnd):
    try:
        pid = ctypes.c_ulong(0)
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value:
            return False
        return is_target_executable(psutil.Process(pid.value).exe())
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess, OSError):
        return False


def chrome_windows():
    """Visible windows belonging only to this package's Chrome channel."""
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


def set_window_opacity(hwnd, alpha):
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
    user32.SetPropW(hwnd, PROFILE_TAG_PROP, ctypes.c_void_p(index + 1))


def get_profile_index_for_window(hwnd):
    value = user32.GetPropW(hwnd, PROFILE_TAG_PROP)
    if not value:
        return None
    return value - 1


def reconnect_existing_windows(state_dict, plist):
    """Re-link still-open windows tagged by an earlier run, so they are reused, not duplicated."""
    reconnected = 0
    for hwnd in chrome_windows():
        idx = get_profile_index_for_window(hwnd)
        if idx is None or not (0 <= idx < len(plist)):
            continue
        profile = plist[idx]
        if state_dict[profile]["hwnd"] is None:
            state_dict[profile]["hwnd"] = hwnd
            reconnected += 1
    if reconnected:
        log(f"Reconnected to {reconnected} already-open window(s) from a previous session.")
    return reconnected


def load_profile_display_names(plist):
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


def identify_manual_windows(state_dict, plist, display_to_folders):
    """Best-effort: match untagged, already-open Chrome windows to a profile by display name."""
    found = 0
    tracked_hwnds = {s["hwnd"] for s in state_dict.values() if s["hwnd"] is not None}
    for hwnd in chrome_windows():
        if hwnd in tracked_hwnds or get_profile_index_for_window(hwnd) is not None:
            continue
        texts = window_texts(hwnd)
        if not texts:
            continue
        for display_name, folders in display_to_folders.items():
            if len(folders) != 1:
                continue
            folder = folders[0]
            if state_dict[folder]["hwnd"] is not None:
                continue
            if any(display_name in t for t in texts):
                idx = plist.index(folder)
                tag_window_with_profile_index(hwnd, idx)
                state_dict[folder]["hwnd"] = hwnd
                found += 1
                log(f"[{folder}] recognized an already-open window by profile name '{display_name}'.")
                break
    return found


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
    try:
        control = auto.ControlFromHandle(hwnd)
        return tuple(
            c.Name for c, _d in auto.WalkControl(control, includeTop=True, maxDepth=MAX_TREE_DEPTH)
            if c.Name
        )
    except Exception:
        return None


def text_has_limit_phrase(text):
    normalized = " ".join(str(text).split()).casefold()
    return any(phrase.casefold() in normalized for phrase in TARGET_PHRASES)


EXTRA_NODES_AFTER_HIT = 60
ROLLING_LIMIT_TEXT_NODES = 8

_last_scan_info = (0, False, 0)


def scan_diag():
    total, doc_seen, page_nodes = _last_scan_info
    if total == 0 and not doc_seen:
        return "(diag: UI Automation returned nothing)"
    return f"(diag: names={total}, page_document_found={doc_seen}, page_nodes={page_nodes}, need>={MIN_PAGE_NODES})"


def scan_window(hwnd):
    """Walk the window's UI Automation tree looking for a limit phrase.
    Returns (hit_text_or_None, names_tuple_or_None, readable). 'readable' means the web
    page itself exposed enough named nodes; only readable + no phrase counts as clear."""
    global _last_scan_info
    names = []
    hit_index = None
    page_nodes = 0
    doc_seen = False
    doc_depth = None
    _last_scan_info = (0, False, 0)
    try:
        control = auto.ControlFromHandle(hwnd)
        if control is None:
            return None, None, False
        for c, depth in auto.WalkControl(control, includeTop=True, maxDepth=MAX_TREE_DEPTH):
            if isinstance(c, auto.DocumentControl):
                doc_seen = True
                if doc_depth is None:
                    doc_depth = depth
            elif doc_depth is not None and depth <= doc_depth:
                doc_depth = None
            name = c.Name
            if not name:
                continue
            names.append(name)
            if doc_depth is not None and depth > doc_depth:
                page_nodes += 1
            if hit_index is None:
                recent_start = max(0, len(names) - ROLLING_LIMIT_TEXT_NODES)
                recent_text = " ".join(names[recent_start:])
                if text_has_limit_phrase(name) or text_has_limit_phrase(recent_text):
                    hit_index = recent_start
            elif len(names) - hit_index > EXTRA_NODES_AFTER_HIT:
                break
    except Exception:
        return None, None, False
    _last_scan_info = (len(names), doc_seen, page_nodes)
    if hit_index is not None:
        return " ".join(names[hit_index:]), None, True
    readable = (page_nodes >= MIN_PAGE_NODES) if READABILITY_CHECK else True
    return None, tuple(names), readable


def wait_until_page_loaded(hwnd):
    """Block until the profile's page is fully loaded (patient on slow internet).
    Returns (outcome, payload):
      ("limit", hit_text)   a usage-limit message is on screen
      ("clear", names)      page readable, settled, no limit message
      ("window_gone", None) the window disappeared
      ("unreadable", None)  never became readable within PAGE_LOAD_MAX_SECONDS"""
    started = time.time()
    last_signature = None
    stable = 0
    readable_since = None
    last_progress_log = started
    while time.time() - started < PAGE_LOAD_MAX_SECONDS and not _profile_time_up():
        if not user32.IsWindow(hwnd):
            return "window_gone", None
        hit, names, readable = scan_window(hwnd)
        if hit:
            return "limit", hit
        now_ts = time.time()
        if readable and names is not None:
            if readable_since is None:
                readable_since = now_ts
            stable = stable + 1 if names == last_signature else 0
            last_signature = names
            if stable >= PAGE_STABLE_READS or now_ts - readable_since >= PAGE_READABLE_FALLBACK_SECONDS:
                return "clear", names
        else:
            readable_since = None
            stable = 0
            last_signature = None
        if now_ts - last_progress_log >= 30:
            log(f"Still waiting for the page to finish loading ({int(now_ts - started)}s)...")
            last_progress_log = now_ts
        time.sleep(PAGE_POLL_SECONDS)
    return "unreadable", None


def looks_signed_out(names):
    return any(marker in str(n).casefold() for n in names for marker in NOT_SIGNED_IN_MARKERS)


def launch_profile(profile, index, restore_focus_to=None):
    """Open one profile at TARGET_URL. Returns the new window handle or None.
    The page itself is verified afterwards by wait_until_page_loaded()."""
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
        return None
    hwnd = wait_for_new_window(before_handles)
    if hwnd is None:
        log(f"[{profile}] window did not appear.")
        return None
    tag_window_with_profile_index(hwnd, index)
    hiding = restore_focus_to is not None and user32.IsWindow(restore_focus_to)
    if hiding:
        set_window_opacity(hwnd, 0)
        user32.SetWindowPos(hwnd, HWND_BOTTOM, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE)
        user32.SetForegroundWindow(restore_focus_to)
    if hiding and user32.IsWindow(hwnd):
        set_window_opacity(hwnd, 255)
    return hwnd


# ---------- Claude chat-list Continue / Try again helper ----------
# UI Automation property reads are slow COM calls. Each control is read once per
# snapshot and cached on the object (a fresh walk creates fresh objects).

def _control_name(control):
    cached = getattr(control, "_tk_name", None)
    if cached is not None:
        return cached
    try:
        value = (control.Name or "").strip()
    except Exception:
        return ""
    try:
        control._tk_name = value
    except Exception:
        pass
    return value


def _control_type(control):
    cached = getattr(control, "_tk_type", None)
    if cached is not None:
        return cached
    try:
        value = str(control.ControlTypeName or "")
    except Exception:
        return ""
    try:
        control._tk_type = value
    except Exception:
        pass
    return value


def _control_rect(control):
    cached = getattr(control, "_tk_rect", None)
    if cached is not None:
        return cached or None
    try:
        rect = control.BoundingRectangle
        value = (int(rect.left), int(rect.top), int(rect.right), int(rect.bottom))
    except Exception:
        value = False
    try:
        control._tk_rect = value
    except Exception:
        pass
    return value or None


def _rect_center(rect):
    return ((rect[0] + rect[2]) // 2, (rect[1] + rect[3]) // 2)


def _window_caption(hwnd):
    try:
        buf = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(hwnd, buf, len(buf))
        return buf.value
    except Exception:
        return ""


def _walk_window(hwnd):
    try:
        root = auto.ControlFromHandle(hwnd)
        if root is None:
            return root, []
        return root, list(auto.WalkControl(root, includeTop=True, maxDepth=MAX_TREE_DEPTH))
    except Exception:
        return None, []


def _chrome_tab_count(hwnd):
    _root, walked = _walk_window(hwnd)
    count = sum(1 for control, _depth in walked if _control_type(control) == "TabItemControl")
    return count if count > 0 else None


def _wait_for_new_scan_tab(hwnd, old_caption, old_tab_count, timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline and user32.IsWindow(hwnd):
        caption = _window_caption(hwnd).casefold()
        tab_count = _chrome_tab_count(hwnd)
        if old_tab_count is not None and tab_count is not None and tab_count > old_tab_count:
            return True
        if caption != old_caption.casefold() and ("recents" in caption or "chats" in caption):
            return True
        time.sleep(0.2)
    return False


def _has_blocking_usage_dialog(names):
    """True for Claude's account-level Pro upsell modal, not an in-chat banner."""
    cleaned = [str(name).casefold() for name in names if name]
    joined = " ".join(cleaned)
    if any(phrase in joined for phrase in CHAT_BLOCKING_DIALOG_PHRASES):
        return True
    for start in range(len(cleaned)):
        for end in range(start + 1, min(start + 8, len(cleaned)) + 1):
            block = " ".join(cleaned[start:end])
            if any(phrase in block for phrase in CHAT_BLOCKING_DIALOG_PHRASES):
                return True
    return False


def _wait_for_stable_window_content(hwnd, ready_check, timeout, stable_reads_required=None, diagnostic_out=None):
    """Wait for an expected page and a stable UIA tree. ready_check may set
    diag['fast_ready']=True to accept the page immediately (e.g. the Continue
    button is already visible), skipping the extra stable reads."""
    required = stable_reads_required or CHAT_STABLE_READS_REQUIRED
    deadline = time.time() + timeout
    if _profile_deadline is not None:
        deadline = min(deadline, _profile_deadline)  # never wait past the profile's time cap
    previous_signature = None
    stable_reads = 0
    last_progress_log = time.time()
    diag = diagnostic_out if diagnostic_out is not None else {}
    diag.update({
        "caption": _window_caption(hwnd),
        "window_accessible": False,
        "named_controls": 0,
        "ready_check": False,
        "minimum_controls_met": False,
        "busy_markers": [],
        "stable_reads": 0,
        "required_stable_reads": required,
        "blocking_usage_dialog": False,
        "sample_controls": [],
    })
    while time.time() < deadline and user32.IsWindow(hwnd):
        root, walked = _walk_window(hwnd)
        if root is None or not walked:
            stable_reads = 0
            previous_signature = None
            diag.update({
                "caption": _window_caption(hwnd),
                "window_accessible": bool(root is not None),
                "named_controls": 0,
                "ready_check": False,
                "minimum_controls_met": False,
                "busy_markers": [],
                "stable_reads": 0,
                "sample_controls": [],
            })
            time.sleep(CHAT_LOAD_POLL_SECONDS)
            continue
        named_controls = []
        for control, _depth in walked:
            nm = _control_name(control)
            if nm:
                named_controls.append((_control_type(control), nm))
        signature = tuple(named_controls)
        names = [name.casefold() for _kind, name in named_controls]
        diag.update({
            "caption": _window_caption(hwnd),
            "window_accessible": True,
            "named_controls": len(named_controls),
            "sample_controls": [name for _kind, name in named_controls[:10]],
        })
        if _has_blocking_usage_dialog(names):
            diag.update({"blocking_usage_dialog": True, "ready_check": False,
                         "minimum_controls_met": len(named_controls) >= 3,
                         "stable_reads": stable_reads})
            log("Claude's account-level usage dialog is open; chat scanning is paused so dialog text is not mistaken for chat titles.")
            return False
        busy_markers = [
            marker for marker in ("loading conversation", "loading chats", "loading...", "loading…", "connecting...")
            if any(marker in name for name in names)
        ]
        diag.pop("fast_ready", None)
        condition_ready = bool(ready_check(root, walked, names))
        fast = bool(diag.pop("fast_ready", False))
        minimum_controls_met = len(named_controls) >= 3
        ready = condition_ready and minimum_controls_met and not busy_markers
        if ready and signature == previous_signature:
            stable_reads += 1
        else:
            stable_reads = 0
        previous_signature = signature
        diag.update({
            "ready_check": condition_ready,
            "minimum_controls_met": minimum_controls_met,
            "busy_markers": busy_markers,
            "stable_reads": stable_reads,
            "required_stable_reads": required,
        })
        if ready and (fast or stable_reads >= required):
            diag["timed_out"] = False
            return True
        if time.time() - last_progress_log >= 30:
            log("Still waiting for Claude's page to finish loading; the chat scan is paused until the window content is stable.")
            last_progress_log = time.time()
        time.sleep(CHAT_LOAD_POLL_SECONDS)
    diag["timed_out"] = True
    diag["window_still_exists"] = bool(user32.IsWindow(hwnd))
    diag["caption"] = _window_caption(hwnd) if user32.IsWindow(hwnd) else "<window closed>"
    diag["stable_reads"] = stable_reads
    diag["required_stable_reads"] = required
    return False


def _format_wait_diagnostics(details):
    d = details or {}
    samples = " | ".join(str(x).replace("\n", " ")[:70] for x in d.get("sample_controls", [])[:6])
    busy = ", ".join(d.get("busy_markers", [])) or "none"
    return (
        f"caption={d.get('caption', '<unknown>')!r}; "
        f"controls={d.get('named_controls', 0)}; "
        f"page_ready={d.get('ready_check', False)}; "
        f"minimum_controls={d.get('minimum_controls_met', False)}; "
        f"busy={busy}; "
        f"stable_reads={d.get('stable_reads', 0)}/{d.get('required_stable_reads', CHAT_STABLE_READS_REQUIRED)}; "
        f"blocking_dialog={d.get('blocking_usage_dialog', False)}; "
        f"conditions={d.get('readiness_conditions', {})}; "
        f"sample_controls=[{samples}]"
    )


def _wait_for_chat_list(hwnd, timeout=CHAT_LIST_LOAD_TIMEOUT_SECONDS, stable_reads_required=None, diagnostic_out=None):
    diag = diagnostic_out if diagnostic_out is not None else {}

    def list_ready(root, walked, names):
        caption = _window_caption(hwnd).casefold()
        root_rect = _control_rect(root)
        pane_left = root_rect[0] + int((root_rect[2] - root_rect[0]) * 0.19) if root_rect else 0
        main_heading = False
        if root_rect:
            for control, _depth in walked:
                if _control_name(control).casefold() == "chats and tasks":
                    rect = _control_rect(control)
                    if rect and rect[0] >= pane_left and rect[1] <= root_rect[1] + 170:
                        main_heading = True
                        break
        page_identified = bool("recents" in caption or "chats - claude" in caption
                               or "chats and tasks - claude" in caption or main_heading)
        empty_state = any(
            marker in name
            for name in names
            for marker in ("no chats", "no conversations", "no results")
        )
        has_chat_rows = bool(_chat_entry_controls(hwnd, root, walked)) if page_identified else False
        conditions = {
            "main_chat_page_identified": page_identified,
            "main_chat_heading_visible": main_heading,
            "visible_chat_row_found": has_chat_rows,
            "explicit_empty_state_found": empty_state,
        }
        diag["readiness_conditions"] = conditions
        diag["ready_check"] = page_identified and (has_chat_rows or empty_state)
        return diag["ready_check"]

    return _wait_for_stable_window_content(
        hwnd, list_ready, timeout, stable_reads_required=stable_reads_required,
        diagnostic_out=diag,
    )


def _main_chat_list_heading_present(hwnd, walked=None, root=None):
    if walked is None or root is None:
        root, controls = _walk_window(hwnd)
    else:
        controls = walked
    root_rect = _control_rect(root) if root is not None else None
    if root_rect is None:
        return False
    pane_left = root_rect[0] + int((root_rect[2] - root_rect[0]) * 0.19)
    for control, _depth in controls:
        if _control_name(control).casefold() == "chats and tasks":
            rect = _control_rect(control)
            if rect and rect[0] >= pane_left and rect[1] <= root_rect[1] + 180:
                return True
    return False


def _is_composer_name(name):
    """Claude's message box is labelled differently in different places: a new chat says
    'How can I help you today?', but INSIDE a conversation it is just 'Reply' (or
    'Reply to Claude...'). The old check only knew 'write a message' / 'message claude',
    so every chat without a paused banner looked 'not loaded' for 180 s."""
    text = str(name).casefold().strip().rstrip("….. ")
    return (text == "reply" or text.startswith("reply to claude")
            or "write a message" in text or "message claude" in text
            or "how can claude help" in text or "how can i help" in text
            or "claude is ai and can make mistakes" in text)


def _wait_for_chat_page(hwnd, timeout=CHAT_PAGE_LOAD_SECONDS, previous_caption=None, diagnostic_out=None):
    old_caption = (previous_caption or "").strip().casefold()
    diag = diagnostic_out if diagnostic_out is not None else {}
    started_at = time.time()

    def conversation_ready(root, walked, names):
        caption = _window_caption(hwnd).strip().casefold()
        caption_changed = bool(old_caption and caption and caption != old_caption)
        joined = " ".join(names)
        has_composer = any(_is_composer_name(name) for name in names)
        has_paused_banner = any(phrase in joined for phrase in CHAT_CONTINUE_CONTEXTS)
        has_limit_modal = text_has_limit_phrase(joined)
        list_still_visible = _main_chat_list_heading_present(hwnd, walked, root)
        # Safety net: if the message box label is ever unknown again, a tab whose title
        # changed and whose chat-list heading is gone is a conversation page. Give the
        # normal signals a few seconds first so a banner is not missed.
        fallback_view = (caption_changed and not list_still_visible and
                         time.time() - started_at >= CHAT_READY_FALLBACK_SECONDS)
        conditions = {
            "tab_caption_changed_from_chat_list": caption_changed,
            "message_composer_detected": has_composer,
            "paused_usage_banner_detected": has_paused_banner,
            "usage_limit_text_detected": has_limit_modal,
            "main_chat_list_heading_still_visible": list_still_visible,
            "fallback_view_used": fallback_view,
        }
        diag["readiness_conditions"] = conditions
        ready = (has_paused_banner or has_limit_modal or fallback_view or
                 (has_composer and (caption_changed or not list_still_visible)))
        diag["ready_check"] = ready
        diag.pop("action", None)
        if ready:
            # Look for the Continue / Try again button in this very snapshot; if it is
            # already there the page is clearly loaded and we can click right away.
            action = _find_chat_action(hwnd, root, walked)
            diag["action"] = action
            if action is not None:
                diag["fast_ready"] = True
        return ready

    return _wait_for_stable_window_content(hwnd, conversation_ready, timeout,
                                           diagnostic_out=diag)


def _click_control(control):
    try:
        if hasattr(control, "IsEnabled") and not control.IsEnabled:
            return False
    except Exception:
        pass
    cached_name = getattr(control, "_tk_name", None)
    cached_rect = getattr(control, "_tk_rect", None)
    if wait_for_user_idle():
        # The user was active: only click if the very same button is still in the same place.
        try:
            if cached_name is not None and (control.Name or "").strip() != cached_name:
                return False
            if cached_rect:
                r = control.BoundingRectangle
                if (int(r.left), int(r.top), int(r.right), int(r.bottom)) != tuple(cached_rect):
                    return False
        except Exception:
            return False
        try:
            user32.SetForegroundWindow(control.GetTopLevelControl().NativeWindowHandle)
            time.sleep(0.2)
        except Exception:
            pass
    try:
        control.Click(waitTime=0.12)
        mark_own_input()
        return True
    except TypeError:
        try:
            control.Click()
            mark_own_input()
            return True
        except Exception:
            return False
    except Exception:
        return False


def _find_sidebar_view_all(hwnd):
    root, walked = _walk_window(hwnd)
    root_rect = _control_rect(root) if root is not None else None
    if not root_rect:
        return None
    left_limit = root_rect[0] + int((root_rect[2] - root_rect[0]) * 0.22)
    matches = []
    for control, _depth in walked:
        if _control_name(control).casefold() != "view all":
            continue
        rect = _control_rect(control)
        if rect and rect[0] < left_limit:
            matches.append((rect[1], control))
    return min(matches, key=lambda item: item[0])[1] if matches else None


def _caption_is_chat_list(hwnd):
    caption = _window_caption(hwnd).casefold()
    return bool("recents" in caption or "chats - claude" in caption
                or "chats and tasks - claude" in caption)


def _on_chat_list(hwnd):
    return _caption_is_chat_list(hwnd) or _main_chat_list_heading_present(hwnd)


def _main_pane_left(root_rect, walked):
    """Left edge of the main list area, found from the page heading (works in narrow windows
    where the sidebar is wider than 19%). None if the heading is not found."""
    left, top, right, bottom = root_rect
    min_left = left + int((right - left) * 0.12)  # the sidebar's own heading sits left of this
    best = None
    for control, _depth in walked:
        if _control_name(control).casefold() not in ("chats and tasks", "recents"):
            continue
        rect = _control_rect(control)
        if not rect or rect[0] < min_left or rect[1] > top + 250:
            continue
        if best is None or rect[0] > best:
            best = rect[0]
    return None if best is None else best - 24


def _chat_entry_controls(hwnd, root=None, walked=None):
    """Return actionable chat rows only; ignore filters, menus and page chrome.
    Pass root/walked from an existing snapshot to avoid walking the window again."""
    if root is None or walked is None:
        root, walked = _walk_window(hwnd)
    root_rect = _control_rect(root) if root is not None else None
    if not root_rect:
        return []

    left, top, right, bottom = root_rect
    if _has_blocking_usage_dialog([_control_name(control) for control, _depth in walked]):
        return []
    pane_left = _main_pane_left(root_rect, walked)
    if pane_left is None:
        if not _caption_is_chat_list(hwnd):
            return []  # an open chat or another page: its text must never be treated as chats
        pane_left = left + int((right - left) * 0.19)
    pane_right = left + int((right - left) * 0.66)
    list_top = top + 105
    list_bottom = bottom - 45

    ignore = {
        "chats and tasks", "select", "new", "search", "search your activity",
        "view all", "pinned", "projects", "artifacts", "code", "plugins",
        "new chat", "recents", "share", "settings", "filter by", "all",
        "shared", "archived", "close", "chat", "more options", "today",
        "yesterday", "this week", "last week", "this month", "older",
        "group and sort", "group by", "sort by", "upgrade", "dismiss upgrade banner",
        "new from a template",
    }
    priority = {
        "ListItemControl": 0,
        "HyperlinkControl": 1,
        "ButtonControl": 2,
        "CustomControl": 3,
        "TextControl": 4,
    }
    found = {}
    for control, _depth in walked:
        name = _control_name(control)
        normalized = " ".join(name.casefold().split())
        if not name or normalized in ignore or len(name) > 180:
            continue
        if normalized.startswith("more options for "):
            continue
        if any(marker in normalized for marker in (
            "explore plans", "upgrade to", "build, debug, and ship",
            "analyze data and build slides", "claude navigates, clicks buttons",
        )):
            continue

        rect = _control_rect(control)
        if not rect:
            continue
        if rect[0] < pane_left or rect[0] > pane_right:
            continue
        if rect[1] < list_top or rect[1] > list_bottom:
            continue
        if rect[2] <= rect[0] or rect[3] <= rect[1]:
            continue
        if (rect[3] - rect[1]) > 100:
            continue
        if re.fullmatch(r"\d+\s+(seconds?|minutes?|hours?|days?|weeks?|months?)\s+ago", normalized):
            continue

        ctype = _control_type(control)
        if ctype not in priority:
            continue
        old = found.get(name)
        rank = priority[ctype]
        if old is None or rank < old[0]:
            found[name] = (rank, rect[1], control)

    return [
        (name, item[2])
        for name, item in sorted(found.items(), key=lambda kv: (kv[1][1], kv[0].casefold()))
    ]


def _find_chat_row(hwnd, title):
    for name, control in _chat_entry_controls(hwnd):
        if name == title:
            return control
    return None


def _rolling_action_contexts(walked, phrases, kind):
    """Find context phrases even when Chrome splits a sentence across UIA nodes."""
    named = [(i, control, _control_name(control))
             for i, (control, _depth) in enumerate(walked) if _control_name(control)]
    contexts = []
    for pos in range(len(named)):
        for width in range(1, min(8, len(named) - pos) + 1):
            group = named[pos:pos + width]
            joined = " ".join(item[2] for item in group).casefold()
            if any(phrase in joined for phrase in phrases):
                rects = [_control_rect(item[1]) for item in group]
                rects = [rect for rect in rects if rect]
                group_rect = None
                if rects:
                    group_rect = (
                        min(rect[0] for rect in rects),
                        min(rect[1] for rect in rects),
                        max(rect[2] for rect in rects),
                        max(rect[3] for rect in rects),
                    )
                contexts.append((kind, group[0][0], group_rect))
                break
    return contexts


def _chat_action_context_present(hwnd):
    _root, walked = _walk_window(hwnd)
    return bool(
        _rolling_action_contexts(walked, CHAT_CONTINUE_CONTEXTS, "continue") or
        _rolling_action_contexts(walked, CHAT_ERROR_CONTEXTS, "error")
    )


def _find_chat_action(hwnd, root=None, walked=None):
    """Find an in-conversation Continue/Try again control near its message."""
    if root is None or walked is None:
        root, walked = _walk_window(hwnd)
    root_rect = _control_rect(root) if root is not None else None
    if not root_rect:
        return None

    pane_left = root_rect[0] + int((root_rect[2] - root_rect[0]) * 0.18)
    main_top = root_rect[1] + 105
    contexts = (
        _rolling_action_contexts(walked, CHAT_CONTINUE_CONTEXTS, "continue") +
        _rolling_action_contexts(walked, CHAT_ERROR_CONTEXTS, "error")
    )

    controls = []
    for index, (control, _depth) in enumerate(walked):
        name = _control_name(control)
        if not name:
            continue
        label = " ".join(name.casefold().split()).strip().rstrip("…. ")
        if label not in {"continue", "try again"}:
            continue
        rect = _control_rect(control)
        if not rect or rect[0] < pane_left or rect[1] < main_top:
            continue
        ctype = _control_type(control)
        if ctype not in {"ButtonControl", "HyperlinkControl", "TextControl", "CustomControl"}:
            continue
        controls.append((label, index, rect, control))

    choices = []
    for label, index, rect, control in controls:
        wanted_kind = "continue" if label == "continue" else "error"
        related = [ctx for ctx in contexts if ctx[0] == wanted_kind]
        if label == "continue" and not related:
            continue  # never click the unrelated page-header Continue control

        distances = []
        for _kind, ctx_index, ctx_rect in related:
            if rect and ctx_rect:
                _, button_y = _rect_center(rect)
                _, context_y = _rect_center(ctx_rect)
                distances.append(abs(button_y - context_y))
            else:
                distances.append(abs(index - ctx_index) * 3)

        if related:
            distance = min(distances)
            if distance > (180 if label == "try again" else 160):
                continue
        elif label == "try again":
            distance = 500
        else:
            continue

        choices.append((0 if label == "continue" else 1, distance, -rect[1], control,
                        "Continue" if label == "continue" else "Try again"))

    if not choices:
        return None
    choices.sort(key=lambda item: (item[0], item[1], item[2]))
    _kind, _distance, _y, control, label = choices[0]
    return label, control


def _wait_for_action_to_change(hwnd, label, timeout=CHAT_ACTION_VERIFY_SECONDS):
    deadline = time.time() + timeout
    while time.time() < deadline and user32.IsWindow(hwnd):
        current = _find_chat_action(hwnd)
        if current is None or current[0].casefold() != label.casefold():
            return True
        time.sleep(CHAT_ACTION_VERIFY_POLL_SECONDS)
    return False


def _return_to_chat_list(hwnd):
    view_all = _find_sidebar_view_all(hwnd)
    if view_all is not None and _click_control(view_all):
        return _wait_for_chat_list(hwnd, timeout=CHAT_LIST_LOAD_TIMEOUT_SECONDS)
    try:
        root = auto.ControlFromHandle(hwnd)
        wait_for_user_idle()
        root.SetActive()
        root.SendKeys("{Alt}{Left}", waitTime=0.15)
        mark_own_input()
        return _wait_for_chat_list(hwnd, timeout=CHAT_LIST_LOAD_TIMEOUT_SECONDS)
    except Exception:
        return False


def scan_chats_for_profile(profile, hwnd, info):
    """Open every chat once and click Continue / Try again where they appear.
    Returns {"completed": bool, "clicked": int, "dialog": bool}. Inspected titles are kept
    in memory for this visit only, so a second attempt only re-opens the unresolved chats."""
    result = {"completed": False, "clicked": 0, "dialog": False, "timeout": False}
    if not user32.IsWindow(hwnd):
        return result
    original_foreground = user32.GetForegroundWindow()
    inspected_this_run = 0
    seen_titles = set(info.get("chat_scan_seen", set()))
    failed_titles = set()
    idle_pages = 0
    tab_open_requested = False
    tab_confirmed = False
    using_existing_list = False
    original_tab_caption = ""
    blocking_dialog_seen = False
    try:
        _focus_window(hwnd)
        time.sleep(0.1)
        _root, initial_walked = _walk_window(hwnd)
        if _has_blocking_usage_dialog([_control_name(control) for control, _depth in initial_walked]):
            blocking_dialog_seen = True
            result["dialog"] = True
            log(f"[{profile}] chat scan deferred: Claude's usage dialog is open; no dialog controls will be treated as chats.")
            return result
        # Only probe the current tab when it already looks like the chat list;
        # a fresh /new page would just waste several seconds here.
        current_caption = _window_caption(hwnd).casefold()
        if "recents" in current_caption or "chats" in current_caption:
            using_existing_list = _wait_for_chat_list(hwnd, timeout=6, stable_reads_required=2)
        if not using_existing_list:
            # Work in this same (main) tab, no extra tab. Sidebar "View all" first (fast, no page
            # reload); backup: type the address ({Delete} removes Chrome's auto-completed ending).
            opened = False
            view_all = _find_sidebar_view_all(hwnd)
            if view_all is not None and _click_control(view_all):
                opened = True
            if not opened:
                try:
                    root = auto.ControlFromHandle(hwnd)
                    wait_for_user_idle()
                    root.SetActive()
                    root.SendKeys("{Ctrl}l", waitTime=0.3)
                    root.SendKeys(CHAT_LIST_URL + "{Delete}{Enter}", waitTime=0.1)
                    mark_own_input()
                    opened = True
                except Exception:
                    opened = False
            if not opened:
                log(f"[{profile}] chat scan paused: could not open the chat list in the main tab.")
                return result
        chat_list_diag = {}
        if not _wait_for_chat_list(hwnd, timeout=CHAT_LIST_LOAD_TIMEOUT_SECONDS,
                                   diagnostic_out=chat_list_diag):
            _root, current_walked = _walk_window(hwnd)
            blocking_dialog_seen = _has_blocking_usage_dialog(
                [_control_name(control) for control, _depth in current_walked]
            )
            if blocking_dialog_seen:
                result["dialog"] = True
                log(f"[{profile}] chat scan deferred: Claude's usage dialog is open.")
            else:
                log(f"[{profile}] chat scan paused: Claude's chat list did not become fully loaded/stable. Diagnostics: {_format_wait_diagnostics(chat_list_diag)}")
            return result

        while inspected_this_run < CHAT_SCAN_MAX_ITEMS and idle_pages < CHAT_LIST_IDLE_PAGES:
            if _profile_time_up():
                result["timeout"] = True
                return result
            if not _on_chat_list(hwnd):
                log(f"[{profile}] the page is not the chat list any more; going back to it.")
                if not _return_to_chat_list(hwnd):
                    log(f"[{profile}] chat scan stopped: could not get back to the chat list.")
                    return result
            entries = _chat_entry_controls(hwnd)
            pending = [
                (title, control) for title, control in entries
                if title not in seen_titles and title not in failed_titles
            ]
            if not pending:
                try:
                    root = auto.ControlFromHandle(hwnd)
                    wait_for_user_idle()
                    root.SetActive()
                    root.SendKeys("{PAGEDOWN}", waitTime=0.1)
                    mark_own_input()
                except Exception:
                    break
                time.sleep(CHAT_LIST_SCROLL_WAIT_SECONDS)
                newer = [
                    title for title, _control in _chat_entry_controls(hwnd)
                    if title not in seen_titles and title not in failed_titles
                ]
                if not newer:
                    idle_pages += 1
                else:
                    idle_pages = 0
                continue

            idle_pages = 0
            for title, _old_control in pending:
                if inspected_this_run >= CHAT_SCAN_MAX_ITEMS:
                    break
                if _profile_time_up():
                    result["timeout"] = True
                    return result
                wait_for_user_idle()
                previous_caption = _window_caption(hwnd)
                row = _find_chat_row(hwnd, title)
                if row is None or not _click_control(row):
                    time.sleep(0.7)  # one more try before giving up on this chat
                    wait_for_user_idle()
                    row = _find_chat_row(hwnd, title)
                if row is None or not _click_control(row):
                    failed_titles.add(title)
                    log(f"[{profile}] chat scan: could not open chat '{title}'; it remains pending for a later retry.")
                    continue

                chat_page_diag = {}
                page_ready = _wait_for_chat_page(hwnd, previous_caption=previous_caption,
                                                 diagnostic_out=chat_page_diag)
                if not page_ready:
                    _root, current_walked = _walk_window(hwnd)
                    if _has_blocking_usage_dialog(
                        [_control_name(control) for control, _depth in current_walked]
                    ):
                        blocking_dialog_seen = True
                        result["dialog"] = True
                        log(f"[{profile}] chat scan stopped: Claude's usage dialog appeared.")
                        return result
                    failed_titles.add(title)
                    log(f"[{profile}] chat scan: '{title}' did not pass the conversation readiness check within {CHAT_PAGE_LOAD_SECONDS}s; it remains pending and will not be counted as inspected. Diagnostics: {_format_wait_diagnostics(chat_page_diag)}")
                    if not user32.IsWindow(hwnd) or not _return_to_chat_list(hwnd):
                        log(f"[{profile}] chat scan stopped: could not return to the chat list after a load timeout.")
                        return result
                    continue

                # The readiness snapshot already searched for the button; reuse it.
                if "action" in chat_page_diag:
                    action = chat_page_diag["action"]
                else:
                    action = _find_chat_action(hwnd)
                clicked_titles = info.setdefault("chat_action_clicked", set())
                action_handled = True
                if action is not None:
                    label, button = action
                    if title in clicked_titles:
                        log(f"[{profile}] [{title}] {label} is still present after an earlier click; leaving it pending for retry.")
                        action_handled = False
                    elif _click_control(button):
                        time.sleep(CHAT_ACTION_SETTLE_SECONDS)
                        if _wait_for_action_to_change(hwnd, label):
                            result["clicked"] += 1
                            info["last_click_at"] = time.time()
                            clicked_titles.add(title)
                            log(f"[{profile}] [{title}] clicked in-chat {label}; disappearance confirmed.")
                        else:
                            log(f"[{profile}] [{title}] {label} click was not confirmed; leaving this chat pending.")
                            action_handled = False
                    else:
                        log(f"[{profile}] [{title}] found {label}, but the button could not be clicked; leaving this chat pending.")
                        action_handled = False
                elif _chat_action_context_present(hwnd):
                    # Words like "could not" also appear in normal chat text. A real paused chat
                    # always shows its button, so after repeated misses treat it as a false alarm.
                    missing = info.setdefault("chat_action_missing", {})
                    missing[title] = missing.get(title, 0) + 1
                    if missing[title] >= CHAT_ACTION_MISSING_LIMIT:
                        log(f"[{profile}] [{title}] message text matched {missing[title]} times but there is never a button; treating as a normal chat.")
                    else:
                        log(f"[{profile}] [{title}] pause/error message found but its action button was not identified; leaving this chat pending ({missing[title]}/{CHAT_ACTION_MISSING_LIMIT}).")
                        action_handled = False
                elif title in clicked_titles:
                    clicked_titles.discard(title)

                if not action_handled:
                    failed_titles.add(title)
                    info["chat_scan_seen"] = seen_titles
                    if not _return_to_chat_list(hwnd):
                        log(f"[{profile}] chat scan stopped: could not return to the chat list after an unconfirmed action.")
                        return result
                    continue

                seen_titles.add(title)
                info["chat_scan_seen"] = seen_titles
                inspected_this_run += 1

                if not _return_to_chat_list(hwnd):
                    # After a Continue click the usage dialog often covers the list.
                    _root, current_walked = _walk_window(hwnd)
                    if _has_blocking_usage_dialog(
                        [_control_name(control) for control, _depth in current_walked]
                    ):
                        blocking_dialog_seen = True
                        result["dialog"] = True
                        log(f"[{profile}] chat scan stopped: Claude's usage dialog appeared.")
                    else:
                        log(f"[{profile}] chat scan stopped: could not return to the fully loaded chat list; remaining chats stay pending.")
                    return result

        info["chat_scan_seen"] = seen_titles
        reached_cap = inspected_this_run >= CHAT_SCAN_MAX_ITEMS
        completed = not failed_titles and not reached_cap and idle_pages >= CHAT_LIST_IDLE_PAGES
        result["completed"] = completed
        if completed:
            log(f"[{profile}] chat scan complete: inspected {len(seen_titles)} chat(s), clicked {result['clicked']} Continue/Try again action(s) this visit.")
        elif reached_cap:
            log(f"[{profile}] chat scan paused at the {CHAT_SCAN_MAX_ITEMS}-chat safety cap; completed chats are saved.")
        elif failed_titles:
            log(f"[{profile}] chat scan partially complete: {len(seen_titles)} chat(s) saved, {len(failed_titles)} chat(s) unresolved.")
        else:
            log(f"[{profile}] chat scan ended without confirming the end of the chat list; saved {len(seen_titles)} chats.")
        return result
    except Exception as exc:
        log(f"[{profile}] chat scan error: {exc}")
        return result
    finally:
        # No extra tab is opened any more, so nothing is closed here (Ctrl+W would close the main tab).
        if original_foreground and user32.IsWindow(original_foreground):
            user32.SetForegroundWindow(original_foreground)


# ================= one profile at a time, one pass =================

def _recheck_limit(hwnd, wait_seconds):
    """Look for a usage-limit message; the dialog can appear a few seconds after a click."""
    deadline = time.time() + wait_seconds
    while user32.IsWindow(hwnd):
        hit, _names, _readable = scan_window(hwnd)
        if hit:
            return hit
        if time.time() >= deadline:
            return None
        time.sleep(1.0)
    return None


def _visit_profile(profile, idx, info):
    """Returns (status_key, detail)."""
    hwnd = info.get("hwnd")
    if hwnd is not None and not user32.IsWindow(hwnd):
        hwnd = None
        info["hwnd"] = None

    # 1) Open the profile (one window, fully, before anything else happens).
    if hwnd is not None:
        log(f"[{profile}] using its already-open window.")
    else:
        for attempt in range(1, LAUNCH_ATTEMPTS + 1):
            wait_until_calm(RESOURCE_WAIT_MAX_SECONDS)
            wait_for_user_idle()
            log(f"[{profile}] opening... (attempt {attempt}/{LAUNCH_ATTEMPTS})")
            foreground = user32.GetForegroundWindow()
            hwnd = launch_profile(profile, idx, restore_focus_to=foreground or None)
            if hwnd is not None:
                break
            time.sleep(3)
        if hwnd is None:
            return "launch_failed", "Chrome window did not appear"
        info["hwnd"] = hwnd
        info["script_launched"] = True

    # 2) Wait until the Claude page has completely loaded.
    log(f"[{profile}] waiting for the page to load completely...")
    outcome, payload = wait_until_page_loaded(hwnd)
    if outcome == "window_gone":
        info["hwnd"] = None
        log(f"[{profile}] the window was closed before the page loaded.")
        return "window_closed", "window closed while loading"
    if outcome == "unreadable":
        log(f"[{profile}] page never became readable within {PAGE_LOAD_MAX_SECONDS}s {scan_diag()}; closing this profile's window and moving on.")
        close_profile_window(profile, info)
        return "unreadable", "page did not load"
    if outcome == "limit":
        record_limit(profile, info)
        return "limited", "limit message on screen"

    # 3) Page is loaded and has no limit message.
    if looks_signed_out(payload):
        log(f"[{profile}] this profile is not signed in to Claude; nothing to do. Leaving the window open.")
        return "not_signed_in", "sign in manually"
    log(f"[{profile}] page loaded, no usage limit.")

    # 4) Open every chat once (Continue / Try again).
    clicked = 0
    dialog_seen = False
    timed_out = False
    for attempt in range(1, CHAT_SCAN_ATTEMPTS + 1):
        if not user32.IsWindow(hwnd):
            break
        if _profile_time_up():
            timed_out = True
            break
        wait_until_calm(CHAT_SCAN_RESOURCE_WAIT_SECONDS)
        scan = scan_chats_for_profile(profile, hwnd, info)
        clicked += scan["clicked"]
        dialog_seen = dialog_seen or scan["dialog"]
        if scan.get("timeout"):
            timed_out = True
            break
        if scan["completed"]:
            info["chat_scan_completed"] = True
            break
        if scan["dialog"]:
            break
        if attempt < CHAT_SCAN_ATTEMPTS:
            log(f"[{profile}] chat scan incomplete; trying once more.")
            time.sleep(3)

    if not user32.IsWindow(hwnd):
        info["hwnd"] = None
        return "window_closed", f"window closed during chat scan (clicked {clicked})"

    if timed_out or (_profile_time_up() and not info.get("chat_scan_completed")):
        log(f"[{profile}] time cap of {PROFILE_MAX_SECONDS // 60} min reached before the work finished; closing this profile's window.")
        close_profile_window(profile, info)
        return "timeout", f"time cap reached; clicked {clicked}"

    # 5) Final limit check (clicking Continue can bring the limit dialog back).
    # A limit dialog can appear up to LIMIT_RECHECK_AFTER_CLICK_SECONDS after a click. Count that time
    # from the LAST click, not from the end of the scan (later chats already used up that time).
    if dialog_seen:
        recheck_wait = LIMIT_RECHECK_AFTER_CLICK_SECONDS
    elif clicked and info.get("last_click_at"):
        recheck_wait = max(2, LIMIT_RECHECK_AFTER_CLICK_SECONDS - (time.time() - info["last_click_at"]))
    else:
        recheck_wait = 2
    hit = _recheck_limit(hwnd, recheck_wait)
    if hit:
        record_limit(profile, info)
        return "limited", f"limit message appeared; clicked {clicked}"

    seen = len(info.get("chat_scan_seen", ()))
    if info.get("chat_scan_completed"):
        detail = f"all chats inspected ({seen}); clicked {clicked}"
    else:
        detail = f"{seen} chats inspected, some could not be opened; clicked {clicked}"
    if CLOSE_WINDOW_WHEN_DONE and info.get("script_launched"):
        close_profile_window(profile, info)
    return "clear", detail


def visit_profile(profile, idx, info):
    global _profile_deadline
    _profile_deadline = time.time() + PROFILE_MAX_SECONDS
    try:
        return _visit_profile(profile, idx, info)
    except KeyboardInterrupt:
        raise
    except Exception as exc:
        log(f"[{profile}] unexpected error: {exc}")
        return "error", str(exc)


# ---------- keep the PC awake + report (this run only) ----------

ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001
kernel32.SetThreadExecutionState.argtypes = [ctypes.c_uint]
kernel32.SetThreadExecutionState.restype = ctypes.c_uint


def _keep_pc_awake(on):
    """While the tool runs the PC must not go to sleep."""
    try:
        kernel32.SetThreadExecutionState(ES_CONTINUOUS | (ES_SYSTEM_REQUIRED if on else 0))
    except Exception:
        pass


def _status_bn(info):
    status = info.get("last_status") or ""
    key = status.split(":", 1)[0]
    if not status:
        return "এখনো যাওয়া হয়নি"
    if key == "limited":
        return "লিমিট শেষ, জানালা বন্ধ করা হয়েছে"
    if key == "clear":
        return "সব চ্যাট দেখা শেষ" if info.get("chat_scan_completed") else "কিছু চ্যাট খোলা যায়নি"
    return {
        "window_closed": "জানালা বন্ধ হয়ে গিয়েছিল",
        "unreadable": "পেজ লোড হয়নি",
        "timeout": "সময়সীমা শেষ, জানালা বন্ধ করা হয়েছে",
        "launch_failed": "জানালা খোলেনি",
        "not_signed_in": "লগইন করা নেই",
        "error": "ত্রুটি হয়েছে",
    }.get(key, status)


def _status_key(info):
    return (info.get("last_status") or "").split(":", 1)[0]


def write_report(plist):
    """Plain-text summary of THIS run next to the script (overwritten every run)."""
    try:
        now = datetime.now()
        done = sum(1 for p in plist if state[p].get("chat_scan_completed"))
        limited = sum(1 for p in plist if _status_key(state[p]) == "limited")
        problems = sum(1 for p in plist if _status_key(state[p]) in FAILED_STATUS_KEYS)
        clicked = sum(len(state[p].get("chat_action_clicked", ())) for p in plist)
        lines = [
            f"রিপোর্ট - {now:%Y-%m-%d %H:%M}",
            "=" * 60,
            f"মোট প্রোফাইল: {len(plist)} | সব চ্যাট দেখা শেষ: {done} | লিমিটে ছিল: {limited} | সমস্যা: {problems}",
            f"Continue / Try again ক্লিক করা চ্যাট (এই রানে): {clicked}",
            "",
            "প্রোফাইল | অবস্থা | চ্যাট দেখা / ক্লিক",
            "-" * 60,
        ]
        for p in plist:
            info = state[p]
            lines.append(
                f"{p} | {_status_bn(info)} | "
                f"{len(info.get('chat_scan_seen', ()))} / {len(info.get('chat_action_clicked', ()))}"
            )
        with open(SCRIPT_DIR / REPORT_FILE_NAME, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    except Exception as exc:
        log(f"Could not write the report ({exc}).")


def print_summary(plist):
    log("----- Summary of this run -----")
    counts = {}
    for profile in plist:
        info = state[profile]
        status = info.get("last_status") or "not visited yet"
        key = status.split(":", 1)[0]
        counts[key] = counts.get(key, 0) + 1
        log(f"  {profile}: {status}")
    log("  Totals: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))


def main():
    global PLIST, state
    if not acquire_single_instance():
        print("Another copy of this tool is already running. Close it first (two copies close each other's windows).")
        input("\nPress Enter to exit...")
        return

    PLIST = profiles()[:MAX_PROFILES]
    if not PLIST:
        print("No Chrome profiles were found.")
        input("\nPress Enter to exit...")
        return

    log("=" * 64)
    log(f"CHROME PROFILE OPENER (simple, no memory) v{TOOLKIT_VERSION} -- one profile at a time, one pass")
    log(f"Detected profiles={len(PLIST)} safe_cpu<={SAFE_CPU_PERCENT:.0f}% safe_ram<={SAFE_RAM_PERCENT:.0f}% "
        f"page_load_patience={PAGE_LOAD_MAX_SECONDS}s")

    state = {p: new_info() for p in PLIST}  # fresh every run; nothing is loaded from or saved to disk
    reconnect_existing_windows(state, PLIST)
    display_to_folders = load_profile_display_names(PLIST)
    if display_to_folders:
        identify_manual_windows(state, PLIST, display_to_folders)

    print("\nOne profile is opened at a time and fully loaded before any work starts. Press Ctrl+C to stop.\n")
    try:
        _keep_pc_awake(True)
        for number, profile in enumerate(PLIST, 1):
            idx = PLIST.index(profile)
            log(f"----- [{number}/{len(PLIST)}] {profile} -----")
            info = state[profile]
            key, detail = visit_profile(profile, idx, info)
            info["last_status"] = f"{key}: {detail}" if detail else key
            log(f"[{profile}] done -> {info['last_status']}")
        log("All profiles visited; finished.")
        print_summary(PLIST)
        write_report(PLIST)
    except KeyboardInterrupt:
        log("Stopped by user (Ctrl+C).")
        print_summary(PLIST)
        write_report(PLIST)
    finally:
        _keep_pc_awake(False)

    input("\nPress Enter to close...")


if __name__ == "__main__":
    main()
