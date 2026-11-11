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

MAX_PROFILES = 35
MAX_CONCURRENT_PROFILES = 7    # never more than this many open at the same time
MAX_WAIT_FOR_WINDOW = 20  # only wait for the OS window; page verification runs in the watcher
CHECK_INTERVAL_SECONDS = 0.5
TARGET_URL = "https://claude.ai/new"
# "out of free" catches "You are out of free messages until <time>" too, and
# "free messages return" catches "Your free messages return at <time>" --
# the time changes every time, so we only match the fixed part of the text.
# Matching is case-sensitive (see text_has_limit_phrase).
TARGET_PHRASES = [
    "Upgrade to keep chatting",
    "out of free",
    "free messages return",   # "Your free messages return at <time>"
    "your usage limit resets", # "Your usage limit resets at <time>"
]

# A scan only counts as "page was read" if enough text was found INSIDE the web
# page (the UI Automation Document node). If Chrome's page is frozen/empty or
# UI Automation fails, we must not treat that as "no limit message".
READABILITY_CHECK = True       # set False to treat every successful scan as readable
MIN_PAGE_NODES = 3             # named nodes needed under the page Document to call it readable
UNREADABLE_FLAG_SECONDS = 10   # a window that was fine must stay unreadable this long before it is flagged
UNREADABLE_WARN_MINUTES = 5    # re-log a warning this often while a window stays unreadable
MAX_TREE_DEPTH = 30
WM_CLOSE = 0x0010
HWND_BOTTOM = 1
SWP_NOMOVE = 0x0002
SWP_NOSIZE = 0x0001
GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
LWA_ALPHA = 0x2
DEFAULT_REOPEN_WAIT_HOURS = 5  # fallback if a reset time can't be read from the message
RESET_BUFFER_MINUTES = 10      # actual reset sometimes lags a few minutes behind the stated time
RETRY_BACKOFF_MINUTES = 5      # if still limited shortly after the stated reset time, retry again this soon
STALE_THRESHOLD_MINUTES = 30   # how far in the past counts as "just lagging" vs "must mean tomorrow"
BACKOFF_BASE_MINUTES = 5       # a profile that fails to open waits this long before the next attempt...
BACKOFF_CAP_MINUTES = 60       # ...doubling each consecutive failure, up to this ceiling
IDENTIFY_MANUAL_EVERY_N_CYCLES = 20  # how often to look for manually-opened windows we haven't tagged

# Low-overhead scanning (see "fast page reading" below).
USE_FAST_SCAN = True              # read each page with ONE cached UI Automation query; falls back to the slow walk on any failure
FAST_SCAN_MAX_FAILURES = 5        # this many consecutive fast-scan errors -> use the slow walk for the rest of the session
FULL_READ_EVERY_SECONDS = 10.0   # a page already confirmed readable gets a cheap phrase probe; its full text is re-read this often
MAX_SCAN_DUTY_CYCLE = 0.25        # scanning may use at most about this share of wall time; the loop sleeps longer if scans get slow
MAX_ADAPTIVE_SLEEP_SECONDS = 2.0  # ...but it never sleeps longer than this between checks
RUNNING_PROFILES_TTL_SECONDS = 5.0  # the Chrome process list is only re-read this often (and always right before a launch)
TARGET_PID_CACHE_SECONDS = 30.0   # remember "this process is the target Chrome" instead of asking Windows every time

# Covered windows: Chrome normally freezes the page of a window that is completely hidden
# behind other windows, and a frozen page cannot be read (log: page_nodes=0). These two
# Chrome switches tell it NOT to treat covered windows as hidden, so they stay readable
# without bringing anything to the front or stealing focus. They only take effect when
# Chrome STARTS, so Chrome must be launched by this tool (or closed once and relaunched).
KEEP_COVERED_WINDOWS_AWAKE = True  # set False to launch Chrome without these switches
AWAKE_CHROME_FLAGS = [
    "--disable-features=CalculateNativeWinOcclusion",
    "--disable-backgrounding-occluded-windows",
]

