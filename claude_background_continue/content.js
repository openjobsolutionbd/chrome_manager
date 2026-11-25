// Claude Background Continue v2.0.0 -- page helper.
//
// This file does nothing by itself: no timers, no observers, no clicks of its own.
// background.js injects it into a Claude tab and then calls the functions below, one short
// synchronous call at a time. All waiting happens in background.js, because a page in a
// minimized or background window is "hidden" and Chrome slows down its timers.

(() => {
  const VERSION = "2.0.0";
  if (globalThis.__cbc && globalThis.__cbc.version === VERSION) return;

  const ACTION_SELECTOR = "button, [role='button'], a, input[type='button'], input[type='submit']";
  const LIMIT_MARKERS = [
    "paused when your free usage ran out",
    "free usage ran out",
    "stopped by a usage limit",
    "usage limit",
    "out of free",
    "free messages return"
  ];

  const normalize = value => String(value || "")
    .replace(/[​-‍﻿]/g, "")
    .replace(/\s+/g, " ")
    .trim()
    .toLowerCase();

  const visibleText = element => normalize(element?.innerText || element?.textContent || "");

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

  // The closest visible block around the button that mentions a usage limit. A "Continue"
  // button with no limit notice around it (for example inside a code answer) is ignored.
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

  // ---- sidebar ----

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

  function sidebarRoots() {
    return [...document.querySelectorAll("aside, nav, [role='navigation']")];
  }

  function chatUrlsFrom(anchors) {
    const urls = [];
    const seen = new Set();
    for (const anchor of anchors) {
      const url = chatUrlFromAnchor(anchor);
      if (url && !seen.has(url)) {
        seen.add(url);
        urls.push(url);
      }
    }
    return urls;
  }

  // Chat links in the sidebar, in page order. Visibility is not required, so a sidebar that
  // is collapsed (for example because the window is small or minimized) still gives its links.
  function collectLinks() {
    const inSidebar = [];
    for (const root of sidebarRoots()) inSidebar.push(...root.querySelectorAll("a[href]"));
    const urls = chatUrlsFrom(inSidebar);
    if (urls.length) return urls;

    // No sidebar element found: fall back to every link, except ones clearly in the main area.
    const everywhere = [...document.querySelectorAll("a[href]")].filter(anchor => {
      const rect = anchor.getBoundingClientRect();
      return !(rect.width && rect.height && rect.left > Math.max(520, window.innerWidth * 0.55));
    });
    return chatUrlsFrom(everywhere);
  }

  // Claude may hide older chats behind a "View all" control.
  function expandSidebar() {
    const viewAll = [...document.querySelectorAll("button, a, [role='button']")]
      .find(element => isVisible(element) && normalize(element.innerText || element.textContent) === "view all");
    if (!viewAll) return false;
    viewAll.click();
    return true;
  }

  // Scrolls every scrollable sidebar container down by one page. Returns whether anything moved
  // and whether all of them are now at the bottom.
  function scrollSidebar() {
    const roots = sidebarRoots();
    const scope = roots.length ? roots : [document.body];
    const seen = new Set();
    let moved = false;
    let atBottom = true;
    for (const root of scope) {
      for (const element of [root, ...root.querySelectorAll("*")]) {
        if (seen.has(element)) continue;
        seen.add(element);
        const style = getComputedStyle(element);
        const canScroll = element.scrollHeight > element.clientHeight + 40 &&
          /(auto|scroll)/.test(`${style.overflowY} ${style.overflow}`);
        if (!canScroll) continue;
        const before = element.scrollTop;
        element.scrollTop = Math.min(element.scrollHeight, before + Math.max(180, element.clientHeight * 0.8));
        if (element.scrollTop !== before) moved = true;
        if (element.scrollTop + element.clientHeight < element.scrollHeight - 2) atBottom = false;
      }
    }
    return { moved, atBottom };
  }

  // ---- one chat ----

  // What the page looks like right now. background.js polls this until the chat has loaded
  // and stopped changing.
  function snapshot() {
    const action = findUsageLimitAction();
    const text = visibleText(document.body);
    return {
      url: location.href,
      readyState: document.readyState,
      visibility: document.visibilityState,
      width: window.innerWidth,
      height: window.innerHeight,
      textLength: text.length,
      limitNotice: containsLimitNotice(text),
      action: action ? { name: action.buttonName } : null
    };
  }

  // Looks the button up again (the page may have changed since snapshot()) and clicks it once.
  function clickAction(expectedName) {
    const hit = findUsageLimitAction();
    if (!hit) return { clicked: false, reason: "the button was gone" };
    if (expectedName && hit.buttonName !== expectedName) {
      return { clicked: false, reason: `the button changed to "${hit.buttonName}"` };
    }
    hit.button.click();
    return { clicked: true, name: hit.buttonName };
  }

  globalThis.__cbc = { version: VERSION, snapshot, clickAction, collectLinks, expandSidebar, scrollSidebar };
})();
