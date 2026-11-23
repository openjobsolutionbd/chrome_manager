"""Claude Auto Continue -- finds the "Continue" / "Try again" button of a Claude chat that stopped at the
usage limit and (when DRY_RUN is False) presses it. Version 0.3.x also visits the other tabs and the sidebar chats of each profile window.
With DRY_RUN = True it only writes to auto_continue_log.txt what it WOULD press.

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
import sys
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

# --- works with different uiautomation versions ---
# uiautomation 2.0.x names the client class "_AutomationClient" (with a leading underscore). Python's
# "import *" does not export such names, so it is NOT found on the package itself but only in the library's
# inner module (uiautomation.uiautomation). Older versions call it "AutomationClient". All places are tried.
# 2.0.x also has no "TreeScope" class, and offers CreateControlFromElement only as Control.CreateControlFromElement.
TREE_DESCENDANTS = 4   # the UI Automation constant TreeScope_Descendants

def get_uia():
    modules = (auto, getattr(auto, "uiautomation", None), sys.modules.get("uiautomation.uiautomation"))
    for module in modules:
        for name in ("_AutomationClient", "AutomationClient"):
            client = getattr(module, name, None) if module is not None else None
            if client is not None:
                return client.instance().IUIAutomation
    raise RuntimeError("This version of uiautomation is not supported (no UI Automation client found). "
                       "Run: py -m pip install --upgrade uiautomation")

def create_control(element):
    maker = getattr(auto, "CreateControlFromElement", None) or auto.Control.CreateControlFromElement
    return maker(element)

# Project version (see CHANGELOG.md). Bump with every merged change to this project.
# Claude_Auto_Continue_Inspect.py carries the same number; keep both equal.
VERSION = "0.3.5"
PROJECT_NAME = "Claude Auto Continue"

DRY_RUN = False                   # True: only log what would be pressed. False: really press the button.
SCAN_INTERVAL_SECONDS = 30        # how often every Claude window is checked
WINDOW_GAP_SECONDS = 0.2          # small pause between two windows, so the checks never pile up
MIN_GAP_MINUTES = 10              # per chat: at least this long between two presses
MAX_PRESSES_PER_HOUR = 3          # per chat: never more presses than this in one hour
REPEAT_LOG_MINUTES = 10           # the same situation is written to the log again only after this long
LIST_SIDEBAR_CHATS = False        # log the chat list of the sidebar (information for the next version)
SIDEBAR_LIST_EVERY_MINUTES = 30
MAX_LINKS_SCANNED = 150
MAX_SIDEBAR_NAMES_LOGGED = 20
BANNER_CONTAINER_LEVELS = 5       # how many levels above the banner text the button is searched in
VISIT_TABS = True                 # also look at the other Claude tabs of a window (switches the tab, then switches back)
VISIT_SIDEBAR = True              # also open the chats of the sidebar one by one, then return to the first chat
VISIT_EVERY_MINUTES = 5           # per window: how often such a visit round is made
MAX_CHATS_PER_ROUND = 8           # per window and round: at most this many sidebar chats are opened
MAX_VISIT_SECONDS = 90            # per window and round: a visit never takes longer than this
MIN_SETTLE_SECONDS = 1.5          # wait after switching a tab / chat before reading it
PAGE_SETTLE_SECONDS = 8           # ...and at most this long until the page is readable
BANNER_RENDER_SECONDS = 1.5       # extra wait once the page is readable: the banner appears a moment later
HOLD_AFTER_PRESS_MINUTES = 5      # after a press the window is left alone (no switching) so the chat can continue
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

def present(element):
    """True when a UI Automation call really returned something. When nothing is found the library hands back an
    empty (NULL) COM pointer, which is NOT None, so a plain 'is None' test wrongly says 'found'."""
    return element is not None and bool(element)

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
                # Chat ids stay valid after a restart; window-handle keys ("hwnd:...") do not, so they are dropped.
                loaded = history_from_json(json.load(f).get("presses"))
                history.update({k: v for k, v in loaded.items() if not k.startswith("hwnd:")})
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
        "limit_each": {p: name_cond(p, 3) for p in LIMIT_ACTIVE_PHRASES},
        "button": {b: uia.CreateAndCondition(button_type, name_cond(b, 1)) for _p, b in BANNERS},
        "link": uia.CreatePropertyCondition(auto.PropertyId.ControlTypeProperty, auto.ControlType.HyperlinkControl),
        "document": uia.CreatePropertyCondition(auto.PropertyId.ControlTypeProperty, auto.ControlType.DocumentControl),
        "tab": uia.CreatePropertyCondition(auto.PropertyId.ControlTypeProperty, auto.ControlType.TabItemControl),
    }

def page_documents(root, conds):
    """The web page(s) of the window (UI Automation Document nodes). Everything is searched INSIDE them, never in
    Chrome's own toolbar / tab strip, so a tab title or bookmark can not be mistaken for the banner."""
    docs = root.FindAll(TREE_DESCENDANTS, conds["document"])
    if not present(docs):
        return []
    return [docs.GetElement(i) for i in range(docs.Length)]

