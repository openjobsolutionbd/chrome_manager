const logElement = document.getElementById("log");
const statusElement = document.getElementById("status");
const batchButton = document.getElementById("batch");
const stopButton = document.getElementById("stop");

function renderLog(entries) {
  if (!Array.isArray(entries) || entries.length === 0) {
    logElement.textContent = "(no scan results yet)";
    return;
  }
  logElement.textContent = [...entries].reverse().map(entry => {
    const button = entry.button ? `\nButton: ${entry.button}` : "";
    return `[${entry.time || ""}] ${entry.status || ""}${button}\n` +
      `${entry.detail || ""}\nURL: ${entry.url || ""}\n`;
  }).join("\n");
}

function renderBatch(batch) {
  const running = Boolean(batch && batch.scannerTabId);
  batchButton.disabled = running;
  stopButton.disabled = !running;
  if (!running) {
    statusElement.textContent = "Starts by itself when a Claude tab opens. You can also start it from the button above.";
    return;
  }
  if (batch.phase === "collect") {
    statusElement.textContent = "Collecting chat links from the Claude sidebar…";
  } else {
    const total = batch.queue?.length || 0;
    const current = Math.min((batch.index || 0) + 1, total);
    statusElement.textContent = `Scanning sidebar chats: ${current} of ${total}. Your original tab is untouched.`;
  }
}

function refresh() {
  chrome.storage.local.get({ log: [], batchScan: null }, data => {
    if (chrome.runtime.lastError) {
      logElement.textContent = "Could not load log.";
      return;
    }
    renderLog(data.log);
    renderBatch(data.batchScan);
  });
}

function sendMessage(message) {
  return new Promise((resolve, reject) => {
    chrome.runtime.sendMessage(message, response => {
      if (chrome.runtime.lastError) reject(new Error(chrome.runtime.lastError.message));
      else resolve(response);
    });
  });
}

batchButton.addEventListener("click", async () => {
  statusElement.textContent = "Starting sidebar scan…";
  try {
    const response = await sendMessage({ type: "startBatchScan" });
    if (!response?.ok) statusElement.textContent = response?.error || "Could not start the sidebar scan.";
    else statusElement.textContent = response.message;
  } catch (error) {
    statusElement.textContent = `Could not start scan: ${error.message}`;
  }
  refresh();
});

stopButton.addEventListener("click", async () => {
  statusElement.textContent = "Stopping sidebar scan…";
  try {
    const response = await sendMessage({ type: "stopBatchScan" });
    statusElement.textContent = response?.message || "Stop requested.";
  } catch (error) {
    statusElement.textContent = `Could not stop scan: ${error.message}`;
  }
  refresh();
});

document.getElementById("clear").addEventListener("click", () => {
  chrome.storage.local.set({ log: [] }, () => {
    if (chrome.runtime.lastError) {
      statusElement.textContent = "Could not clear log.";
      return;
    }
    statusElement.textContent = "Log cleared.";
    refresh();
  });
});

chrome.storage.onChanged.addListener((changes, areaName) => {
  if (areaName !== "local") return;
  if (changes.log || changes.batchScan) refresh();
});

refresh();
