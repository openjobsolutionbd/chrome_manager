import ctypes
import time
import os
from pathlib import Path

try:
    import psutil
except ImportError:
    print("psutil is required. Run: py -m pip install psutil")
    input("\nPress Enter to exit...")
    raise SystemExit(1)

BROWSER_LABEL = "Google Chrome"
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
    print(f"{BROWSER_LABEL} executable was not found; no windows were closed.")
    input("\nPress Enter to exit...")
    raise SystemExit(1)

user32 = ctypes.windll.user32
WM_CLOSE = 0x0010
EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
user32.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
user32.GetWindowThreadProcessId.restype = ctypes.c_ulong

CONFIRM_ROUNDS = 4
ROUND_WAIT_SECONDS = 2
POLL_INTERVAL = 0.1

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

print("=" * 64)
print(f"        CLOSE ALL {BROWSER_LABEL.upper()} PROFILES")
print("=" * 64)

for round_num in range(1, CONFIRM_ROUNDS + 1):
    windows = chrome_windows()
    if not windows:
        break
    print(f"Round {round_num}: closing {len(windows)} target-browser window(s)...")
    for hwnd in windows:
        user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
    deadline = time.time() + ROUND_WAIT_SECONDS
    while time.time() < deadline:
        if not chrome_windows():
            break
        time.sleep(POLL_INTERVAL)
    for hwnd in chrome_windows():
        user32.SetForegroundWindow(hwnd)
        time.sleep(0.05)
        user32.keybd_event(0x0D, 0, 0, 0)
        user32.keybd_event(0x0D, 0, 2, 0)
        time.sleep(0.1)

remaining = chrome_windows()
print()
if remaining:
    print(f"{len(remaining)} {BROWSER_LABEL} window(s) could not be closed automatically.")
    print("A tab may be waiting on an unsaved-data prompt.")
else:
    print(f"All {BROWSER_LABEL} windows closed. Other Chrome channels are left untouched.")
time.sleep(2)