def page_is_readable(uia, doc):
    """A frozen page (window covered by other windows or minimized) has a Document node with NO children."""
    try:
        child = uia.ControlViewWalker.GetFirstChildElement(doc)
        return bool(child)
    except Exception:
        return False

def banner_hit(doc, conds):
    """(banner element, banner text, its button name) when a known banner is on the page, else None."""
    if not present(doc.FindFirst(TREE_DESCENDANTS, conds["any_banner"])):
        return None
    for phrase, button in BANNERS:
        element = doc.FindFirst(TREE_DESCENDANTS, conds["banner"][phrase])
        if present(element):
            return element, phrase, button
    return None

def find_button_near_banner(uia, banner_element, conds, button):
    """Looks for the button only in the container of the banner text: starts at the banner element and goes up
    a few levels. The first level that contains the exact button wins. Returns the elements found (list)."""
    walker = uia.ControlViewWalker
    node = banner_element
    for _level in range(BANNER_CONTAINER_LEVELS):
        try:
            node = walker.GetParentElement(node)
        except Exception:
            return []
        if not node:
            return []
        found = node.FindAll(TREE_DESCENDANTS, conds["button"][button])
        if present(found) and found.Length > 0:
            return [found.GetElement(i) for i in range(found.Length)]
    return []

def button_control(element):
    return create_control(element)

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

def describe_element(element):
    """What an element is, for the log: its text, its type, whether it is off screen and where it is."""
    name = safe(lambda: element.CurrentName, "") or ""
    kind = safe(lambda: element.CurrentLocalizedControlType, "") or "?"
    off = safe(lambda: bool(element.CurrentIsOffscreen), "?")
    return f"'{short(name, 100)}' (type {kind}, offscreen={off}, {rect_text(element)})"

def active_limit_hit(doc, conds):
    """(phrase, element) of the first 'limit is still active' text on the page, or None when there is none.
    The element is only used to tell the log what was found."""
    if not present(doc.FindFirst(TREE_DESCENDANTS, conds["limit"])):
        return None
    for phrase in LIMIT_ACTIVE_PHRASES:
        element = doc.FindFirst(TREE_DESCENDANTS, conds["limit_each"][phrase])
        if present(element):
            return phrase, element
    return "?", None

def control_of(element):
    return safe(lambda: create_control(element))

def element_value(element):
    """The 'value' Chrome gives an element: for a link its address, for the page Document its address."""
    control = control_of(element)
    return safe(lambda: control.GetLegacyIAccessiblePattern().Value, "") or ""

def chat_id_from_url(url):
    if "/chat/" not in (url or ""):
        return ""
    return url.split("/chat/", 1)[1].split("?", 1)[0].split("#", 1)[0].strip("/")

def page_key(hwnd, docs):
    """Counter key of the chat on screen: the chat id (stable across restarts, title changes and tab switches);
    when the address can not be read, one counter for the whole window."""
    for doc in docs:
        chat = chat_id_from_url(element_value(doc))
        if chat:
            return chat
    return f"hwnd:{hwnd}"

_hold_until = {}    # window -> no tab / chat switching before this time (a chat was just continued)

