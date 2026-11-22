"""Claude Auto Continue -- inspection stage. READ-ONLY (nothing is clicked, typed, closed or navigated).

Run it while a Claude chat window is open (for example a chat that shows "Paused when your
free usage ran out. Continue ..."). It reads every window of the targeted Google Chrome through
UI Automation and writes inspect_report.txt next to this script with:
  * every control whose name looks like a Continue / Try again / Paused / sidebar-list item,
  * every button and every link of the page (name, id, supported actions, link address).
That tells us the exact names and the exact way Chrome exposes the buttons and the sidebar
chat list, so an automatic "Continue" click can be built on facts instead of guesses.
The report contains your chat titles. It stays on your computer (it is ignored by git).
Part of the separate project "Claude Auto Continue" (see README.md in this folder)."""
import ctypes
import os
import time
from datetime import datetime
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
VERSION = "0.2.0"
PROJECT_NAME = "Claude Auto Continue"

BROWSER_LABEL = "Google Chrome"
SCRIPT_DIR = Path(__file__).resolve().parent
REPORT_FILE = SCRIPT_DIR / "inspect_report.txt"
KEYWORDS = ("continue", "try again", "retry", "paused", "stopped", "usage limit", "free usage", "ran out",
            "free messages", "resume", "new chat", "chats and tasks", "recents", "view all")
MAX_TREE_DEPTH = 30
MAX_NODES_PER_WINDOW = 4000      # stop reading one window after this many controls
MAX_SECONDS_PER_WINDOW = 60      # ...or after this many seconds
MAX_LINES_PER_SECTION = 150      # report size limit per section and window


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


def say(text):
    """print() that cannot crash on a console that cannot show Bengali letters."""
    try:
        print(text)
    except UnicodeEncodeError:
        print(str(text).encode("ascii", "replace").decode("ascii"))

def is_target_window(hwnd):
    try:
        pid = ctypes.c_ulong(0)
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value:
            return False
        return is_target_executable(psutil.Process(pid.value).exe())
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


def short(value, limit=60):
    value = " ".join(str(value if value is not None else "").split())
    return value if len(value) <= limit else value[:limit - 3] + "..."

def safe(getter, default=""):
    try:
        return getter()
    except Exception:
        return default

def pattern_flags(control):
    """Which actions the control offers to UI Automation (Invoke = can be pressed)."""
    flags = []
    for label, attr in (("Invoke", "InvokePattern"), ("Toggle", "TogglePattern"),
                        ("ExpandCollapse", "ExpandCollapsePattern"), ("Value", "ValuePattern"),
                        ("SelectionItem", "SelectionItemPattern"), ("LegacyIAccessible", "LegacyIAccessiblePattern")):
        try:
            if control.GetPattern(getattr(auto.PatternId, attr)) is not None:
                flags.append(label)
        except Exception:
            pass
    return ",".join(flags) or "-"

def rect_text(control):
    def get():
        r = control.BoundingRectangle
        return f"x={r.left} y={r.top} w={r.right - r.left} h={r.bottom - r.top}"
    return safe(get, "?")

def describe(control, ctype, name, path):
    default_action = ""
    value = ""
    try:
        legacy = control.GetLegacyIAccessiblePattern()
        if legacy is not None:
            default_action = safe(lambda: legacy.DefaultAction)
            value = safe(lambda: legacy.Value)
    except Exception:
        pass
    return (f"{ctype.replace('Control', '')} | name='{short(name, 80)}' "
            f"| id='{short(safe(lambda: control.AutomationId), 40)}' "
            f"| class='{short(safe(lambda: control.ClassName), 30)}' "
            f"| patterns={pattern_flags(control)} | default_action='{short(default_action, 30)}' "
            f"| value='{short(value, 120)}' | enabled={safe(lambda: control.IsEnabled, '?')} "
            f"| offscreen={safe(lambda: control.IsOffscreen, '?')} | {rect_text(control)} | path: {path}")

