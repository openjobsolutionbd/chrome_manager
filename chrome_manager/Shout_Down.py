import ctypes
import os
import subprocess
import time
from pathlib import Path

try:
    import psutil
except ImportError:
    print("psutil is required. Run: py -m pip install psutil")
    input("\nPress Enter to exit...")
    raise SystemExit(1)

BROWSER_LABEL = "Google Chrome"
OPENER_SCRIPT_NAME = "chrome_opener.py"  # the watcher; it reopens closed windows, so it is stopped first

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
    print(f"{BROWSER_LABEL} executable was not found; shutdown cancelled.")
    input("\nPress Enter to exit...")
    raise SystemExit(1)

user32 = ctypes.windll.user32
WM_CLOSE = 0x0010
GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
LWA_ALPHA = 0x2
EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
user32.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
user32.GetWindowThreadProcessId.restype = ctypes.c_ulong
user32.GetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int]
user32.GetWindowLongW.restype = ctypes.c_long
user32.SetLayeredWindowAttributes.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_ubyte, ctypes.c_uint]
user32.SetLayeredWindowAttributes.restype = ctypes.c_bool

CLOSE_TIMEOUT_SECONDS = 30       # windows: keep asking them to close this long (a dialog may be waiting)
EXIT_TIMEOUT_SECONDS = 30        # no windows left: longest wait for Chrome's processes to finish exiting
BACKGROUND_STABLE_SECONDS = 3    # no windows and the same processes for this long = background leftovers, not a closing Chrome
WINDOW_POLL_SECONDS = 0.25
EXIT_POLL_SECONDS = 0.2
SHUTDOWN_DELAY_SECONDS = 0       # shut down right away

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

def target_browser_pids():
    """PIDs of every process of the targeted Chrome (browser, renderers, background)."""
    pids = set()
    for p in psutil.process_iter(["pid", "name"]):
        try:
            if (p.info.get("name") or "").lower() == "chrome.exe" and is_target_executable(p.exe()):
                pids.add(p.info["pid"])
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass
    return pids

def other_chrome_running():
    # Shutdown affects every application, so protect unsaved work in any other Chrome channel.
    for p in psutil.process_iter(["name"]):
        try:
            if (p.info.get("name") or "").lower() == "chrome.exe" and not is_target_executable(p.exe()):
                return True
        except psutil.AccessDenied:
            return True  # a chrome.exe we cannot identify: be careful and treat it as another channel
        except (psutil.NoSuchProcess, psutil.ZombieProcess):
            pass
    return False

def find_opener_processes():
    """Running copies of Chrome_Opener.py (python or the py launcher). The script file name must
    match exactly, so Chrome_Opener_Close_All.py and this script are never matched."""
    found = []
    me = os.getpid()
    for p in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            if p.info.get("pid") == me:
                continue
            name = (p.info.get("name") or "").lower()
            if not (name.startswith("python") or name in ("py.exe", "pyw.exe")):
                continue
            for arg in (p.info.get("cmdline") or []):
                if str(arg).replace("\\", "/").rsplit("/", 1)[-1].lower() == OPENER_SCRIPT_NAME:
                    found.append(p)
                    break
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass
    return found

def stop_processes(procs):
    """Stop the given processes. Returns True when none of them is left."""
    for p in procs:
        try:
            p.terminate()
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass
    _gone, alive = psutil.wait_procs(procs, timeout=3)
    for p in alive:
        try:
            p.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass
    _gone, alive = psutil.wait_procs(alive, timeout=2)
    return not alive

def make_windows_visible():
    """Chrome_Opener keeps new windows fully transparent until their page has loaded. If it was
    stopped and shutdown is cancelled, nothing would make them visible again, so do it here."""
    for hwnd in target_windows():
        try:
            if user32.GetWindowLongW(hwnd, GWL_EXSTYLE) & WS_EX_LAYERED:
                user32.SetLayeredWindowAttributes(hwnd, 0, 255, LWA_ALPHA)
        except Exception:
            pass

def cancel(lines, opener_stopped):
    make_windows_visible()
    for line in lines:
        print(line)
    print("Shutdown was cancelled so nothing gets lost.")
    if opener_stopped:
        print("Chrome_Opener was stopped; start it again with Chrome_Opener.bat.")
    input("\nPress Enter to exit...")
    raise SystemExit(1)

def main():
    # Check first, before anything is closed or stopped.
    if other_chrome_running():
        cancel(["Another Chrome channel (not this " + BROWSER_LABEL + ") is running.",
                "Nothing was closed."], False)

    # Chrome_Opener reopens any window that closes, so it has to stop first.
    opener_stopped = False
    opener_procs = find_opener_processes()
    if opener_procs:
        opener_stopped = stop_processes(opener_procs)
        if opener_stopped:
            print("Chrome_Opener stopped.")
        else:
            print("Warning: Chrome_Opener could not be stopped; it may reopen windows.")

    started = time.time()
    exit_started = None
    last_pids = None
    stable_since = None
    note = f"{BROWSER_LABEL} is closed."
    while True:
        windows = target_windows()
        now = time.time()
        if windows:
            exit_started = None
            last_pids = None
            stable_since = None
            if now - started >= CLOSE_TIMEOUT_SECONDS:
                cancel([f"{BROWSER_LABEL} did not close within {CLOSE_TIMEOUT_SECONDS} seconds "
                        "(a dialog may be waiting)."], opener_stopped)
            for hwnd in windows:
                user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
            time.sleep(WINDOW_POLL_SECONDS)
            continue
        pids = target_browser_pids()
        if not pids:
            break
        if exit_started is None:
            exit_started = now
        if pids != last_pids:
            last_pids = pids
            stable_since = now
        elif now - stable_since >= BACKGROUND_STABLE_SECONDS:
            note = f"{BROWSER_LABEL} has no windows left; only its background processes remain."
            break
        if now - exit_started >= EXIT_TIMEOUT_SECONDS:
            note = f"{BROWSER_LABEL} has no windows left but its processes are still exiting."
            break
        time.sleep(EXIT_POLL_SECONDS)

    if other_chrome_running():
        cancel([f"{BROWSER_LABEL} is closed, but another Chrome channel is running now."], opener_stopped)

    print(f"{note} Shutting down now.")
    result = subprocess.run(["shutdown", "/s", "/t", str(SHUTDOWN_DELAY_SECONDS)])
    if result.returncode != 0:
        print(f"The shutdown command failed (code {result.returncode}).")
        if opener_stopped:
            print("Chrome_Opener was stopped; start it again with Chrome_Opener.bat.")
        input("\nPress Enter to exit...")
        raise SystemExit(result.returncode)

main()
