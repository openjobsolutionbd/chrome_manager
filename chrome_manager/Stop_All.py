"""Stop_All -- one click stops everything that Start_All.bat started:
1. Chrome_Opener (and its console window), so nothing reopens the windows;
2. every window of the targeted Google Chrome (politely, like the X button; no keys are sent).
If a window stays open (a "Leave site?" question is waiting), it is reported and left for you."""
import ctypes
import os
import time
from pathlib import Path

try:
    import psutil
except ImportError:
    print("psutil is required. Run: py -m pip install psutil")
    input("\nPress Enter to exit...")
    raise SystemExit(1)

SCRIPT_NAMES = {"chrome_opener.py", "claude_auto_continue.py"}
BAT_NAMES = {"chrome_opener.bat", "claude_auto_continue.bat"}
CLOSE_SECONDS = 15

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

user32 = ctypes.windll.user32
WM_CLOSE = 0x0010
EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
user32.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
user32.GetWindowThreadProcessId.restype = ctypes.c_ulong

def basename(arg):
    return str(arg).replace("\\", "/").rsplit("/", 1)[-1].lower()

def tool_processes():
    me = os.getpid()
    found = []
    for p in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            if p.info.get("pid") == me:
                continue
            name = (p.info.get("name") or "").lower()
            args = [basename(a) for a in (p.info.get("cmdline") or [])]
            is_python = name.startswith("python") or name in ("py.exe", "pyw.exe")
            if is_python and any(a in SCRIPT_NAMES for a in args):
                found.append(p)
            elif name == "cmd.exe" and any(a in BAT_NAMES for a in args):
                found.append(p)
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass
    return found

def stop(procs):
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
    return len(procs)

def is_target_window(hwnd):
    try:
        pid = ctypes.c_ulong(0)
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return bool(pid.value) and is_target_executable(psutil.Process(pid.value).exe())
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess, OSError):
        return False

def chrome_windows():
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

def main():
    print("=" * 60)
    print("   STOP ALL (Chrome Opener + Chrome)")
    print("=" * 60)
    count = stop(tool_processes())
    print(f"Stopped {count} tool process(es)." if count else "The tools were not running.")
    if TARGET_EXE is None:
        print("Google Chrome was not found; no windows were closed.")
        time.sleep(3)
        return
    deadline = time.time() + CLOSE_SECONDS
    while time.time() < deadline:
        windows = chrome_windows()
        if not windows:
            break
        for hwnd in windows:
            user32.PostMessageW(hwnd, 0x0010, 0, 0)   # WM_CLOSE, like the X button
        time.sleep(1)
    remaining = chrome_windows()
    if remaining:
        print(f"{len(remaining)} Chrome window(s) are still open (a question like 'Leave site?' may be waiting). Close them yourself.")
        input("\nPress Enter to close...")
    else:
        print("All Chrome windows closed. Done.")
        time.sleep(2)

if __name__ == "__main__":
    main()