# Smart launch protection: defer new launches when the PC is under load.
SAFE_CPU_PERCENT = 65.0
SAFE_RAM_PERCENT = 80.0
RESOURCE_SAMPLE_SECONDS = 0.25
RESOURCE_LOG_INTERVAL_SECONDS = 30
END_PASS_RETRY_DELAY_SECONDS = 5  # one final retry after the normal profile scan
_resource_wait_active = False
_last_resource_wait_log = 0.0

# Matches "resets at 4:30 PM", "until 2:50 AM" or "return at 12:40 AM" and captures
# the time. \s also covers non-breaking / narrow no-break spaces before AM/PM.
RESET_TIME_RE = re.compile(
    r'(?:resets?\s+at|returns?\s+at|until)\s+(\d{1,2}:\d{2}\s*[AP]\.?\s*M\.?)',
    re.IGNORECASE,
)

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
    print("Google Chrome executable was not found.")
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
user32.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
user32.GetWindowThreadProcessId.restype = ctypes.c_ulong

PROFILE_TAG_PROP = "ClaudeAutomationProfileIndex"


# ---------- logging + persistence ----------

LOG_RETENTION_DAYS = 3
LOG_CLEANUP_INTERVAL_SECONDS = 3600  # re-check hourly while the tool is running
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
                # Log entries begin with [YYYY-MM-DD HH:MM:SS].
                try:
                    timestamp = datetime.strptime(line[1:20], "%Y-%m-%d %H:%M:%S")
                    if line.startswith("[") and timestamp < cutoff:
                        changed = True
                        continue
                except (ValueError, IndexError):
                    # Preserve unrecognized lines rather than risk deleting data.
                    pass
                kept.append(line)
        if changed:
            with open(LOG_FILE, "w", encoding="utf-8", newline="") as f:
                f.writelines(kept)
    except Exception:
        pass  # cleanup must never crash the main script

# Clean existing history immediately on startup, then re-check hourly.
prune_old_logs(force=True)

def log(message):
    """Prints AND appends a timestamped line to activity_log.txt."""
    prune_old_logs()
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {message}"
    print(line)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass  # logging must never crash the main script

def resources_safe_for_launch():
    """Sample system load once before a launch; never block the monitoring loop.

    If CPU/RAM is high, the caller skips new launches for this cycle while the
    main loop continues watching already-open profiles.
    """
    global _resource_wait_active, _last_resource_wait_log
    cpu = psutil.cpu_percent(interval=RESOURCE_SAMPLE_SECONDS)
    ram = psutil.virtual_memory().percent
    now_ts = time.time()
    safe = cpu <= SAFE_CPU_PERCENT and ram <= SAFE_RAM_PERCENT
    if safe:
        if _resource_wait_active:
            log(f"System load is back within limits (CPU={cpu:.0f}%, RAM={ram:.0f}%); resuming profile launches.")
        _resource_wait_active = False
        return True
    if (not _resource_wait_active or
            now_ts - _last_resource_wait_log >= RESOURCE_LOG_INTERVAL_SECONDS):
        log(f"Pausing new profile launches because system load is high (CPU={cpu:.0f}% / limit {SAFE_CPU_PERCENT:.0f}%, RAM={ram:.0f}% / limit {SAFE_RAM_PERCENT:.0f}%). Existing profiles will continue to be monitored.")
        _last_resource_wait_log = now_ts
    _resource_wait_active = True
    return False

def record_launch_failure(profile, info):
    """Apply exponential backoff after a failed launch attempt."""
    info["fail_count"] += 1
    exponent = min(max(info["fail_count"] - 1, 0), 20)
    minutes = min(BACKOFF_BASE_MINUTES * (2 ** exponent), BACKOFF_CAP_MINUTES)
    info["backoff_until"] = datetime.now() + timedelta(minutes=minutes)
    log(f"[{profile}] failed to open (attempt {info['fail_count']}) -- temporarily skipped; retry after {minutes} min, at {info['backoff_until']:%H:%M}.")
    save_state(state)

