// job-hunter: read one LinkedIn job search results page, read-only. Run on a
// https://www.linkedin.com/jobs/search/ page. Returns JSON lines: a {"_meta":...} line, then one
// line per job. Clicks a job card only to show its description in the side pane (what a person
// does to read it). Never applies, saves, follows or messages. Job ids whose description it has
// read are remembered in this browser (localStorage "jh_seen") so later runs skip them.
(async () => {
  const P = __PARAMS__; // {per: descriptions to read on this page, w: words a title needs}
  const t0 = Date.now(), sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const jitter = (a, b) => sleep(a + Math.random() * (b - a));
  const meta = { q: "", n: 0, read: 0 };
  const done = (jobs, note) => {
    if (note) meta.note = note;
    meta.n = jobs.length;
    const out = [JSON.stringify({ _meta: meta }), ...jobs.map((j) => JSON.stringify(j))].join("\n");
    window.__jh = out;
    return out;
  };
  const path = location.pathname;
  if (/\/(login|authwall|uas\/login)/.test(path)) return done([], "signin");
  if (/checkpoint|challenge/.test(path) || document.querySelector("#captcha-internal, iframe[src*='captcha']"))
    return done([], "checkpoint");
  const kw = new URLSearchParams(location.search).get("keywords") || "";
  meta.q = kw.replace(/"/g, "").split(/\s+OR\s+/).join(" / ");

  const CARD = "[data-occludable-job-id], [data-job-id], li:has(a[href*='/jobs/view/'])";
  for (let i = 0; i < 20 && !document.querySelector(CARD); i++) await sleep(400);
  if (!document.querySelector(CARD)) {
    const none = /no matching jobs|no results/i.test(document.body.innerText.slice(0, 5000));
    return done([], none ? "no results" : "no job cards found (page layout may have changed)");
  }
  // the list is virtualised: scroll it so all ~25 cards render
  const scroller = (() => {
    for (let el = document.querySelector(CARD); el; el = el.parentElement) {
      const s = getComputedStyle(el);
      if (/(auto|scroll)/.test(s.overflowY) && el.scrollHeight > el.clientHeight + 20) return el;
    }
    return document.scrollingElement;
  })();
  let last = -1, still = 0;
  for (let i = 0; i < 40 && still < 3; i++) {
    scroller.scrollTop += 500;
    await jitter(300, 550);
    const n = document.querySelectorAll(CARD).length;
    still = n === last ? still + 1 : 0;
    last = n;
  }
  scroller.scrollTop = 0;

  const NOISE = /promoted|easy apply|applicant|viewed|actively|early applicant|alumni|connection|reposted|ago$|^\$|verified|school|benefit|response insights|^\d+ (?:minute|hour|day|week|month)/i;
  const idOf = (el) => {
    const v = el.getAttribute("data-occludable-job-id") || el.getAttribute("data-job-id");
    if (v && /^\d+$/.test(v)) return v;
    const a = el.querySelector("a[href*='/jobs/view/']");
    const m = a && a.getAttribute("href").match(/\/jobs\/view\/(\d+)/);
    return m ? m[1] : null;
  };
  const jobs = [], byId = {}, els = {};
  for (const el of document.querySelectorAll(CARD)) {
    const id = idOf(el);
    if (!id || byId[id]) continue;
    const a = el.querySelector("a[href*='/jobs/view/']");
    let title = ((a && (a.getAttribute("aria-label") || a.innerText)) || "").split("\n")[0].replace(/\s+with verification$/i, "").trim();
    const lines = [];
    for (const raw of el.innerText.split("\n")) {
      const s = raw.trim();
      if (s && s !== lines[lines.length - 1]) lines.push(s);
    }
    if (!title) title = lines[0] || "";
    const rest = lines.filter((s) => s !== title && !s.startsWith(title) && !NOISE.test(s));
    const time = el.querySelector("time[datetime]");
    const job = { url: `https://www.linkedin.com/jobs/view/${id}/`, title, company: rest[0] || "",
      location: rest[1] || "", query: meta.q };
    if (time) job.date_posted = time.getAttribute("datetime").slice(0, 10);
    if (job.title && job.company) { jobs.push(job); byId[id] = job; els[id] = a || el; }
  }

  // descriptions: only for titles that fit, not read before, a few per page, at a person's pace
  let seen = [];
  try { seen = JSON.parse(localStorage.getItem("jh_seen") || "[]"); } catch (e) { seen = []; }
  const seenSet = new Set(seen), words = (P.w || []).map((w) => w.toLowerCase());
  const PANE = ["#job-details", ".jobs-description__content", ".jobs-description-content__text",
    "[class*='jobs-description']", ".jobs-search__job-details--container", "article"];
  for (const id of Object.keys(byId)) {
    if (meta.read >= (P.per || 0)) break;
    if (Date.now() - t0 > 22000) { meta.note = "stopped early to stay under the time limit"; break; }
    const job = byId[id], t = job.title.toLowerCase();
    if (seenSet.has(id) || (words.length && !words.some((w) => t.includes(w)))) continue;
    els[id].scrollIntoView({ block: "center" });
    await jitter(400, 800);
    els[id].click();
    await jitter(1800, 3200);
    if (!location.pathname.startsWith("/jobs/search")) { meta.note = "a click left the results page"; break; }
    let text = "";
    for (const sel of PANE) {
      const el = document.querySelector(sel);
      if (el && el.innerText.trim().length > 200) { text = el.innerText; break; }
    }
    const current = new URLSearchParams(location.search).get("currentJobId");
    if (!text || (current && current !== id)) continue;
    job.description = text.replace(/^\s*About the job\s*/i, "").replace(/\s+/g, " ").trim().slice(0, 3000);
    seenSet.add(id);
    meta.read++;
  }
  try { localStorage.setItem("jh_seen", JSON.stringify([...seenSet].slice(-2000))); } catch (e) { /* private window */ }
  return done(jobs);
})();
