import ctypes
import subprocess
import time

user32 = ctypes.windll.user32
WM_CLOSE = 0x0010

EnumWindows = user32.EnumWindows
EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
GetClassNameW = user32.GetClassNameW
IsWindowVisible = user32.IsWindowVisible
PostMessageW = user32.PostMessageW

CLOSE_TIMEOUT_SECONDS = 30      # keep asking Chrome windows to close for this long
SHUTDOWN_DELAY_SECONDS = 0      # shut down immediately once Chrome is closed


def chrome_windows():
    found = []

    def callback(hwnd, _lparam):
        if IsWindowVisible(hwnd):
            buf = ctypes.create_unicode_buffer(256)
            GetClassNameW(hwnd, buf, 256)
            if buf.value == "Chrome_WidgetWin_1":
                found.append(hwnd)
        return True

    EnumWindows(EnumWindowsProc(callback), 0)
    return found


def chrome_running():
    result = subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq chrome.exe"],
        capture_output=True,
        text=True,
        creationflags=subprocess.CREATE_NO_WINDOW
    )
    return "chrome.exe" in result.stdout.lower()


# Repeatedly ask Chrome windows to close (like clicking the X button).
# Re-enumerating each loop catches windows/dialogs that appear *after* the
# first pass, e.g. "leave site?" or unsaved-data prompts.
started = time.time()
while chrome_running() and (time.time() - started) < CLOSE_TIMEOUT_SECONDS:
    for hwnd in chrome_windows():
        PostMessageW(hwnd, WM_CLOSE, 0, 0)

# Never shut down while Chrome is still open -- a blocking dialog may be
# waiting for a response, and forcing it closed risks losing session/tab data.
if chrome_running():
    print("Chrome did not close within the timeout (a dialog may be waiting")
    print("for a response, e.g. 'leave site?' or an unsaved-data prompt).")
    print("Shutdown was cancelled so nothing gets lost.")
    print("Close Chrome manually and re-run this script.")
    input("\nPress Enter to exit...")
    raise SystemExit(1)

print("Chrome closed. Shutting down now.")
subprocess.run(["shutdown", "/s", "/t", str(SHUTDOWN_DELAY_SECONDS)])
