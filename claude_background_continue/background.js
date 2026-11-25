// Claude Background Continue v2.0.0
//
// ONE job: open every chat of the Claude sidebar once. If the chat shows a usage-limit notice
// with a "Continue" or "Try again" button, click it. Nothing else.
//
// All waiting is done here, in the service worker, and every page check is one short
// synchronous call into content.js. A page in a minimized or background window is "hidden"
// and Chrome slows its timers (one tick a second, later one a minute), but this worker's
// timers are not slowed, so a scan takes the same time with the window minimized or not.

const CLAUDE_PREFIX = "https://claude.ai/";
const NEW_CHAT_URL = "https://claude.ai/new";
const PAGE_API_VERSION = "2.0.0";   // must match VERSION in content.js

const BATCH_KEY = "batchScan";
const GUARD_KEY = "reloadGuard";
const LOG_KEY = "log";
const RELOAD_GUARD_MS = 60 * 1000;    // our own reload at the end of a scan must not start another scan
const STALE_BATCH_MS = 2 * 60 * 1000; // a scan with no progress for this long is dead (the worker was stopped)

const POLL_MS = 400;
const SIDEBAR_WAIT_MS = 12000;        // wait this long for the sidebar to list its chats
const SIDEBAR_STABLE_POLLS = 3;       // ...and until the list has stopped growing for this many checks
const SCROLL_ROUNDS = 12;
const CHAT_MAX_WAIT_MS = 15000;       // longest we wait for one chat to load and settle
const CHAT_MIN_WAIT_MS = 1500;
const CHAT_STABLE_POLLS = 3;          // page unchanged for this many checks = loaded
const BEFORE_CLICK_MS = 450;          // look at the button once more before clicking
const AFTER_CLICK_MS = 2500;          // stay on the chat a moment so the click goes through

class ScanCancelled extends Error {}

function isClaudeUrl(url) {
  return typeof url === "string" && url.startsWith(CLAUDE_PREFIX);
}

