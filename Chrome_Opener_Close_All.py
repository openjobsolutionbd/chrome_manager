import ctypes
import time

user32 = ctypes.windll.user32
WM_CLOSE = 0x0010
EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

CONFIRM_ROUNDS = 4        # how many times to retry + confirm any 'Leave site?' prompts
ROUND_WAIT_SECONDS = 2    # how long to wait for windows to close after each round
POLL_INTERVAL = 0.1       # how often to check whether they've closed yet


def chrome_windows():
    found = []
    def cb(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            buf = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, buf, 256)
            if buf.value == "Chrome_WidgetWin_1":
                found.append(hwnd)
        return True
    user32.EnumWindows(EnumWindowsProc(cb), 0)
    return found


print("=" * 64)
print("        CLOSE ALL CHROME PROFILES")
print("=" * 64)

for round_num in range(1, CONFIRM_ROUNDS + 1):
    windows = chrome_windows()
    if not windows:
        break

    print(f"Round {round_num}: closing {len(windows)} window(s)...")
    for hwnd in windows:
        user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)

    deadline = time.time() + ROUND_WAIT_SECONDS
    while time.time() < deadline:
        if not chrome_windows():
            break
        time.sleep(POLL_INTERVAL)

    # Anything still open may be blocked by a "Leave site?" / unsaved-data
    # prompt -- its default button responds to Enter, so bring each such
    # window forward and confirm it before the next round.
    for hwnd in chrome_windows():
        user32.SetForegroundWindow(hwnd)
        time.sleep(0.05)
        user32.keybd_event(0x0D, 0, 0, 0)  # VK_RETURN down
        user32.keybd_event(0x0D, 0, 2, 0)  # VK_RETURN up
        time.sleep(0.1)

remaining = chrome_windows()
print()
if remaining:
    print(f"{len(remaining)} window(s) could not be closed automatically")
    print("(a tab may still be waiting on an unsaved-data prompt).")
else:
    print("All Chrome windows closed. The computer stays on.")

time.sleep(2)  # brief pause so the final message is readable before the window closes
