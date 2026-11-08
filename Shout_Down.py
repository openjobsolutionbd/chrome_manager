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
EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
user32.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
user32.GetWindowThreadProcessId.restype = ctypes.c_ulong
CLOSE_TIMEOUT_SECONDS = 30
SHUTDOWN_DELAY_SECONDS = 0

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

def target_browser_running():
    for p in psutil.process_iter(["name", "exe"]):
        try:
            if (p.info.get("name") or "").lower() == "chrome.exe" and is_target_executable(p.info.get("exe")):
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass
    return False

def any_chrome_running():
    # Shutdown affects every application, so protect unsaved work in either Chrome channel.
    for p in psutil.process_iter(["name"]):
        try:
            if (p.info.get("name") or "").lower() == "chrome.exe":
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass
    return False

started = time.time()
while target_browser_running() and (time.time() - started) < CLOSE_TIMEOUT_SECONDS:
    for hwnd in target_windows():
        user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
    time.sleep(0.25)

if target_browser_running():
    print(f"{BROWSER_LABEL} did not close within the timeout (a dialog may be waiting).")
    print("Shutdown was cancelled so nothing gets lost.")
    input("\nPress Enter to exit...")
    raise SystemExit(1)

if any_chrome_running():
    print(f"{BROWSER_LABEL} is closed, but another Chrome channel is still running.")
    print("Shutdown was cancelled to protect the other browser's tabs and unsaved work.")
    input("\nPress Enter to exit...")
    raise SystemExit(1)

print(f"{BROWSER_LABEL} is closed and no Chrome processes remain. Shutting down now.")
subprocess.run(["shutdown", "/s", "/t", str(SHUTDOWN_DELAY_SECONDS)])