def inspect_tree(walk, max_nodes=MAX_NODES_PER_WINDOW, max_seconds=MAX_SECONDS_PER_WINDOW, clock=time.time):
    """Reads (control, depth) pairs from `walk` and sorts out the interesting ones. Read-only."""
    started = clock()
    result = {"nodes": 0, "doc_found": False, "page_nodes": 0, "truncated": False,
              "keyword": [], "buttons": [], "links": [], "elapsed": 0.0}
    stack = {}          # depth -> (type, name) of the ancestors of the control being looked at
    doc_depth = None    # depth of the page's Document node while we are inside it
    for control, depth in walk:
        result["nodes"] += 1
        if result["nodes"] > max_nodes or clock() - started > max_seconds:
            result["truncated"] = True
            break
        ctype = safe(lambda: control.ControlTypeName, "?")
        name = safe(lambda: control.Name, "") or ""
        stack[depth] = (ctype, name)
        for deeper in [k for k in stack if k > depth]:
            del stack[deeper]
        if ctype == "DocumentControl":
            result["doc_found"] = True
            if doc_depth is None:
                doc_depth = depth
        elif doc_depth is not None and depth <= doc_depth:
            doc_depth = None
        if doc_depth is not None and depth > doc_depth and name:
            result["page_nodes"] += 1
        if not name:
            continue
        lowered = name.casefold()
        want_keyword = any(k in lowered for k in KEYWORDS) and len(result["keyword"]) < MAX_LINES_PER_SECTION
        want_button = ctype == "ButtonControl" and len(result["buttons"]) < MAX_LINES_PER_SECTION
        want_link = ctype == "HyperlinkControl" and len(result["links"]) < MAX_LINES_PER_SECTION
        if not (want_keyword or want_button or want_link):
            continue
        ancestors = [stack[d] for d in sorted(stack) if d < depth][-4:]
        path = " > ".join(f"{t.replace('Control', '')}:'{short(n, 25)}'" for t, n in ancestors) or "(top)"
        line = describe(control, ctype, name, path)
        if want_keyword:
            result["keyword"].append(line)
        if want_button:
            result["buttons"].append(line)
        if want_link:
            result["links"].append(line)
    result["elapsed"] = clock() - started
    return result

def report_lines(index, hwnd, title, result):
    lines = ["", "=" * 78,
             f"WINDOW {index}: hwnd={hwnd} title='{short(title, 100)}'",
             f"controls read={result['nodes']}{' (stopped early: limit reached)' if result['truncated'] else ''}, "
             f"page document found={result['doc_found']}, named page controls={result['page_nodes']}, "
             f"time={result['elapsed']:.1f}s",
             "-" * 78,
             f"A) CONTROLS WITH A KEYWORD IN THEIR NAME ({', '.join(KEYWORDS)}): {len(result['keyword'])}"]
    lines += ["  " + l for l in result["keyword"]] or ["  (none)"]
    lines += ["", f"B) ALL BUTTONS: {len(result['buttons'])}"]
    lines += ["  " + l for l in result["buttons"]] or ["  (none)"]
    lines += ["", f"C) ALL LINKS (the sidebar chat list should be here): {len(result['links'])}"]
    lines += ["  " + l for l in result["links"]] or ["  (none)"]
    return lines

def main():
    say("=" * 64)
    say(f"   {PROJECT_NAME.upper()} v{VERSION} - INSPECT (read-only, nothing is clicked or changed)")
    say("=" * 64)
    windows = target_windows()
    if not windows:
        say(f"No {BROWSER_LABEL} window was found. Open the Claude chat window first, then run this again.")
        input("\nPress Enter to exit...")
        raise SystemExit(1)
    say(f"Found {len(windows)} {BROWSER_LABEL} window(s). Reading them; this can take up to a minute...")
    lines = [f"{PROJECT_NAME} v{VERSION} - inspect report, {datetime.now():%Y-%m-%d %H:%M:%S}",
             f"Chrome: {TARGET_EXE}", f"Windows read: {len(windows)}"]
    for index, hwnd in enumerate(windows, 1):
        title = window_title(hwnd)
        try:
            root = auto.ControlFromHandle(hwnd)
            result = inspect_tree(auto.WalkControl(root, includeTop=True, maxDepth=MAX_TREE_DEPTH))
        except Exception as exc:
            lines += ["", "=" * 78, f"WINDOW {index}: hwnd={hwnd} title='{short(title, 100)}'", f"  could not be read: {exc}"]
            say(f"  window {index}: could not be read ({exc})")
            continue
        lines += report_lines(index, hwnd, title, result)
        say(f"  window {index}: {result['nodes']} controls, keyword matches={len(result['keyword'])}, "
            f"buttons={len(result['buttons'])}, links={len(result['links'])}")
    with open(REPORT_FILE, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    say("")
    say(f"Report written to: {REPORT_FILE}")
    say("Next: open that file in Notepad and send me its content (or at least the A and C sections).")
    input("\nPress Enter to close...")

if __name__ == "__main__":
    main()