def record_launch_success(profile, info, new_hwnd, hit, state, readable=True):
    """Update tracking for a successfully created browser window.

    readable=False means the page could not be read, so "no limit message" is
    not confirmed: the window is kept open and flagged as unverified, and the
    main loop keeps re-checking it every cycle."""
    info["fail_count"] = 0
    info["backoff_until"] = None
    info["unverified_since"] = None
    info["unreadable_first"] = None
    if hit:
        new_reset_at, reason = compute_reopen_time(hit)
        log(f"[{profile}] still limited -> closing again. Will reopen at {new_reset_at:%Y-%m-%d %H:%M} ({reason}).")
        if close_window(new_hwnd):
            info["hwnd"] = None
            info["reopen_at"] = new_reset_at
        else:
            # Keep tracking a window that did not close so the watcher can try again.
            info["hwnd"] = new_hwnd
            info["reopen_at"] = None
            log(f"[{profile}] window could not be closed yet; keeping it under monitoring.")
    elif not user32.IsWindow(new_hwnd):
        # Closed (by the user or by Chrome) while it was still loading: there is
        # nothing to verify, so don't track a dead handle or claim anything about it.
        info["hwnd"] = None
        info["reopen_at"] = None
        log(f"[{profile}] window disappeared while loading -- nothing to verify; it will be reopened.")
    elif readable:
        info["hwnd"] = new_hwnd
        info["reopen_at"] = None
        log(f"[{profile}] open and clear.")
    else:
        info["hwnd"] = new_hwnd
        info["reopen_at"] = None
        info["unverified_since"] = datetime.now()
        log(f"[{profile}] opened, but its page could not be read -- NOT confirmed clear. "
            f"Keeping it open and re-checking every cycle. {scan_diag()}")
    save_state(state)

def load_state(plist):
    """Restores each profile's reopen_at/backoff schedule from disk, if
    present. hwnd is never restored here -- reconnect_existing_windows()
    handles finding still-open windows separately."""
    state = {p: {"hwnd": None, "reopen_at": None, "fail_count": 0, "backoff_until": None,
                 "unverified_since": None} for p in plist}
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
        # Atomic save: an interrupted write cannot leave a truncated JSON state file.
        temp_file = STATE_FILE.with_suffix(STATE_FILE.suffix + ".tmp")
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(serializable, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_file, STATE_FILE)
    except Exception as exc:
        log(f"Could not save state ({exc}).")


# ---------- window helpers ----------

def _normalized_path(value):
    try:
        return os.path.normcase(os.path.abspath(os.path.expandvars(str(value))))
    except (TypeError, ValueError, OSError):
        return ""

def is_target_executable(executable):
    """True only for the exact Chrome executable this package targets.

    Stable Chrome and Chrome both use chrome.exe, so checking the name
    alone could accidentally control the other browser.
    """
    return bool(executable) and _normalized_path(executable) == _normalized_path(CHROME)

_target_pid_cache = {}  # pid -> (is_target, checked_at)

def is_target_window(hwnd):
    """Check the process that owns a window before touching it.

    All windows of one Chrome instance share a browser process, so the answer is
    cached per PID for a short time instead of asking Windows for the process's
    executable path (an expensive call) for every window on every check."""
    try:
        pid = ctypes.c_ulong(0)
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value:
            return False
        now_ts = time.time()
        cached = _target_pid_cache.get(pid.value)
        if cached is not None and now_ts - cached[1] < TARGET_PID_CACHE_SECONDS:
            return cached[0]
        result = is_target_executable(psutil.Process(pid.value).exe())
        if len(_target_pid_cache) > 256:
            _target_pid_cache.clear()
        _target_pid_cache[pid.value] = (result, now_ts)
        return result
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
    """Return only processes for the selected Chrome channel."""
    out = []
    for p in psutil.process_iter(["name", "cmdline", "exe"]):
        try:
            if ((p.info.get("name") or "").lower() == "chrome.exe"
                    and is_target_executable(p.info.get("exe"))):
                out.append(p.info)
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass
    return out

