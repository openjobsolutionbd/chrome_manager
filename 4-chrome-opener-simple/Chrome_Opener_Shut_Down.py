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

SHUTDOWN_TIMEOUT_SECONDS = 60
POLL_INTERVAL_SECONDS = 0.5
WM_CLOSE = 0x0010

user32 = ctypes.windll.user32
EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
user32.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
user32.GetWindowThreadProcessId.restype = ctypes.c_ulong
user32.GetClassNameW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]
user32.GetClassNameW.restype = ctypes.c_int
user32.GetWindowTextW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]
user32.GetWindowTextW.restype = ctypes.c_int

# These are Windows shell/desktop or console-host windows, not user apps.
IGNORED_WINDOW_CLASSES = {
    "Progman",
    "WorkerW",
    "Shell_TrayWnd",
    "Shell_SecondaryTrayWnd",
    "ConsoleWindowClass",
    "CASCADIA_HOSTING_WINDOW_CLASS",
    "tooltips_class32",
    "MSCTFIME UI",
    "IME",
}


def application_windows():
    """Return visible top-level app windows, excluding this script and the shell."""
    found = []
    own_pid = os.getpid()

    def callback(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True

        class_buffer = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, class_buffer, len(class_buffer))
        class_name = class_buffer.value
        if class_name in IGNORED_WINDOW_CLASSES:
            return True

        pid = ctypes.c_ulong(0)
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value or pid.value == own_pid:
            return True

        title_buffer = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(hwnd, title_buffer, len(title_buffer))
        title = title_buffer.value.strip() or "(untitled window)"

        try:
            process = psutil.Process(pid.value)
            process_name = process.name()
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            process_name = "unknown process"

        found.append({
            "hwnd": hwnd,
            "pid": pid.value,
            "title": title,
            "process": process_name,
            "class": class_name,
        })
        return True

    user32.EnumWindows(EnumWindowsProc(callback), 0)
    return found


def close_all_app_windows():
    """Ask every visible app window to close normally; never force-kill apps."""
    windows = application_windows()
    if not windows:
        print("No visible application windows found.")
        return True

    print(f"Sending close requests to {len(windows)} application window(s)...")
    for item in windows:
        user32.PostMessageW(item["hwnd"], WM_CLOSE, 0, 0)
        print(f"  Closing: {item['process']} - {item['title']}")

    deadline = time.time() + SHUTDOWN_TIMEOUT_SECONDS
    last_reminder = 0.0
    while time.time() < deadline:
        remaining = application_windows()
        if not remaining:
            print("All visible application windows are closed.")
            return True

        # Re-send a normal close request every few seconds to windows that remain.
        elapsed = time.time()
        if elapsed - last_reminder >= 5:
            for item in remaining:
                user32.PostMessageW(item["hwnd"], WM_CLOSE, 0, 0)
            last_reminder = elapsed
        time.sleep(POLL_INTERVAL_SECONDS)

    remaining = application_windows()
    if remaining:
        print("\nShutdown cancelled: some applications did not close.")
        print("Close/save the remaining applications manually, then run this file again:")
        for item in remaining[:15]:
            print(f"  {item['process']} - {item['title']}")
        if len(remaining) > 15:
            print(f"  ...and {len(remaining) - 15} more window(s)")
        return False

    return True


if __name__ == "__main__":
    print("=" * 64)
    print("          CLOSE APPS THEN SHUT DOWN WINDOWS")
    print("=" * 64)

    if not close_all_app_windows():
        input("\nPress Enter to exit without shutting down...")
        raise SystemExit(1)

    print("All visible application windows have closed. Shutting down now.")
    subprocess.run(["shutdown", "/s", "/t", "0"], check=False)