function delay(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

function sameChat(a, b) {
  try {
    return new URL(a).pathname === new URL(b).pathname;
  } catch (_) {
    return false;
  }
}

// ---------- stored state ----------

async function getBatch() {
  const data = await chrome.storage.local.get({ [BATCH_KEY]: null });
  return data[BATCH_KEY];
}

// Saves progress, but never brings back a scan that Stop (or a newer scan) already replaced.
async function saveProgress(batch) {
  const current = await getBatch();
  if (!current || current.jobId !== batch.jobId) throw new ScanCancelled();
  batch.updatedAt = Date.now();
  await chrome.storage.local.set({ [BATCH_KEY]: batch });
}

async function appendLog(status, detail, url = "", button = "") {
  try {
    const data = await chrome.storage.local.get({ [LOG_KEY]: [] });
    const previous = Array.isArray(data[LOG_KEY]) ? data[LOG_KEY] : [];
    const entry = {
      time: new Date().toLocaleString(),
      status: String(status || ""),
      detail: String(detail || ""),
      button: String(button || ""),
      url: String(url || "")
    };
    const last = previous[previous.length - 1];
    if (last && last.status === entry.status && last.detail === entry.detail &&
        last.url === entry.url && last.button === entry.button) return;
    await chrome.storage.local.set({ [LOG_KEY]: [...previous, entry].slice(-300) });
  } catch (_) {
    // Logging must never interrupt a scan.
  }
}

async function readGuard() {
  const data = await chrome.storage.local.get({ [GUARD_KEY]: {} });
  return data[GUARD_KEY] && typeof data[GUARD_KEY] === "object" ? data[GUARD_KEY] : {};
}

async function setReloadGuard(tabId) {
  const guard = await readGuard();
  const now = Date.now();
  for (const key of Object.keys(guard)) {
    if (now - guard[key] > RELOAD_GUARD_MS * 5) delete guard[key];
  }
  guard[tabId] = now;
  await chrome.storage.local.set({ [GUARD_KEY]: guard });
}

async function inReloadGuard(tabId) {
  const guard = await readGuard();
  return Boolean(guard[tabId]) && Date.now() - guard[tabId] < RELOAD_GUARD_MS;
}

async function closeTab(tabId) {
  if (!Number.isInteger(tabId)) return;
  try { await chrome.tabs.remove(tabId); } catch (_) {}
}

// ---------- talking to the page ----------

// Calls one function of content.js in the tab. Returns undefined when the tab cannot be
// reached (still navigating, closed, no access), so callers simply try again on the next poll.
async function callPage(tabId, name, ...args) {
  const run = () => chrome.scripting.executeScript({
    target: { tabId },
    func: (fn, fnArgs, version) => {
      const api = globalThis.__cbc;
      if (!api || api.version !== version || typeof api[fn] !== "function") return { __missing: true };
      return api[fn](...fnArgs);
    },
    args: [name, args, PAGE_API_VERSION]
  });
  try {
    let result = await run();
    let value = result && result[0] ? result[0].result : undefined;
    if (value && value.__missing) {
      await chrome.scripting.executeScript({ target: { tabId }, files: ["content.js"] });
      result = await run();
      value = result && result[0] ? result[0].result : undefined;
      if (value && value.__missing) return undefined;
    }
    return value;
  } catch (_) {
    return undefined;
  }
}

// ---------- the scan ----------

async function collectSidebarLinks(batch) {
  const tabId = batch.scannerTabId;
  const found = [];
  const known = new Set();
  const add = list => {
    for (const url of Array.isArray(list) ? list : []) {
      if (isClaudeUrl(url) && !known.has(url)) {
        known.add(url);
        found.push(url);
      }
    }
  };

  // Wait until the sidebar has listed its chats and the list has stopped growing.
  const deadline = Date.now() + SIDEBAR_WAIT_MS;
  let lastCount = -1;
  let stable = 0;
  while (Date.now() < deadline) {
    await delay(POLL_MS);
    const snap = await callPage(tabId, "snapshot");
    if (!snap || snap.readyState !== "complete" || !isClaudeUrl(snap.url)) continue;
    batch.pageState = { visibility: snap.visibility, width: snap.width, height: snap.height };
    add(await callPage(tabId, "collectLinks"));
    stable = found.length > 0 && found.length === lastCount ? stable + 1 : 0;
    lastCount = found.length;
    if (found.length > 0 && stable >= SIDEBAR_STABLE_POLLS) break;
  }

  // "View all", then scroll the sidebar down to load older chats.
  if (await callPage(tabId, "expandSidebar")) {
    await delay(900);
    add(await callPage(tabId, "collectLinks"));
  }
  if (found.length > 0) {
    for (let round = 0; round < SCROLL_ROUNDS; round += 1) {
      const scrolled = await callPage(tabId, "scrollSidebar");
      if (!scrolled || !scrolled.moved) break;
      await delay(250);
      add(await callPage(tabId, "collectLinks"));
      if (scrolled.atBottom) break;
    }
  }
  return found;
}

// Opens one chat in the scanner tab, waits until it has loaded and stopped changing, and
// clicks "Continue" / "Try again" if the chat has one beside a usage-limit notice.
async function checkOneChat(batch, url) {
  const tabId = batch.scannerTabId;
  await chrome.tabs.update(tabId, { url });

  const startedAt = Date.now();
  let lastSignature = "";
  let stable = 0;
  let loaded = false;
  let last = null;
  let withAction = null;
  while (Date.now() - startedAt < CHAT_MAX_WAIT_MS) {
    await delay(POLL_MS);
    const snap = await callPage(tabId, "snapshot");
    // Still showing the previous page, or still loading: keep waiting.
    if (!snap || snap.readyState !== "complete" || !sameChat(snap.url, url)) {
      stable = 0;
      lastSignature = "";
      continue;
    }
    loaded = true;
    last = snap;
    if (snap.action) {
      withAction = snap;
      break;
    }
    const signature = `${snap.textLength}|${snap.limitNotice}`;
    stable = signature === lastSignature ? stable + 1 : 0;
    lastSignature = signature;
    if (stable >= CHAT_STABLE_POLLS && Date.now() - startedAt >= CHAT_MIN_WAIT_MS) break;
  }

  if (!withAction) return { found: false, loaded, notice: Boolean(last && last.limitNotice) };

  await delay(BEFORE_CLICK_MS);
  const clicked = await callPage(tabId, "clickAction", withAction.action.name);
  if (clicked && clicked.clicked) await delay(AFTER_CLICK_MS);
  return {
    found: true,
    loaded: true,
    name: withAction.action.name,
    clicked: Boolean(clicked && clicked.clicked),
    reason: clicked && clicked.reason ? clicked.reason : ""
  };
}

async function endScan(batch, status, message, reloadIfClicked) {
  const current = await getBatch();
  if (!current || current.jobId !== batch.jobId) return; // stopped, or replaced by a newer scan
  await chrome.storage.local.set({ [BATCH_KEY]: null });
  await appendLog(status, message, batch.sourceUrl || "");
  await closeTab(batch.scannerTabId);
  if (reloadIfClicked && batch.clickedAny && Number.isInteger(batch.sourceTabId)) {
    await setReloadGuard(batch.sourceTabId);
    try { await chrome.tabs.reload(batch.sourceTabId); } catch (_) {}
  }
}

async function runScan(batch) {
  const keepAlive = setInterval(() => chrome.runtime.getPlatformInfo(() => void chrome.runtime.lastError), 20000);
  try {
    const urls = await collectSidebarLinks(batch);
    if (!urls.length) {
      await endScan(batch, "Sidebar scan could not find chats",
        "No chat links were found in the sidebar. Is this profile signed in to Claude, and does the extension have site access?", false);
      return;
    }
    const page = batch.pageState
      ? ` (scanner page: ${batch.pageState.visibility}, ${batch.pageState.width}x${batch.pageState.height})`
      : "";
    batch.queue = urls;
    batch.index = 0;
    batch.phase = "chats";
    await saveProgress(batch);
    await appendLog("Sidebar chats found", `Found ${urls.length} chat link(s). Checking each one once.${page}`, batch.sourceUrl || "");

    for (let i = 0; i < urls.length; i += 1) {
      batch.index = i;
      await saveProgress(batch);
      const number = i + 1;
      const result = await checkOneChat(batch, urls[i]);
      if (result.found && result.clicked) {
        batch.clickedAny = true;
        await appendLog(`Chat ${number}/${urls.length}: ${result.name} clicked`,
          `Clicked "${result.name}" beside the usage-limit notice.`, urls[i], result.name);
      } else if (result.found) {
        await appendLog(`Chat ${number}/${urls.length}: ${result.name} found, not clicked`,
          `Not clicked: ${result.reason || "unknown reason"}.`, urls[i], result.name);
      } else if (!result.loaded) {
        await appendLog(`Chat ${number}/${urls.length}: did not load`,
          `The chat did not finish loading within ${CHAT_MAX_WAIT_MS / 1000} seconds.`, urls[i]);
      } else if (result.notice) {
        await appendLog(`Chat ${number}/${urls.length}: notice without button`,
          "A usage-limit notice is visible, but it has no Continue or Try again button.", urls[i]);
      } else {
        await appendLog(`Chat ${number}/${urls.length}: nothing to do`,
          "No Continue or Try again button beside a usage-limit notice.", urls[i]);
      }
    }
    await endScan(batch, "Sidebar scan complete", `Checked ${urls.length} sidebar chat(s), each once.`, true);
  } catch (error) {
    if (error instanceof ScanCancelled) return; // Stop was pressed; Stop already cleaned up
    await endScan(batch, "Sidebar scan error", `The scan stopped because of an error: ${error?.message || String(error)}`, false);
  } finally {
    clearInterval(keepAlive);
  }
}

// ---------- starting and stopping ----------

let starting = false;

async function clearIfStale() {
  const batch = await getBatch();
  if (!batch) return;
  if (Date.now() - (batch.updatedAt || batch.startedAt || 0) < STALE_BATCH_MS) return;
  await chrome.storage.local.set({ [BATCH_KEY]: null });
  await closeTab(batch.scannerTabId);
  await appendLog("Old sidebar scan cleared", "A scan that made no progress for 2 minutes was removed so a new one can start.", batch.sourceUrl || "");
}

async function startScan(sourceTab) {
  if (starting) return { ok: false, error: "A sidebar scan is already starting." };
  starting = true;
  try {
    await clearIfStale();
    const running = await getBatch();
    if (running) return { ok: false, error: "A sidebar scan is already running. Stop it before starting another." };
    if (!sourceTab || !Number.isInteger(sourceTab.id) || !isClaudeUrl(sourceTab.url)) {
      return { ok: false, error: "Open a Claude tab first, then start the sidebar scan." };
    }

    let windowState = "unknown";
    try { windowState = (await chrome.windows.get(sourceTab.windowId)).state || "unknown"; } catch (_) {}

    // A separate inactive tab in the same window, so the user's own chat is never navigated.
    const scannerTab = await chrome.tabs.create({ url: NEW_CHAT_URL, active: false, windowId: sourceTab.windowId });
    const batch = {
      scannerTabId: scannerTab.id,
      sourceTabId: sourceTab.id,
      sourceUrl: sourceTab.url,
      phase: "collect",
      queue: [],
      index: 0,
      clickedAny: false,
      startedAt: Date.now(),
      updatedAt: Date.now(),
      jobId: `${Date.now()}-${scannerTab.id}`
    };
    await chrome.storage.local.set({ [BATCH_KEY]: batch });
    await appendLog("Sidebar scan started",
      `Window state: ${windowState}. Opened a background tab and collecting the sidebar's chat links.`, sourceTab.url);
    void runScan(batch);
    return { ok: true, message: "Sidebar scan started in a separate background tab." };
  } catch (error) {
    return { ok: false, error: error?.message || String(error) };
  } finally {
    starting = false;
  }
}

async function stopScan() {
  const batch = await getBatch();
  if (!batch) return { ok: true, message: "No sidebar scan is running." };
  await chrome.storage.local.set({ [BATCH_KEY]: null });
  await closeTab(batch.scannerTabId);
  await appendLog("Sidebar scan stopped", "The sidebar scan was stopped by the user.", batch.sourceUrl || "");
  return { ok: true, message: "Sidebar scan stopped." };
}

async function maybeAutoStart(tab) {
  if (!tab || !Number.isInteger(tab.id) || !tab.active || !isClaudeUrl(tab.url)) return;
  if (await inReloadGuard(tab.id)) return;
  const running = await getBatch();
  if (running && running.scannerTabId === tab.id) return;
  await startScan(tab);
}

async function autoStartOnActiveTab() {
  try {
    const tabs = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
    if (tabs && tabs[0]) await maybeAutoStart(tabs[0]);
  } catch (_) {
    // The browser may not be ready yet; the tab events below start the scan later.
  }
}

// ---------- when a scan starts by itself ----------
// When a Claude tab finishes loading in front, or is switched to. Not on a timer.

chrome.runtime.onStartup.addListener(async () => {
  await chrome.storage.local.set({ [BATCH_KEY]: null }); // no scan can survive a browser restart
  void autoStartOnActiveTab();
});

chrome.runtime.onInstalled.addListener(() => {
  void autoStartOnActiveTab();
});

chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  if (changeInfo.status === "complete" && tab && tab.active) void maybeAutoStart(tab);
});

chrome.tabs.onActivated.addListener(({ tabId }) => {
  chrome.tabs.get(tabId, tab => {
    if (chrome.runtime.lastError) return;
    void maybeAutoStart(tab);
  });
});

chrome.tabs.onRemoved.addListener(async tabId => {
  const batch = await getBatch();
  if (batch && batch.scannerTabId === tabId) {
    await chrome.storage.local.set({ [BATCH_KEY]: null });
    await appendLog("Sidebar scan interrupted", "The background scan tab was closed before the scan finished.", batch.sourceUrl || "");
  }
});

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (!message || typeof message.type !== "string") return;

  if (message.type === "startBatchScan") {
    chrome.tabs.query({ active: true, lastFocusedWindow: true })
      .then(tabs => startScan(tabs && tabs[0]))
      .then(sendResponse)
      .catch(error => sendResponse({ ok: false, error: error?.message || String(error) }));
    return true;
  }

  if (message.type === "stopBatchScan") {
    stopScan().then(sendResponse).catch(error => sendResponse({ ok: false, error: error?.message || String(error) }));
    return true;
  }
});