def running_profile_names():
    """Read Chrome processes once and return the profile folders already running.

    Avoids repeating a full Windows process enumeration for every profile.
    """
    running = set()
    for info in chrome_processes():
        for arg in (info.get("cmdline") or []):
            if arg.lower().startswith("--profile-directory="):
                running.add(arg.split("=", 1)[1])
    return running

def awake_flags_status():
    """Is the Chrome that is running right now protected against freezing covered windows?

    Returns "off" (the setting is disabled), "no-chrome" (Chrome is not running; the
    flags will be applied on the next launch), "active" (the running Chrome was started
    with the switches) or "inactive" (Chrome was started WITHOUT them, so covered
    windows can still freeze until Chrome is closed once and relaunched by this tool).
    Only the browser (main) process is checked: helper processes have --type=..."""
    if not KEEP_COVERED_WINDOWS_AWAKE:
        return "off"
    saw_browser = False
    for info in chrome_processes():
        args = info.get("cmdline") or []
        if any(a.startswith("--type=") for a in args):
            continue
        saw_browser = True
        if all(any(a == flag for a in args) for flag in AWAKE_CHROME_FLAGS):
            return "active"
    return "inactive" if saw_browser else "no-chrome"

_running_cache = {"at": 0.0, "profiles": set()}

def get_running_profiles(force=False):
    """Profile folders that already have a Chrome process.

    Reading the process list (dozens of Chrome processes, command lines included)
    is expensive, so the result is cached and only refreshed when it is older than
    RUNNING_PROFILES_TTL_SECONDS or when forced -- the loop forces it right before
    a launch, so a launch never relies on a stale answer."""
    now_ts = time.time()
    if force or now_ts - _running_cache["at"] >= RUNNING_PROFILES_TTL_SECONDS:
        _running_cache["profiles"] = running_profile_names()
        _running_cache["at"] = now_ts
    return _running_cache["profiles"]

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

def text_has_limit_phrase(text):
    """Match known Claude limit messages without depending on letter case."""
    normalized = text.casefold()
    return any(phrase.casefold() in normalized for phrase in TARGET_PHRASES)

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

_last_scan_info = (0, False, 0)

def scan_diag():
    """One-line description of the last scan, written next to every 'unreadable'
    log line so the log itself shows WHY (UI Automation failed / no page Document
    node / page empty) and MIN_PAGE_NODES / READABILITY_CHECK can be tuned."""
    total, doc_seen, page_nodes = _last_scan_info
    if total == 0 and not doc_seen:
        return "(diag: UI Automation returned nothing)"
    return f"(diag: names={total}, page_document_found={doc_seen}, page_nodes={page_nodes}, need>={MIN_PAGE_NODES})"

_fast_scan_failures = 0
_scan_memo = {}        # hwnd -> (time of last full page read, that read was readable)
_probe_condition = None
_scan_seconds = 0.0    # time spent scanning since the main loop last reset it

def _probe_for_phrase(uia, root):
    """Cheapest possible check: ONE search that asks Chrome itself for any element
    whose name contains a limit phrase (case-insensitive). Nothing but a yes/no
    comes back, so the cost does not grow with the size of the page."""
    global _probe_condition
    if _probe_condition is None:
        # 3 = IgnoreCase | MatchSubstring
        conds = [uia.CreatePropertyConditionEx(auto.PropertyId.NameProperty, phrase, 3)
                 for phrase in TARGET_PHRASES]
        cond = conds[0]
        for extra in conds[1:]:
            cond = uia.CreateOrCondition(cond, extra)
        _probe_condition = cond
    return root.FindFirst(auto.TreeScope.Descendants, _probe_condition) is not None