def handle_window(uia, conds, hwnd, title, now, tag=None):
    """One check of the page that is on screen in one window. Returns "pressed" when the button was really pressed.
    `tag` is set when the page was brought up by a visit (other tab / sidebar chat)."""
    label = f"[window {hwnd} '{short(title, 50)}']"
    root = uia.ElementFromHandle(hwnd)
    if not present(root):
        return ""
    if user32.IsIconic(hwnd):
        log_changed(f"state|{hwnd}", f"{label} window is MINIMIZED -> its page is frozen by Chrome and can not be read.", now)
        return ""
    docs = page_documents(root, conds)
    if not docs:
        log_changed(f"state|{hwnd}", f"{label} no web page found in this window (not a page, or Chrome has not exposed it).", now)
        return ""
    if not any(page_is_readable(uia, d) for d in docs):
        log_changed(f"state|{hwnd}", f"{label} page is EMPTY/FROZEN (window covered by other windows? Chrome freezes such pages) -> cannot look for the banner.", now)
        return ""
    key = page_key(hwnd, docs)
    if tag:
        label = f"{label} [{tag}, chat {short(key, 14)}]"
    hits = [banner_hit(d, conds) for d in docs]
    if all(h is None for h in hits):
        if tag is None:
            log_changed(f"state|{hwnd}", f"{label} page readable, no banner.", now)
        _last_logged.pop(key, None)   # no banner any more: a later banner is news again
        return ""
    for doc, hit in zip(docs, hits):
        if hit is None:
            continue
        banner_element, phrase, button = hit
        limit = active_limit_hit(doc, conds)
        if limit is not None:
            limit_phrase, limit_element = limit
            seen = describe_element(limit_element) if limit_element is not None else "(element not found again)"
            log_changed(key, f"{label} banner '{phrase}' found, but the limit is still active on this page -> not pressing. "
                             f"Limit text '{limit_phrase}' found in: {seen}. Banner: {describe_element(banner_element)}", now)
            return ""
        found = find_button_near_banner(uia, banner_element, conds, button)
        if not found:
            log_changed(key, f"{label} banner '{phrase}' found, but no button named exactly '{button}' next to it -> not pressing.", now)
            return ""
        element = found[0]
        several = "" if len(found) == 1 else f" ({len(found)} buttons have that name; the first is used)"
        allowed, reason = decide_press(history.get(key, []), now)
        if not allowed:
            log_changed(key, f"{label} '{button}' button present -> not pressing: {reason}.{several}", now)
            return ""
        control = safe(lambda: button_control(element))
        supported = has_invoke(control)
        where = rect_text(element)
        if DRY_RUN:
            # A dry run presses nothing, so it must not count as a press either (it would block the real one later).
            log_changed(key, f"{label} DRY-RUN: would press '{button}' under '{phrase}' ({reason}; Invoke supported: "
                             f"{'yes' if supported else 'NO'}; {where}){several}", now)
            return ""
        if not supported:
            log_changed(key, f"{label} '{button}' button found but it offers no Invoke action -> cannot press ({where}).", now)
            return ""
        done, info = press(control)
        if done:
            history.setdefault(key, []).append(now)
            save_state()
            if tag != "tab":   # a chat continued in another TAB keeps running in the background; no hold needed
                _hold_until[hwnd] = now + timedelta(minutes=HOLD_AFTER_PRESS_MINUTES)
        log_changed(key, f"{label} '{button}' under '{phrase}': {info} ({reason}; {where}){several}", now)
        return "pressed" if done else ""
    return ""


# ---------- visiting the other tabs and the sidebar chats ----------

_next_visit = {}        # window -> time of the next visit round
_sidebar_warned = set()

def list_tabs(root, conds):
    found = root.FindAll(TREE_DESCENDANTS, conds["tab"])
    tabs = []
    if not present(found):
        return tabs
    for i in range(found.Length):
        element = found.GetElement(i)
        name = safe(lambda: element.CurrentName, "") or ""
        control = control_of(element)
        pattern = safe(lambda: control.GetSelectionItemPattern())
        selected = bool(safe(lambda: pattern.IsSelected, False)) if pattern is not None else False
        tabs.append({"element": element, "name": name, "selected": selected, "selectable": pattern is not None})
    return tabs

def select_element(element):
    """Switches to a tab through the UI Automation Select action (no mouse, no keyboard, no focus change)."""
    control = control_of(element)
    pattern = safe(lambda: control.GetSelectionItemPattern())
    if pattern is None:
        return False
    try:
        try:
            pattern.Select(waitTime=0)
        except TypeError:
            pattern.Select()
        return True
    except Exception:
        return False

