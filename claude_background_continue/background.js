// Claude Background Continue v1.5.0
// Adds a sequential scan of chat links found in Claude's sidebar.

const CLAUDE_URL_PATTERN = "https://claude.ai/*";
const CLAUDE_URL_PREFIX = "https://claude.ai/";
const BATCH_KEY = "batchScan";
const justReloadedTabs = new Map(); // tabId -> time of the reload this extension made
const processingTabs = new Set();
const autoStartingTabs = new Set();

function isClaudeUrl(url) {
  return typeof url === "string" && url.startsWith(CLAUDE_URL_PREFIX);
}

function delay(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

async function injectScanner(tabId) {
  if (!Number.isInteger(tabId)) return;
  try {
    await chrome.scripting.executeScript({
      target: { tabId },
      files: ["content.js"]
    });
  } catch (_) {
    // Tab may be closing or site access may not be granted.
  }
}

async function injectIntoOpenClaudeTabs() {
  try {
    const tabs = await chrome.tabs.query({ url: [CLAUDE_URL_PATTERN] });
    for (const tab of tabs) {
      if (Number.isInteger(tab.id)) void injectScanner(tab.id);
    }
  } catch (_) {
    // Ignore startup races; tab listeners will retry.
  }
}

async function getBatch() {
  const data = await chrome.storage.local.get({ [BATCH_KEY]: null });
  return data[BATCH_KEY];
}

async function setBatch(batch) {
  await chrome.storage.local.set({ [BATCH_KEY]: batch });
}

async function appendLog(status, detail, url = "", button = "") {
  try {
    const data = await chrome.storage.local.get({ log: [] });
    const previous = Array.isArray(data.log) ? data.log : [];
    const entry = {
      time: new Date().toLocaleString(),
      status: String(status || ""),
      detail: String(detail || ""),
      button: String(button || ""),
      url: String(url || "")
    };
    const last = previous[previous.length - 1];
    if (
      last && last.status === entry.status && last.detail === entry.detail &&
      last.url === entry.url && last.button === entry.button
    ) return;
    await chrome.storage.local.set({ log: [...previous, entry].slice(-300) });
  } catch (_) {
    // Logging must not interrupt scanning.
  }
}

async function startBatchScanForTab(sourceTab) {
  const running = await getBatch();
  if (running && running.scannerTabId) {
    return { ok: false, error: "A sidebar scan is already running. Stop it before starting another." };
  }
  if (!sourceTab || !Number.isInteger(sourceTab.id) || !isClaudeUrl(sourceTab.url)) {
    return { ok: false, error: "Open a Claude tab first, then start the sidebar scan." };
  }

  // Use a separate inactive tab so the user's current chat remains untouched.
  const scannerTab = await chrome.tabs.create({ url: "about:blank", active: false });
  const batch = {
    scannerTabId: scannerTab.id,
    sourceTabId: sourceTab.id,
    sourceUrl: sourceTab.url,
    phase: "collect",
    queue: [],
    index: 0,
    startedAt: Date.now(),
    jobId: `${Date.now()}-${scannerTab.id}`
  };
  await setBatch(batch);
  await appendLog("Sidebar scan started", "Opening a separate background tab at Claude New Chat and collecting chat links from the sidebar. The original chat tab will not be navigated.", sourceTab.url);
  await chrome.tabs.update(scannerTab.id, { url: "https://claude.ai/new" });
  return { ok: true, message: "Sidebar scan started in a separate background tab." };
}

async function startBatchScan() {
  const tabs = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
  return startBatchScanForTab(tabs && tabs[0]);
}

async function maybeAutoStartForTab(tab) {
  if (!tab || !Number.isInteger(tab.id) || !tab.active || !isClaudeUrl(tab.url)) return;
  // The reload we make at the end of a scan must not start another scan.
  const reloadedAt = justReloadedTabs.get(tab.id);
  if (reloadedAt && Date.now() - reloadedAt < 60 * 1000) return;
  if (autoStartingTabs.has(tab.id)) return;
  autoStartingTabs.add(tab.id);
  try {
    const currentBatch = await getBatch();
    if (currentBatch && currentBatch.scannerTabId) return;
    await startBatchScanForTab(tab);
  } finally {
    autoStartingTabs.delete(tab.id);
  }
}

async function autoStartOnCurrentClaudeTab() {
  try {
    const tabs = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
    if (tabs && tabs[0]) await maybeAutoStartForTab(tabs[0]);
  } catch (_) {
    // Startup may happen before the active tab is ready.
  }
}

async function stopBatchScan() {
  const batch = await getBatch();
  if (!batch) return { ok: true, message: "No sidebar scan is running." };
  await chrome.storage.local.set({ [BATCH_KEY]: null });
  if (Number.isInteger(batch.scannerTabId)) {
    try { await chrome.tabs.remove(batch.scannerTabId); } catch (_) {}
  }
  await appendLog("Sidebar scan stopped", "The sidebar scan was stopped by the user.", batch.sourceUrl || "");
  return { ok: true, message: "Sidebar scan stopped." };
}

async function finishBatch(message, status = "Sidebar scan complete") {
  const batch = await getBatch();
  if (!batch) return;
  await chrome.storage.local.set({ [BATCH_KEY]: null });
  await appendLog(status, message, batch.sourceUrl || "");
  if (Number.isInteger(batch.scannerTabId)) {
    try { await chrome.tabs.remove(batch.scannerTabId); } catch (_) {}
  }
  if (status === "Sidebar scan complete" && batch.clickedAny && Number.isInteger(batch.sourceTabId)) {
    justReloadedTabs.set(batch.sourceTabId, Date.now());
    try { await chrome.tabs.reload(batch.sourceTabId); } catch (_) {}
  }
}

async function goToCurrentQueueItem(batch) {
  if (!batch.queue || batch.index >= batch.queue.length) {
    await finishBatch(`Checked ${batch.queue?.length || 0} sidebar chat(s).`);
    return;
  }

  batch.phase = "navigate";
  await setBatch(batch);
  const nextUrl = batch.queue[batch.index];
  try {
    const tab = await chrome.tabs.get(batch.scannerTabId);
    if (tab.url === nextUrl) {
      await chrome.tabs.reload(batch.scannerTabId);
    } else {
      await chrome.tabs.update(batch.scannerTabId, { url: nextUrl });
    }
  } catch (error) {
    await finishBatch(`Could not open chat ${batch.index + 1}: ${error?.message || String(error)}`, "Sidebar scan error");
  }
}

async function handleSidebarLinks(tabId, response) {
  const batch = await getBatch();
  if (!batch || batch.scannerTabId !== tabId) return;

  const urls = Array.isArray(response?.chatUrls)
    ? [...new Set(response.chatUrls.filter(isClaudeUrl))]
    : [];

  if (!urls.length) {
    await finishBatch(
      "No chat links were found in the sidebar. Make sure the Claude sidebar is expanded and the extension has site access.",
      "Sidebar scan could not find chats"
    );
    return;
  }

  batch.queue = urls;
  batch.index = 0;
  batch.phase = "navigate";
  await setBatch(batch);
  await appendLog("Sidebar chats found", `Found ${urls.length} chat link(s). Checking them one by one.`, batch.sourceUrl || "");
  await goToCurrentQueueItem(batch);
}

async function handleChatResult(tabId, response) {
  const batch = await getBatch();
  if (!batch || batch.scannerTabId !== tabId) return;

  const currentUrl = batch.queue?.[batch.index] || "";
  const result = response || {};
  const number = batch.index + 1;
  const total = batch.queue.length;

  if (result.found) {
    const clickText = result.clicked ? "Click attempted." : "No click was made.";
    await appendLog(
      `Chat ${number}/${total}: ${result.buttonName || "Continue/Try again"} found`,
      `${clickText} ${result.detail || "A usage-limit action was detected in this chat."}`,
      currentUrl,
      result.buttonName || ""
    );
  } else {
    await appendLog(
      `Chat ${number}/${total}: no action found`,
      "No Continue or Try again button associated with a usage-limit notice was found in this chat.",
      currentUrl
    );
  }

  if (result.found && result.clicked) batch.clickedAny = true;

  batch.index += 1;
  if (batch.index >= total) {
    await setBatch(batch);
    await finishBatch(`Finished checking ${total} sidebar chat(s).`);
  } else {
    batch.phase = "navigate";
    await setBatch(batch);
    await goToCurrentQueueItem(batch);
  }
}

async function processScannerTab(tabId) {
  if (processingTabs.has(tabId)) return;
  processingTabs.add(tabId);
  try {
    const batch = await getBatch();
    if (!batch || batch.scannerTabId !== tabId) return;

    if (batch.phase === "collect" || batch.phase === "collecting") {
      batch.phase = "collecting";
      await setBatch(batch);
      await delay(900);
      let response;
      try {
        response = await chrome.tabs.sendMessage(tabId, {
          type: "collectSidebarChats",
          jobId: batch.jobId
        });
      } catch (_) {
        await injectScanner(tabId);
        await delay(700);
        response = await chrome.tabs.sendMessage(tabId, {
          type: "collectSidebarChats",
          jobId: batch.jobId
        });
      }
      await handleSidebarLinks(tabId, response);
      return;
    }

    if (batch.phase === "navigate") {
      batch.phase = "inspecting";
      await setBatch(batch);
      // Let the chat's message list and any usage-limit banner settle before inspection.
      await delay(1300);
      let response;
      try {
        response = await chrome.tabs.sendMessage(tabId, {
          type: "inspectBatchChat",
          jobId: batch.jobId
        });
      } catch (_) {
        await injectScanner(tabId);
        await delay(700);
        response = await chrome.tabs.sendMessage(tabId, {
          type: "inspectBatchChat",
          jobId: batch.jobId
        });
      }
      await handleChatResult(tabId, response);
    }
  } catch (error) {
    const batch = await getBatch();
    if (batch && batch.scannerTabId === tabId) {
      await finishBatch(`The scanner encountered an error: ${error?.message || String(error)}`, "Sidebar scan error");
    }
  } finally {
    processingTabs.delete(tabId);
  }
}

// Attach automatically to regular Claude tabs on install/startup/navigation.
chrome.runtime.onInstalled.addListener(() => {
  void injectIntoOpenClaudeTabs();
  void autoStartOnCurrentClaudeTab();
});
chrome.runtime.onStartup.addListener(() => {
  void injectIntoOpenClaudeTabs();
  void autoStartOnCurrentClaudeTab();
});

chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  const url = changeInfo.url || tab?.url;
  if (isClaudeUrl(url) && (changeInfo.status === "complete" || Boolean(changeInfo.url))) {
    void injectScanner(tabId);
  }
  if (changeInfo.status === "complete") {
    void processScannerTab(tabId);
    if (tab?.active && isClaudeUrl(url)) void maybeAutoStartForTab({ ...tab, url });
  }
});

chrome.tabs.onActivated.addListener(({ tabId }) => {
  chrome.tabs.get(tabId, tab => {
    if (chrome.runtime.lastError) return;
    if (isClaudeUrl(tab?.url)) {
      void injectScanner(tabId);
      void maybeAutoStartForTab({ ...tab, active: true });
    }
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
    startBatchScan().then(sendResponse).catch(error => sendResponse({ ok: false, error: error?.message || String(error) }));
    return true;
  }

  if (message.type === "stopBatchScan") {
    stopBatchScan().then(sendResponse).catch(error => sendResponse({ ok: false, error: error?.message || String(error) }));
    return true;
  }

  if (message.type === "diagnostic" || message.type === "clicked") {
    appendLog(
      String(message.status || message.type),
      String(message.detail || ""),
      String(message.url || sender.tab?.url || ""),
      String(message.button || "")
    );
    return;
  }
});
