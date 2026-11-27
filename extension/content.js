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
  const log = (msg) => PROFILE && send({ type: "log", profile: PROFILE, msg });

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
    const buttons = [...document.querySelectorAll("button")].filter(visible);
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
    const v = await waitFor(viewAll, 15000);
    if (!v) return false;
    v.click();
    return !!(await waitFor(
      () => location.pathname.startsWith("/recents") || location.pathname.startsWith("/chats"),
      10000
    ));
  }

  // timings copied from the user's video (milliseconds)
  const T = {
    beforeViewAll: 2700,  // /new page -> click "View all"
    firstList: 3250,      // first list page -> click first chat
    list: 2500,           // list page (later times) -> click next chat
    beforeContinue: 3000, // chat opened -> click Continue
    findContinue: 12000,  // slow internet: keep looking this long for the button
    afterContinue: 6750,  // Continue clicked -> click "View all" again
  };

  async function walk() {
    walking = true;
    send({ type: "maximize" });
    log("walk started");
    await waitFor(() => document.readyState === "complete" && viewAll(), 90000);
    if (!viewAll()) return log("STOP: 'View all' not found (not loaded, or not logged in)");
    await sleep(T.beforeViewAll);
    if (limitShown()) return;
    if (!(await openList())) return log("STOP: could not open the chat list");
    await sleep(T.firstList);
    const hrefs = [...new Set(chatLinks().map((a) => a.getAttribute("href")))].slice(0, 20);
    log(`found ${hrefs.length} chats`);
    for (let i = 0; i < hrefs.length; i++) {
      if (limitShown()) return;
      const last = i === hrefs.length - 1;
      const tag = `chat ${i + 1}/${hrefs.length}`;
      let a = chatLinks().find((x) => x.getAttribute("href") === hrefs[i]);
      if (!a) {
        if (!(await openList())) return log("STOP: could not open the chat list");
        await sleep(T.list);
        a = chatLinks().find((x) => x.getAttribute("href") === hrefs[i]);
      }
      if (!a) {
        log(`${tag}: link not found, skipped`);
        continue;
      }
      a.click();
      await sleep(T.beforeContinue);
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