def invoke_element(element):
    control = control_of(element)
    if control is None:
        return False
    done, _info = press(control)
    return done

def sidebar_links(uia, conds, hwnd):
    """{chat id: (name, element)} of the chat links in the window, in page order."""
    root = uia.ElementFromHandle(hwnd)
    out = {}
    if not present(root):
        return out
    links = root.FindAll(TREE_DESCENDANTS, conds["link"])
    if not present(links):
        return out
    for i in range(min(links.Length, MAX_LINKS_SCANNED)):
        element = links.GetElement(i)
        chat = chat_id_from_url(element_value(element))
        if chat and chat not in out:
            out[chat] = (short(safe(lambda: element.CurrentName, ""), 40), element)
    return out

def current_chat_id(uia, conds, hwnd):
    root = uia.ElementFromHandle(hwnd)
    if not present(root):
        return ""
    for doc in page_documents(root, conds):
        chat = chat_id_from_url(element_value(doc))
        if chat:
            return chat
    return ""

def wait_for_page(uia, conds, hwnd, expect_chat=None):
    """Waits until the page that was just brought up is readable (and, for a chat, shows that chat)."""
    time.sleep(MIN_SETTLE_SECONDS)
    end = time.time() + PAGE_SETTLE_SECONDS
    while True:
        root = safe(lambda: uia.ElementFromHandle(hwnd))
        docs = page_documents(root, conds) if present(root) else []
        ready = any(page_is_readable(uia, d) for d in docs)
        if ready and expect_chat:
            ready = any(chat_id_from_url(element_value(d)) == expect_chat for d in docs)
        if ready:
            time.sleep(BANNER_RENDER_SECONDS)
            return True
        if time.time() >= end:
            return False
        time.sleep(0.5)

def visit_window(uia, conds, hwnd, title, now):
    """One visit round of one window: every other Claude tab, then the sidebar chats, then back to where it was.
    Skipped while the user works in that window, while it is minimized, right after a press and between rounds."""
    if not (VISIT_TABS or VISIT_SIDEBAR):
        return
    hold = _hold_until.get(hwnd)
    if hold is not None and now < hold:
        return
    due = _next_visit.get(hwnd)
    if due is not None and now < due:
        return
    if user32.IsIconic(hwnd) or user32.GetForegroundWindow() == hwnd:
        return   # frozen page, or the user is working in this window right now
    _next_visit[hwnd] = now + timedelta(minutes=VISIT_EVERY_MINUTES)
    label = f"[window {hwnd} '{short(title, 50)}']"
    root = uia.ElementFromHandle(hwnd)
    if not present(root):
        return
    started = time.time()
    stats = {"tabs": 0, "chats": 0, "pressed": 0}

    def stop_now():
        return time.time() - started > MAX_VISIT_SECONDS or user32.GetForegroundWindow() == hwnd

    # --- other tabs ---
    tabs = list_tabs(root, conds) if VISIT_TABS else []
    original = next((t for t in tabs if t["selected"]), None)
    others = [t for t in tabs if t is not original and t["selectable"] and "claude" in t["name"].casefold()]
    moved_tab = False
    for tab in others:
        if stop_now():
            break
        if not select_element(tab["element"]):
            continue
        moved_tab = True
        wait_for_page(uia, conds, hwnd)
        stats["tabs"] += 1
        if handle_window(uia, conds, hwnd, window_title(hwnd), datetime.now(), tag="tab") == "pressed":
            stats["pressed"] += 1
    if moved_tab and original is not None:
        select_element(original["element"])
        time.sleep(0.5)

    # --- sidebar chats (in the tab that was in front) ---
    if VISIT_SIDEBAR and not stop_now() and not on_hold(hwnd):
        links = sidebar_links(uia, conds, hwnd)
        if not links:
            if hwnd not in _sidebar_warned:
                _sidebar_warned.add(hwnd)
                log(f"{label} no chat links with a readable address found in the sidebar -> sidebar chats are not visited in this window.")
        else:
            original_chat = current_chat_id(uia, conds, hwnd)
            targets = [c for c in links if c != original_chat][:MAX_CHATS_PER_ROUND]
            moved_chat = False
            stayed = False
            for chat in targets:
                if stop_now():
                    break
                fresh = sidebar_links(uia, conds, hwnd).get(chat)   # the sidebar is redrawn after every switch
                if fresh is None or not invoke_element(fresh[1]):
                    continue
                moved_chat = True
                wait_for_page(uia, conds, hwnd, expect_chat=chat)
                stats["chats"] += 1
                if handle_window(uia, conds, hwnd, window_title(hwnd), datetime.now(), tag="sidebar") == "pressed":
                    stats["pressed"] += 1
                    stayed = True   # stay on this chat: it is running again (the window is on hold for a while)
                    break
            if moved_chat and not stayed and original_chat:
                back = sidebar_links(uia, conds, hwnd).get(original_chat)
                if back is not None and invoke_element(back[1]):
                    wait_for_page(uia, conds, hwnd, expect_chat=original_chat)
    log_changed(f"visit|{hwnd}", f"{label} visit round: {stats['tabs']} other tab(s) and {stats['chats']} sidebar chat(s) "
                                 f"looked at, {stats['pressed']} pressed.", datetime.now())

