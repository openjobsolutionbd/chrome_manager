// Claude Background Continue v1.5.0
// Watches the current chat and supports sequential inspection of sidebar chats.

(() => {
  const INSTANCE_KEY = "__claudeBackgroundContinueV15";
  if (globalThis[INSTANCE_KEY]) {
    globalThis[INSTANCE_KEY].scan();
    return;
  }

  const ACTION_SELECTOR = "button, [role='button'], a, input[type='button'], input[type='submit']";
  const LIMIT_MARKERS = [
    "paused when your free usage ran out",
    "free usage ran out",
    "stopped by a usage limit",
    "usage limit",
    "out of free",
    "free messages return"
  ];

  const clickedButtons = new WeakSet();
  const pendingButtons = new WeakSet();
  let scanQueued = false;
  let lastDiagnosticKey = "";
  let lastActionForPage = null;

  const normalize = value => String(value || "")
    .replace(/[\u200B-\u200D\uFEFF]/g, "")
    .replace(/\s+/g, " ")
    .trim()
    .toLowerCase();

  const visibleText = element => normalize(element?.innerText || element?.textContent || "");

  function delay(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
  }

  function isVisible(element) {
    if (!element || !element.isConnected) return false;
    const style = window.getComputedStyle(element);
    if (style.display === "none" || style.visibility === "hidden" || Number(style.opacity) === 0) return false;
    return element.getClientRects().length > 0;
  }

  function getActionName(element) {
    const labels = [
      element.innerText,
      element.getAttribute("aria-label"),
      element.getAttribute("title"),
      element.value,
      element.textContent
    ];
    for (const label of labels) {
      const text = normalize(label);
      const match = text.match(/^(continue|try again)(?=$|[\s:·])/i);
      if (match) return match[1].toLowerCase() === "continue" ? "Continue" : "Try again";
    }
    return null;
  }

  function containsLimitNotice(text) {
    return LIMIT_MARKERS.some(marker => text.includes(normalize(marker)));
  }

  function findNearestLimitContext(button) {
    let current = button.parentElement;
    let depth = 1;
    let best = null;
    while (current && depth <= 12 && current !== document.body && current !== document.documentElement) {
      if (isVisible(current)) {
        const text = visibleText(current);
        if (containsLimitNotice(text)) {
          const score = text.length + depth * 3;
          if (!best || score < best.score) best = { text, score };
        }
      }
      current = current.parentElement;
      depth += 1;
    }
    return best;
  }

  function hasLimitNoticeOnPage() {
    return containsLimitNotice(visibleText(document.body));
  }

  function sendLog(type, status, detail, buttonName = "") {
    try {
      const result = chrome.runtime.sendMessage({
        type,
        status,
        detail,
        button: buttonName,
        url: location.href,
        time: Date.now()
      });
      if (result && typeof result.catch === "function") result.catch(() => {});
    } catch (_) {
      // Ignore extension reload/shutdown races.
    }
  }

  function reportOnce(status, detail, buttonName = "") {
    const key = `${status}|${buttonName}|${detail}`;
    if (key === lastDiagnosticKey) return;
    lastDiagnosticKey = key;
    sendLog("diagnostic", status, detail, buttonName);
  }

  function findUsageLimitAction() {
    const candidates = [];
    for (const element of document.querySelectorAll(ACTION_SELECTOR)) {
      if (!isVisible(element) || element.disabled) continue;
      if (element.getAttribute("aria-disabled") === "true") continue;
      const actionName = getActionName(element);
      if (!actionName) continue;
      const context = findNearestLimitContext(element);
      if (!context) continue;
      candidates.push({ button: element, buttonName: actionName, score: context.score });
    }
    candidates.sort((a, b) => a.score - b.score);
    return candidates[0] || null;
  }

  function attemptClick(hit) {
    return new Promise(resolve => {
      if (!hit || clickedButtons.has(hit.button)) {
        resolve({ clicked: Boolean(hit && clickedButtons.has(hit.button)), alreadyHandled: true });
        return;
      }
      if (pendingButtons.has(hit.button)) {
        resolve({ clicked: false, pending: true });
        return;
      }
      pendingButtons.add(hit.button);
      window.setTimeout(() => {
        pendingButtons.delete(hit.button);
        if (!isVisible(hit.button) || hit.button.disabled || hit.button.getAttribute("aria-disabled") === "true") {
          resolve({ clicked: false, stale: true });
          return;
        }
        if (getActionName(hit.button) !== hit.buttonName) {
          resolve({ clicked: false, stale: true });
          return;
        }
        const currentHit = findUsageLimitAction();
        if (!currentHit || currentHit.button !== hit.button || clickedButtons.has(hit.button)) {
          resolve({ clicked: false, stale: true });
          return;
        }
        clickedButtons.add(hit.button);
        hit.button.click();
        lastActionForPage = { buttonName: hit.buttonName, url: location.href, time: Date.now() };
        sendLog(
          "clicked",
          "Click attempted",
          `Clicked the "${hit.buttonName}" button associated with the usage-limit notice.`,
          hit.buttonName
        );
        resolve({ clicked: true });
      }, 450);
    });
  }

  async function scanPage() {
    const hit = findUsageLimitAction();
    if (!hit) {
      if (hasLimitNoticeOnPage()) {
        reportOnce(
          "Notice found, button not detected",
          "Usage-limit text is visible, but no Continue or Try again button was found beside it."
        );
      } else {
        lastDiagnosticKey = "";
      }
      return;
    }
    reportOnce("Button detected", `Found "${hit.buttonName}" beside a Claude usage-limit notice.`, hit.buttonName);
    await attemptClick(hit);
  }

  function queueScan() {
    if (scanQueued) return;
    scanQueued = true;
    window.setTimeout(() => {
      scanQueued = false;
      void scanPage();
    }, 120);
  }

  function chatUrlFromAnchor(anchor) {
    try {
      const url = new URL(anchor.getAttribute("href"), location.origin);
      if (url.origin !== location.origin) return null;
      if (!/\/chat\/[^/]+/i.test(url.pathname)) return null;
      return url.href;
    } catch (_) {
      return null;
    }
  }

  function collectChatLinks() {
    const found = [];
    const seen = new Set();
    for (const anchor of document.querySelectorAll("a[href]")) {
      const rect = anchor.getBoundingClientRect();
      // Chat links are normally in the left navigation/sidebar.
      if (rect.width && rect.height && rect.left > Math.max(520, window.innerWidth * 0.55)) continue;
      const url = chatUrlFromAnchor(anchor);
      if (url && !seen.has(url)) {
        seen.add(url);
        found.push(url);
      }
    }
    return found;
  }

  async function collectSidebarChatLinks() {
    let urls = collectChatLinks();

    // Claude's sidebar may collapse older chats behind a "View all" control.
    const viewAll = [...document.querySelectorAll("button, a, [role='button']")]
      .find(element => isVisible(element) && normalize(element.innerText || element.textContent) === "view all");
    if (viewAll) {
      viewAll.click();
      await delay(900);
      urls = collectChatLinks();
    }

    const sidebarRoots = [...document.querySelectorAll("aside, nav, [role='navigation']")];
    const roots = sidebarRoots.length ? sidebarRoots : [document.body];
    const scrollers = [];
    for (const root of roots) {
      for (const element of [root, ...root.querySelectorAll("*")]) {
        const style = getComputedStyle(element);
        const canScroll = element.scrollHeight > element.clientHeight + 40 &&
          /(auto|scroll)/.test(`${style.overflowY} ${style.overflow}`);
        if (canScroll && !scrollers.includes(element)) scrollers.push(element);
      }
    }

    const originalPositions = scrollers.map(element => [element, element.scrollTop]);
    const maxRounds = 18;
    for (const scroller of scrollers) {
      for (let round = 0; round < maxRounds; round += 1) {
        const before = scroller.scrollTop;
        scroller.scrollTop = Math.min(scroller.scrollHeight, before + Math.max(180, scroller.clientHeight * 0.8));
        await delay(180);
        const newlyFound = collectChatLinks();
        const known = new Set(urls);
        for (const url of newlyFound) if (!known.has(url)) urls.push(url);
        if (scroller.scrollTop === before || scroller.scrollTop + scroller.clientHeight >= scroller.scrollHeight - 2) break;
      }
    }
    for (const [element, position] of originalPositions) element.scrollTop = position;

    // Include any links which became visible during scrolling, preserving first-seen order.
    const finalLinks = collectChatLinks();
    const known = new Set(urls);
    for (const url of finalLinks) if (!known.has(url)) urls.push(url);
    return urls;
  }

  async function inspectBatchChat() {
    // Automatic page scanning may already have clicked the button while this tab loaded.
    await delay(250);
    const hit = findUsageLimitAction();
    if (hit) {
      reportOnce("Button detected", `Found "${hit.buttonName}" beside a Claude usage-limit notice.`, hit.buttonName);
      const clickResult = await attemptClick(hit);
      return {
        found: true,
        buttonName: hit.buttonName,
        clicked: Boolean(clickResult.clicked || clickedButtons.has(hit.button)),
        detail: clickResult.alreadyHandled ? "The action was already handled by the automatic page scanner." : "Usage-limit action inspected."
      };
    }

    if (lastActionForPage && lastActionForPage.url === location.href && Date.now() - lastActionForPage.time < 15000) {
      return {
        found: true,
        buttonName: lastActionForPage.buttonName,
        clicked: true,
        detail: "The automatic page scanner already clicked this action."
      };
    }

    if (hasLimitNoticeOnPage()) {
      return {
        found: false,
        detail: "A usage-limit notice was visible, but no matching Continue or Try again action was found."
      };
    }
    return { found: false, detail: "No usage-limit action found." };
  }

  chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    if (!message || typeof message.type !== "string") return;

    if (message.type === "collectSidebarChats") {
      collectSidebarChatLinks()
        .then(chatUrls => sendResponse({ chatUrls, count: chatUrls.length, pageUrl: location.href }))
        .catch(error => sendResponse({ chatUrls: [], error: error?.message || String(error) }));
      return true;
    }

    if (message.type === "inspectBatchChat") {
      inspectBatchChat()
        .then(sendResponse)
        .catch(error => sendResponse({ found: false, error: error?.message || String(error) }));
      return true;
    }
  });

  const observer = new MutationObserver(queueScan);
  if (document.documentElement) {
    observer.observe(document.documentElement, {
      childList: true,
      subtree: true,
      characterData: true,
      attributes: true,
      attributeFilter: ["disabled", "aria-disabled", "class", "style", "aria-label"]
    });
  }

  globalThis[INSTANCE_KEY] = { scan: scanPage };
  queueScan();
  window.setInterval(() => { void scanPage(); }, 10000);
})();
