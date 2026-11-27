# launcher.py (v1.2.1)  -  opens Chrome profiles in batches of 10.
# The extension (claude_limit_closer) does the clicking and closes Chrome when
# the limit message shows. This script opens profiles, keeps time, writes ONE
# log file, and opens the next batch when the current batch is finished.
import os, sys, json, time, subprocess, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, quote

# ---------------- settings ----------------
BATCH_SIZE = 10            # profiles opened together
WAIT_AFTER_CLICKS = 10     # all chats / Continue clicks finished -> wait 10 seconds -> close
LAUNCH_GAP = 4             # seconds between opening two profiles
NO_EXTENSION_SECONDS = 120 # profile never answered = extension missing
PROFILE_MAX_SECONDS = 15 * 60
BATCH_MAX_SECONDS = 25 * 60
PORT = 8765
URL = "https://claude.ai/new"
PROFILES = []              # empty = all profiles found in Chrome; or e.g. ["Default", "Profile 1"]
LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "launcher.log")
# ------------------------------------------

state = {}
lock = threading.Lock()


def log(p, msg):
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} [{p or '-'}] {msg}"
    print(line)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        p = (q.get("profile") or [""])[0]
        reply = "wait"
        with lock:
            s = state.get(p)
            if u.path == "/log":
                log(p, (q.get("msg") or [""])[0])
                reply = "ok"
            elif s and not s["finished"]:
                if u.path == "/limit":
                    s["finished"] = True
                    s["result"] = "limit"
                    log(p, "LIMIT reached, Chrome closed itself. Text seen: " + (q.get("line") or [""])[0])
                    reply = "ok"
                elif u.path == "/ping":
                    now = time.time()
                    if s["hello"] is None:
                        s["hello"] = now
                        log(p, "page loaded")
                    done = (q.get("done") or ["0"])[0] == "1"
                    if done and s.get("done_at") is None:
                        s["done_at"] = now
                    if (s.get("done_at") and now - s["done_at"] >= WAIT_AFTER_CLICKS) or now - s["hello"] >= PROFILE_MAX_SECONDS:
                        s["finished"] = True
                        s["result"] = "closed"
                        log(p, "no limit -> closing")
                        reply = "close"
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(reply.encode())


def find_chrome():
    for base in (os.environ.get("PROGRAMFILES"), os.environ.get("PROGRAMFILES(X86)"), os.environ.get("LOCALAPPDATA")):
        if base:
            path = os.path.join(base, "Google", "Chrome", "Application", "chrome.exe")
            if os.path.exists(path):
                return path
    sys.exit("chrome.exe not found")


def find_profiles():
    if PROFILES:
        return PROFILES
    ls = os.path.join(os.environ["LOCALAPPDATA"], "Google", "Chrome", "User Data", "Local State")
    with open(ls, encoding="utf-8") as f:
        names = list(json.load(f)["profile"]["info_cache"].keys())
    names.sort(key=lambda n: (n != "Default", int(n.split()[-1]) if n.split()[-1].isdigit() else 0))
    return names


OLD_EXT = "Claude Background Continue"  # old extension: opens extra tabs, must be removed
NEW_EXT = "Claude Limit Closer"


def chrome_data_dir():
    return os.path.join(os.environ["LOCALAPPDATA"], "Google", "Chrome", "User Data")


def profile_display_names():
    try:
        with open(os.path.join(chrome_data_dir(), "Local State"), encoding="utf-8") as f:
            cache = json.load(f)["profile"]["info_cache"]
        return {k: v.get("name", k) for k, v in cache.items()}
    except Exception:
        return {}


def enabled_extension_names(profile):
    """Names of the extensions switched on in this profile (None = could not read)."""
    names, read_ok = set(), False
    for fn in ("Secure Preferences", "Preferences"):
        try:
            with open(os.path.join(chrome_data_dir(), profile, fn), encoding="utf-8") as f:
                data = json.load(f)
            read_ok = True
            for ext in (data.get("extensions", {}).get("settings", {}) or {}).values():
                name = (ext.get("manifest") or {}).get("name")
                if name and ext.get("state", 1) != 0 and not ext.get("disable_reasons"):
                    names.add(name)
        except Exception:
            pass
    return names if read_ok else None


def check_extensions(profiles):
    """Tell the owner which profiles still have the old extension, or miss the new one."""
    display = profile_display_names()
    old, missing, unknown = [], [], []
    for p in profiles:
        names = enabled_extension_names(p)
        label = f"{p} ({display.get(p, p)})"
        if names is None:
            unknown.append(label)
            continue
        if OLD_EXT in names:
            old.append(label)
        if NEW_EXT not in names:
            missing.append(label)
    if old:
        log("", f"PROBLEM: old extension '{OLD_EXT}' is still ON in: {', '.join(old)}  -> remove it (it opens extra tabs)")
    if missing:
        log("", f"PROBLEM: '{NEW_EXT}' is NOT installed in: {', '.join(missing)}  -> install it")
    if unknown:
        log("", f"could not check extensions in: {', '.join(unknown)}")
    if not (old or missing):
        log("", "extension check OK")
    return bool(old or missing)


def launch(chrome, p):
    subprocess.Popen([
        chrome,
        f"--profile-directory={p}",
        "--start-maximized",
        "--new-window",
        f"{URL}#cm={quote(p)}",
    ])


def main():
    try:
        server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    except OSError:
        sys.exit(f"Port {PORT} is busy. Close the other launcher window first.")
    threading.Thread(target=server.serve_forever, daemon=True).start()

    chrome = find_chrome()
    remaining = find_profiles()
    log("", f"===== START: {len(remaining)} profiles, batch size {BATCH_SIZE} =====")
    if check_extensions(remaining):
        log("", "starting in 30 seconds anyway; close this window now if you want to fix the profiles above first")
        time.sleep(30)
    results = {}
    n = 0
    while remaining:
        batch, remaining = remaining[:BATCH_SIZE], remaining[BATCH_SIZE:]
        n += 1
        log("", f"--- batch {n}: {', '.join(batch)}")
        with lock:
            for p in batch:
                state[p] = {"hello": None, "finished": False, "result": None}
        t0 = time.time()
        for p in batch:
            launch(chrome, p)
            state[p]["launched"] = time.time()
            time.sleep(LAUNCH_GAP)
        while True:
            time.sleep(2)
            now = time.time()
            with lock:
                for p in batch:
                    s = state[p]
                    if not s["finished"] and s["hello"] is None and now - s["launched"] > NO_EXTENSION_SECONDS:
                        s["finished"] = True
                        s["result"] = "no extension"
                        log(p, "extension did not answer - is it installed in this profile?")
                all_done = all(state[p]["finished"] for p in batch)
            if all_done or now - t0 > BATCH_MAX_SECONDS:
                break
        for p in batch:
            results[p] = state[p]["result"] or "timeout"
        time.sleep(5)
    summary = {}
    for r in results.values():
        summary[r] = summary.get(r, 0) + 1
    log("", f"===== FINISHED: {summary} =====")


if __name__ == "__main__":
    main()