def _scan_window_fast(hwnd):
    """Low-cost page reading in two tiers (instead of walking the whole window tree
    one slow cross-process call per node, most of them Chrome's own toolbar/tabs):

    1. PROBE (every check): a page that was fully read recently and was readable only
       needs one filtered search for the limit phrases. No match -> still clear.
    2. FULL READ (first time, every FULL_READ_EVERY_SECONDS, or when the probe matched):
       find the page's Document node(s) and fetch all descendant names in ONE cached
       query. This gives the reset-time text next to the phrase and re-proves that
       the page is readable (not frozen/empty).

    Returns (hit, names, readable) like scan_window(), or None when the fast path
    could not give a trustworthy answer (the caller then uses the slow walk)."""
    global _last_scan_info
    uia = auto.AutomationClient.instance().IUIAutomation
    root = uia.ElementFromHandle(hwnd)
    if root is None:
        return None
    now_ts = time.time()
    memo = _scan_memo.get(hwnd)
    if memo is not None and memo[1] and now_ts - memo[0] < FULL_READ_EVERY_SECONDS:
        if not _probe_for_phrase(uia, root):
            return None, (), True  # recently proven readable, and no limit phrase right now
        # a phrase is on screen: fall through to the full read to capture the reset time
    doc_cond = uia.CreatePropertyCondition(auto.PropertyId.ControlTypeProperty,
                                           auto.ControlType.DocumentControl)
    docs = root.FindAll(auto.TreeScope.Descendants, doc_cond)
    if docs is None or docs.Length == 0:
        _scan_memo.pop(hwnd, None)
        return None  # no page Document found: let the slow walk decide
    cache = uia.CreateCacheRequest()
    cache.AddProperty(auto.PropertyId.NameProperty)
    true_cond = uia.CreateTrueCondition()
    names = []
    for i in range(docs.Length):
        found = docs.GetElement(i).FindAllBuildCache(auto.TreeScope.Descendants, true_cond, cache)
        if found is None:
            continue
        for j in range(found.Length):
            name = found.GetElement(j).CachedName
            if name:
                names.append(name)
    _last_scan_info = (len(names), True, len(names))
    readable = (len(names) >= MIN_PAGE_NODES) if READABILITY_CHECK else True
    if len(_scan_memo) > 128:
        _scan_memo.clear()  # closed windows leave stale handles behind; a clear just costs one full read each
    _scan_memo[hwnd] = (now_ts, readable)
    for idx, name in enumerate(names):
        if text_has_limit_phrase(name):
            end = idx + 1 + EXTRA_NODES_AFTER_HIT
            return " ".join(names[idx:end]), None, True
    return None, tuple(names), readable

def scan_window(hwnd):
    """Reads a window for the limit message: fast cached page query first, the
    original full-tree walk as a safe fallback. The fast result is used whenever a
    Document node was found (a limit hit, a readable page, or a genuinely empty
    page); any error or missing Document goes to the slow walk, and after
    FAST_SCAN_MAX_FAILURES consecutive errors the fast path is switched off for
    the rest of the session so a problem on one PC cannot break detection."""
    global _fast_scan_failures, _scan_seconds
    started = time.perf_counter()
    try:
        if USE_FAST_SCAN and _fast_scan_failures < FAST_SCAN_MAX_FAILURES:
            try:
                result = _scan_window_fast(hwnd)
                _fast_scan_failures = 0
                if result is not None:
                    return result
            except Exception:
                _fast_scan_failures += 1
                if _fast_scan_failures == FAST_SCAN_MAX_FAILURES:
                    log("Fast page reading failed repeatedly; using the standard slower scan for the rest of this session.")
        return _scan_window_slow(hwnd)
    finally:
        _scan_seconds += time.perf_counter() - started

