const BASE = "http://127.0.0.1:8765";

async function call(path) {
  try {
    const r = await fetch(BASE + path);
    return (await r.text()).trim();
  } catch (e) {
    return ""; // Python not running: ignore
  }
}

// close every window of this profile = this profile's Chrome closes
async function closeAll() {
  const wins = await chrome.windows.getAll();
  wins.forEach((w) => chrome.windows.remove(w.id).catch(() => {}));
}

const q = (s) => encodeURIComponent(s || "");

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  const winId = sender.tab && sender.tab.windowId;

  // all waiting happens here: timers of covered/hidden Chrome windows get slowed down
  if (msg.type === "sleep") {
    setTimeout(() => sendResponse(true), msg.ms);
    return true;
  }
  if (msg.type === "maximize" && winId != null) {
    chrome.windows.update(winId, { state: "maximized" }).catch(() => {});
    return;
  }
  if (msg.type === "log") {
    call(`/log?profile=${q(msg.profile)}&msg=${q(msg.msg)}`);
    return;
  }
  if (msg.type === "limit") {
    (msg.profile
      ? call(`/limit?profile=${q(msg.profile)}&line=${q(msg.line)}`)
      : Promise.resolve()
    ).finally(closeAll);
    return;
  }
  if (msg.type === "ping") {
    call(`/ping?profile=${q(msg.profile)}&done=${msg.done ? 1 : 0}`).then((t) => {
      if (t === "close") closeAll();
    });
    return;
  }
  if (msg.type === "shouldScan" && winId != null) {
    chrome.storage.session.get("scanned").then((d) => {
      const scanned = d.scanned || {};
      if (scanned[winId]) return sendResponse(false);
      scanned[winId] = true;
      chrome.storage.session.set({ scanned }).then(() => sendResponse(true));
    });
    return true; // async answer
  }
});
