(() => {
  if (window.__clc) return;
  window.__clc = true;

  // profile name given by launcher.py in the address (#cm=Profile%201)
  let PROFILE = "";
  try {
    const m = location.hash.match(/cm=([^&]+)/);
    if (m) {
      PROFILE = decodeURIComponent(m[1]);
      sessionStorage.setItem("clc_profile", PROFILE);
    } else {
      PROFILE = sessionStorage.getItem("clc_profile") || "";
    }
  } catch (e) {}

  // waiting is done by the background script (page timers are slowed in covered windows)
  const sleep = (ms) => {
    try {
      return chrome.runtime
        .sendMessage({ type: "sleep", ms })
        .catch(() => new Promise((r) => setTimeout(r, ms)));
    } catch (e) {
      return new Promise((r) => setTimeout(r, ms));
    }
  };
  const send = (m) => {
    try {
      chrome.runtime.sendMessage(m).catch(() => {});
    } catch (e) {}
  };
  const log = (msg) => send({ type: "log", profile: PROFILE || "manual", msg });

  let lastContinueClick = 0;
  let walkDone = false;
  let limitSent = false;
  let walking = false;

  // ---------- limit message (reset time) ----------
  function limitLine() {
    if (!document.body) return null;
    const lines = (document.body.innerText || "").split("\n");
    for (let l of lines) {
      l = l.trim();
      if (l.length < 3 || l.length > 150) continue;
      if (
        (/out of (free )?messages/i.test(l) && /(until|resets?)\s*(at|in)?\s*\d/i.test(l)) ||
        /(usage )?limit (reached|resets?)\s*(at|in)\s*\d/i.test(l)
      )
        return l;
    }
    return null;
  }
  const limitShown = () => !!limitLine();

  // ---------- Continue / Try again button ----------
  function visible(el) {
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  }
  function findContinue() {
    const buttons = [...document.querySelectorAll("button,[role='button']")].filter(visible);
    for (const b of buttons) {
      if (!/^(continue|try again|retry)$/i.test(b.textContent.trim())) continue;
      let p = b.parentElement;
      for (let i = 0; i < 4 && p; i++, p = p.parentElement) {
        if (/paused when your free usage ran out|usage ran out/i.test(p.innerText || "")) return b;
      }
    }
    return buttons.find((b) => /^(try again|retry)$/i.test(b.textContent.trim())) || null;
  }

  // ---------- always-on watcher (limit -> close; hand-opened chats -> Continue) ----------
  (async () => {
    for (;;) {
      await sleep(1000);
      try {
        const line = limitLine();
        if (line) {
          if (!limitSent) {
            limitSent = true;
            send({ type: "limit", profile: PROFILE, line: line.slice(0, 120) });
          }
          continue;
        }
        if (walking) continue; // the walk clicks Continue itself, with the video timing
        if (Date.now() - lastContinueClick < 6000) continue;
        const b = findContinue();
        if (b) {
          lastContinueClick = Date.now();
          b.click();
          log(`clicked "${b.textContent.trim()}" (watcher)`);
        }
      } catch (e) {}
    }
  })();

  // ---------- tell launcher.py we are alive; it may say "close" ----------
  async function waitFor(fn, ms) {
    const end = Date.now() + ms;
    while (Date.now() < end) {
      const v = fn();
      if (v) return v;
      await sleep(400);
    }
    return null;
  }

  if (PROFILE) {
    (async () => {
      if (document.readyState !== "complete")
        await new Promise((r) => window.addEventListener("load", r, { once: true }));
      for (;;) {
        send({ type: "ping", profile: PROFILE, done: walkDone });
        await sleep(2000);
      }
    })();
  }

  // ---------- one-time walk through recent chats ----------
  const viewAll = () =>
    [...document.querySelectorAll("a,button")].find(
      (e) => /^view all$/i.test(e.textContent.trim()) && visible(e)
    );
  const chatLinks = () => [...document.querySelectorAll("a[href^='/chat/']")].filter(visible);

  async function openList() {
    const v = await waitFor(viewAll, 60000);
    if (!v) return false;
    v.click();
    return !!(await waitFor(
      () => location.pathname.startsWith("/recents") || location.pathname.startsWith("/chats"),
      60000
    ));
  }

  // slow internet: do not leave a chat / list before it has really loaded
  async function waitChatLoaded(titleBefore) {
    const t0 = Date.now();
    let last = -1, same = 0, titleOk = false;
    while (Date.now() - t0 < T.maxLoad) {
      await sleep(1000);
      if (limitShown()) return true;
      if (!location.pathname.startsWith("/chat/")) continue;
      if (document.title !== titleBefore) titleOk = true;
      const len = document.body ? document.body.innerText.length : 0;
      same = len === last ? same + 1 : 0;
      last = len;
      if (document.readyState === "complete" && same >= 3 && (titleOk || Date.now() - t0 > T.loadNoTitle)) return true;
    }
    return false;
  }
  async function waitListLoaded() {
    const t0 = Date.now();
    let last = -1, same = 0;
    while (Date.now() - t0 < T.maxLoad) {
      await sleep(1000);
      const n = chatLinks().length;
      same = n > 0 && n === last ? same + 1 : 0;
      last = n;
      if (same >= 2) return;
    }
  }

  // timings copied from the user's video (milliseconds)
  const T = {
    beforeViewAll: 2700,  // /new page -> click "View all"
    firstList: 3250,      // first list page -> click first chat
    list: 2500,           // list page (later times) -> click next chat
    findContinue: 12000,  // slow internet: keep looking this long for the button
    afterContinue: 6750,  // Continue clicked -> click "View all" again
    maxLoad: 90000,       // slow internet: wait up to this long for a page to load
    loadNoTitle: 20000,   // chat title never changed: accept the page as loaded after this long
    afterLoaded: 1000,    // page loaded -> look for Continue
  };

  async function walk() {
    walking = true;
    send({ type: "maximize" });
    log(`walk started (extension v${chrome.runtime.getManifest().version})`);
    await waitFor(() => document.readyState === "complete" && viewAll(), 90000);
    if (!viewAll()) return log("STOP: 'View all' not found (not loaded, or not logged in)");
    await sleep(T.beforeViewAll);
    if (limitShown()) return;
    if (!(await openList())) return log("STOP: could not open the chat list");
    await sleep(T.firstList);
    await waitListLoaded();
    const hrefs = [...new Set(chatLinks().map((a) => a.getAttribute("href")))].slice(0, 20);
    log(`found ${hrefs.length} chats`);
    for (let i = 0; i < hrefs.length; i++) {
      if (limitShown()) return;
      const last = i === hrefs.length - 1;
      const tag = `chat ${i + 1}/${hrefs.length}`;
      const findLink = () => chatLinks().find((x) => x.getAttribute("href") === hrefs[i]);
      let a = await waitFor(findLink, 60000);
      if (!a) {
        if (!(await openList())) return log("STOP: could not open the chat list");
        await sleep(T.list);
        a = await waitFor(findLink, 60000);
      }
      if (!a) {
        log(`${tag}: link not found, skipped`);
        continue;
      }
      const titleBefore = document.title;
      const tLoad = Date.now();
      a.click();
      const loaded = await waitChatLoaded(titleBefore);
      log(`${tag}: ${loaded ? "loaded" : "NOT loaded"} after ${Math.round((Date.now() - tLoad) / 1000)} s`);
      await sleep(T.afterLoaded);
      const b = await waitFor(findContinue, T.findContinue);
      if (b) {
        b.click();
        lastContinueClick = Date.now();
        await sleep(last ? 3000 : T.afterContinue);
        const again = findContinue();
        if (again) {
          again.click();
          log(`${tag}: Continue clicked, was still there, clicked again`);
          await sleep(3000);
        } else {
          log(`${tag}: Continue clicked`);
        }
      } else {
        log(`${tag}: no Continue button`);
      }
      if (last) break; // Python waits 10 seconds, then closes
      if (!(await openList())) return log("STOP: could not open the chat list");
      await sleep(T.list);
    }
    log("walk finished");
  }

  if (location.pathname === "/new" || location.pathname === "/") {
    chrome.runtime.sendMessage({ type: "shouldScan" }, (yes) => {
      if (yes)
        walk()
          .catch((e) => log("ERROR: " + e))
          .finally(() => {
            walking = false;
            walkDone = true;
          });
      else walkDone = true;
    });
  } else {
    walkDone = true;
  }
})();