def _scan_window_slow(hwnd):
    """Walks the window's UI Automation tree, checking for a limit phrase
    as it goes. Once a phrase is found, keeps reading EXTRA_NODES_AFTER_HIT
    more names (instead of stopping immediately) and returns them all
    joined together, because the actual reset-time text ("It resets at
    1:00 AM...") is a separate control from the phrase that matched (e.g.
    the dialog heading "Upgrade to keep chatting") -- returning just the
    matched node's own text means compute_reopen_time() never sees the
    time and silently falls back to the default wait every time. Returns
    (hit_text_or_None, names_tuple). names_tuple is only built when no
    phrase was found (used for page-settle stability comparisons).

    A third value, `readable`, says whether the web PAGE itself could be read
    (enough named nodes under the UI Automation Document node). "No limit
    phrase" only means "clear" when readable is True: if the scan failed or the
    page is frozen/empty, the result is (None, None, False) / (None, names, False)
    and callers must treat the window as UNVERIFIED, not as clear.
    Returns (hit_text_or_None, names_tuple_or_None, readable)."""
    global _last_scan_info
    names = []
    hit_index = None
    page_nodes = 0
    doc_seen = False
    doc_depth = None  # depth of the page's Document node while we are inside it
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
                doc_depth = None  # walked out of the page area
            name = c.Name
            if not name:
                continue
            names.append(name)
            if doc_depth is not None and depth > doc_depth:
                page_nodes += 1
            if hit_index is None:
                if text_has_limit_phrase(name):
                    hit_index = len(names) - 1
            elif len(names) - hit_index > EXTRA_NODES_AFTER_HIT:
                break
    except Exception:
        return None, None, False
    _last_scan_info = (len(names), doc_seen, page_nodes)
    if hit_index is not None:
        return " ".join(names[hit_index:]), None, True
    readable = (page_nodes >= MIN_PAGE_NODES) if READABILITY_CHECK else True
    return None, tuple(names), readable