def on_hold(hwnd):
    """A press (also one in another tab) puts the window on hold, so no chat switching follows."""
    hold = _hold_until.get(hwnd)
    return hold is not None and datetime.now() < hold

def list_sidebar_chats(uia, conds, hwnd, title, now):
    """Information only: writes the chats of the sidebar to the log (every SIDEBAR_LIST_EVERY_MINUTES).
    Nothing is opened or clicked. Needed to plan the next version (visiting each chat)."""
    due = _next_sidebar.get(hwnd)
    if due is not None and now < due:
        return
    _next_sidebar[hwnd] = now + timedelta(minutes=SIDEBAR_LIST_EVERY_MINUTES)
    root = uia.ElementFromHandle(hwnd)
    if not present(root):
        return
    links = root.FindAll(TREE_DESCENDANTS, conds["link"])
    total = 0 if not present(links) else links.Length
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
            visit_window(uia, conds, hwnd, title, datetime.now())
        except Exception as exc:
            log_changed(f"error|{hwnd}", f"[window {hwnd}] could not be checked: {exc}", now)
        time.sleep(WINDOW_GAP_SECONDS)

AWAKE_CHROME_FLAGS = ("--disable-features=CalculateNativeWinOcclusion", "--disable-backgrounding-occluded-windows")

def awake_flags_status():
    """'active' when the running Chrome was started with the switches that stop it from freezing covered windows."""
    saw_browser = False
    for p in psutil.process_iter(["name", "cmdline", "exe"]):
        try:
            if (p.info.get("name") or "").lower() != "chrome.exe" or not is_target_executable(p.info.get("exe")):
                continue
            args = p.info.get("cmdline") or []
            if any(a.startswith("--type=") for a in args):
                continue
            saw_browser = True
            if all(flag in args for flag in AWAKE_CHROME_FLAGS):
                return "active"
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass
    return "inactive" if saw_browser else "no-chrome"

def ensure_single_instance():
    """Two copies would press the same button twice; the second one stops here."""
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    handle = kernel32.CreateMutexW(None, False, "Local\\ClaudeAutoContinueSingleInstance")
    if ctypes.get_last_error() == 183:   # ERROR_ALREADY_EXISTS
        print("Claude Auto Continue is already running in another window. Close that one first (or use Stop_All.bat).")
        input("\nPress Enter to exit...")
        raise SystemExit(1)
    return handle

_instance_mutex = None

def main():
    global _instance_mutex
    _instance_mutex = ensure_single_instance()
    prune_log(force=True)
    log("=" * 64)
    log(f"{PROJECT_NAME} v{VERSION} -- started. mode={'DRY-RUN (nothing is pressed)' if DRY_RUN else 'PRESSING'} "
        f"interval={SCAN_INTERVAL_SECONDS}s gap={MIN_GAP_MINUTES}min max_per_hour={MAX_PRESSES_PER_HOUR}")
    load_state()
    status = awake_flags_status()
    if status == "active":
        log("Covered-window protection: ACTIVE (Chrome was started with the keep-awake switches).")
    elif status == "inactive":
        log("WARNING: Chrome was started WITHOUT the keep-awake switches. Windows hidden behind other windows or "
            "minimized are frozen by Chrome and CANNOT be read, so only the visible window works. Fix: close ALL Chrome "
            "windows (also the background Chrome in the tray), then start Chrome_Opener.bat again.")
    uia = get_uia()
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