def parse_reset_time_today(text):
    """Extracts e.g. '4:30 PM' or '2:50 AM' from the limit message and
    returns (TODAY's datetime for that time, the raw matched string) --
    the datetime may be in the past; the caller decides what that means.
    Returns (None, None) if no time was found in the text."""
    match = RESET_TIME_RE.search(text)
    if not match:
        return None, None
    raw_matched = match.group(1).strip()
    raw = re.sub(r'[\s.]+', '', raw_matched).upper()  # "12:40 AM" / "12:40 am" / "1:05 p.m." -> "12:40AM"
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
    delay. Returns (hit_text, readable).
    - (text, True): a limit phrase was found.
    - (None, True): the page was READ, its content stopped changing, and no
      limit phrase is on it -> genuinely clear.
    - (None, False): the page could never be read (UI Automation failed, page
      frozen/empty, window vanished) within max_wait_seconds -> UNVERIFIED.
      This must not be treated as "clear"."""
    last_signature = None
    stable_streak = 0
    last_readable = False
    started = time.time()
    while time.time() - started < max_wait_seconds:
        if not user32.IsWindow(hwnd):
            return None, False
        hit, names, readable = scan_window(hwnd)
        if hit:
            return hit, True
        last_readable = readable
        if readable and names is not None and names == last_signature:
            stable_streak += 1
        else:
            stable_streak = 0
        last_signature = names
        if stable_streak >= stable_reads_required:
            return None, True
        time.sleep(poll_seconds)
    return None, last_readable

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
    """Opens one profile at TARGET_URL and returns (hwnd, matched_limit_text, readable).
    matched_limit_text is None if no limit message was found. readable is
    False when the page could not be read at all -- then "no limit message"
    is NOT confirmed (see wait_for_page_or_limit).

    If restore_focus_to is given (the window the user was using right
    before this call), the new window is pushed behind it and focus is
    handed straight back -- so it opens "in the background" instead of
    interrupting whatever the user is doing."""
    before_handles = set(chrome_windows())
    try:
        subprocess.Popen(
            [str(CHROME), f"--profile-directory={profile}", "--new-window",
             *(AWAKE_CHROME_FLAGS if KEEP_COVERED_WINDOWS_AWAKE else []), TARGET_URL],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW
        )
    except Exception as exc:
        log(f"[{profile}] launch failed: {exc}")
        return None, None, False
    hwnd = wait_for_new_window(before_handles)
    if hwnd is None:
        log(f"[{profile}] window did not appear.")
        return None, None, False
    tag_window_with_profile_index(hwnd, index)
    hiding = restore_focus_to is not None and user32.IsWindow(restore_focus_to)
    if hiding:
        set_window_opacity(hwnd, 0)  # suppress the white flash while it loads
        user32.SetWindowPos(hwnd, HWND_BOTTOM, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE)
        user32.SetForegroundWindow(restore_focus_to)
    # Do not wait here for the page to finish loading. That serial wait was the
    # main launch bottleneck: one slow profile could hold up every profile behind
    # it for up to 30 seconds. Register the window immediately as UNVERIFIED;
    # the normal watcher scans it on the next pass and only marks it clear after
    # the page is readable. This preserves limit detection without blocking launch.
    if hiding and user32.IsWindow(hwnd):
        set_window_opacity(hwnd, 255)
    return hwnd, None, False


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
        hit, _, _ = scan_window(hwnd)
        if hit:
            reset_at, reason = compute_reopen_time(hit)
            log(f'[{profile}] limit message found -> closing. Will reopen at {reset_at:%Y-%m-%d %H:%M} ({reason}).')
            if close_window(hwnd):
                info["hwnd"] = None
                info["reopen_at"] = reset_at
                info["unverified_since"] = None
                save_state(state)
            else:
                log(f"[{profile}] could not fully close -- a tab may be blocking it.")


# ================= main: open + watch + auto-reopen, all in one loop =================

plist = profiles()[:MAX_PROFILES]

log("=" * 64)
log("SMART CHROME PROFILE OPENER + LIMIT WATCHER -- session started")
log(f"Detected profiles={len(plist)} max_concurrent={MAX_CONCURRENT_PROFILES} "
    f"check_interval={CHECK_INTERVAL_SECONDS}s safe_cpu<={SAFE_CPU_PERCENT:.0f}% "
    f"safe_ram<={SAFE_RAM_PERCENT:.0f}% retries=one end-of-pass retry + exponential backoff")

_awake = awake_flags_status()
if _awake == "active":
    log("Covered-window protection: ACTIVE (Chrome was started with the keep-awake switches).")
elif _awake == "inactive":
    log("Covered-window protection: NOT active -- Chrome is already running without the keep-awake "
        "switches, so windows hidden behind others can still freeze. To fix it once: run "
        "Chrome_Opener_Close_All.bat, then start this tool again.")
elif _awake == "no-chrome":
    log("Covered-window protection: will be applied to every Chrome window this tool opens.")

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
        failed_this_cycle = []
        launches_paused_this_cycle = False
        _scan_seconds = 0.0
        running_profiles = get_running_profiles()
        for idx, profile in enumerate(plist):
            info = state[profile]
            hwnd = info["hwnd"]

            if hwnd is not None:
                if not user32.IsWindow(hwnd):
                    info["hwnd"] = None  # closed by the user, or something else
                    info["unverified_since"] = None
                    continue
                hit, _, readable = scan_window(hwnd)
                if hit:
                    reset_at, reason = compute_reopen_time(hit)
                    log(f'[{profile}] limit message found -> closing. Will reopen at {reset_at:%Y-%m-%d %H:%M} ({reason}).')
                    if close_window(hwnd):
                        info["hwnd"] = None
                        info["reopen_at"] = reset_at
                        info["unverified_since"] = None
                        save_state(state)
                    else:
                        log(f"[{profile}] could not fully close -- a tab may be blocking it.")
                elif readable:
                    info["unreadable_first"] = None
                    if info.get("unverified_since") is not None:
                        info["unverified_since"] = None
                        log(f"[{profile}] page is now readable -- no limit message, confirmed clear.")
                else:
                    # Could not read the page. Applies to windows that were fine
                    # at launch too: an unreadable window must never count as clear.
                    t = datetime.now()
                    if info.get("unverified_since") is None:
                        if info.get("unreadable_first") is None:
                            info["unreadable_first"] = t
                        elif (t - info["unreadable_first"]).total_seconds() >= UNREADABLE_FLAG_SECONDS:
                            info["unverified_since"] = t
                            log(f"[{profile}] page became unreadable -- limit status UNKNOWN until it can be "
                                f"read again. {scan_diag()}")
                    elif t - info["unverified_since"] >= timedelta(minutes=UNREADABLE_WARN_MINUTES):
                        info["unverified_since"] = t  # warn again after another interval
                        log(f"[{profile}] WARNING: page still unreadable after {UNREADABLE_WARN_MINUTES}+ min "
                            f"-- limit status unknown, please check this window manually. {scan_diag()}")
                continue

            reopen_at = info["reopen_at"]
            if reopen_at is not None and now < reopen_at:
                continue  # still waiting for the reset time

            backoff_until = info["backoff_until"]
            if backoff_until is not None and now < backoff_until:
                continue  # this profile has been failing -- waiting out its backoff

            if profile in running_profiles:
                continue  # already open outside our tracking -- leave it alone

            open_count = sum(1 for s in state.values() if s["hwnd"] is not None)
            if open_count >= MAX_CONCURRENT_PROFILES:
                continue  # at the concurrency cap -- wait for a slot to free up

            if launches_paused_this_cycle:
                continue  # still monitor existing profiles, but defer new launches until next cycle
            if not resources_safe_for_launch():
                launches_paused_this_cycle = True
                continue

            close_any_limited_now(state)  # catch anything that just hit its limit before we open another

            running_profiles = get_running_profiles(force=True)  # fresh list right before launching
            if profile in running_profiles:
                continue  # it turned out to be open already

            log(f"[{profile}] opening...")
            any_open = any(s["hwnd"] is not None for s in state.values())
            keep_focus_on = user32.GetForegroundWindow() if any_open else None
            new_hwnd, hit, readable = launch_profile(profile, idx, restore_focus_to=keep_focus_on)
            if new_hwnd is None:
                record_launch_failure(profile, info)
                failed_this_cycle.append((profile, idx))
                continue

            record_launch_success(profile, info, new_hwnd, hit, state, readable)
            running_profiles.add(profile)

        # One extra opportunity for profiles that failed earlier in this scan.
        # It is intentionally bounded: persistent failures use the normal backoff
        # and do not block monitoring for the rest of the session.
        if failed_this_cycle:
            log(f"End-of-pass retry: {len(failed_this_cycle)} profile(s) failed earlier; retrying once where resources allow.")
            time.sleep(END_PASS_RETRY_DELAY_SECONDS)
            retry_launches_paused = False
            running_profiles = get_running_profiles(force=True)
            for profile, idx in failed_this_cycle:
                info = state[profile]
                if info["hwnd"] is not None or profile in running_profiles:
                    continue  # avoid duplicate windows if a launch eventually appeared
                open_count = sum(1 for s in state.values() if s["hwnd"] is not None)
                if open_count >= MAX_CONCURRENT_PROFILES:
                    log(f"[{profile}] end-of-pass retry skipped: concurrency limit reached.")
                    continue
                if retry_launches_paused:
                    continue
                if not resources_safe_for_launch():
                    retry_launches_paused = True
                    log(f"[{profile}] end-of-pass retry deferred because system load is high; scheduled backoff remains active.")
                    continue
                log(f"[{profile}] end-of-pass retry...")
                any_open = any(s["hwnd"] is not None for s in state.values())
                keep_focus_on = user32.GetForegroundWindow() if any_open else None
                retry_hwnd, retry_hit, retry_readable = launch_profile(profile, idx, restore_focus_to=keep_focus_on)
                if retry_hwnd is None:
                    record_launch_failure(profile, info)
                else:
                    record_launch_success(profile, info, retry_hwnd, retry_hit, state, retry_readable)
                    running_profiles.add(profile)

        print(f"\r  Last check: {now:%H:%M:%S}   ", end="", flush=True)
        # Adaptive pause: if this cycle's SCANNING was slow, sleep longer so the watcher
        # never spends more than ~MAX_SCAN_DUTY_CYCLE of the time scanning. Launching and
        # closing windows is not counted, so it never delays the next check. When scans are
        # quick this stays at CHECK_INTERVAL_SECONDS.
        wait = max(CHECK_INTERVAL_SECONDS, _scan_seconds * (1 - MAX_SCAN_DUTY_CYCLE) / MAX_SCAN_DUTY_CYCLE)
        time.sleep(min(wait, MAX_ADAPTIVE_SLEEP_SECONDS))
except KeyboardInterrupt:
    log("Session stopped by user (Ctrl+C).")
    save_state(state)

input("\nPress Enter to close...")
