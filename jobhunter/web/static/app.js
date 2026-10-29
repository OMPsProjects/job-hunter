// job-hunter local page. Plain JavaScript, no framework, no network calls beyond this computer.
// Everything that comes from a job posting is untrusted: it is only ever set as text (h() below
// never uses innerHTML), so a posting can't run code or change this page.

// The page's key arrives in the link job-hunter opens (#k=...), never inside the page itself, so
// nothing else on this computer can read it from the server. It is kept for this tab only.
const TOKEN = (() => {
  const m = location.hash.match(/^#k=([A-Za-z0-9_-]{20,64})$/);
  let t = "";
  if (m) {
    t = m[1];
    try { sessionStorage.setItem("jh-key", t); } catch { /* private window: this tab only */ }
    history.replaceState(null, "", location.pathname + "#jobs");
  } else {
    try { t = sessionStorage.getItem("jh-key") || ""; } catch { t = ""; }
  }
  return t;
})();
const main = document.getElementById("main");
const PARTS = [["fit", "Fit"], ["seniority", "Level"], ["location_score", "Place"], ["pay_score", "Pay"], ["freshness", "Fresh"]];
const WEIGHT_KEY = { fit: "fit", seniority: "seniority", location_score: "location", pay_score: "pay", freshness: "freshness" };
const STATUS_TEXT = {
  shortlisted: "Shortlisted", tailored: "Resume ready", needs_account: "Needs an account", ready_for_review: "Ready for your review",
  submitted: "Applied", skipped: "Skipped", interviewing: "Interviewing", rejected: "Rejected", offer: "Offer",
};
const SOURCE_TEXT = {
  jobspy: "Indeed and other boards", indeed: "Indeed", linkedin: "LinkedIn", google: "Google Jobs", glassdoor: "Glassdoor",
  zip_recruiter: "ZipRecruiter", remotive: "Remotive", himalayas: "Himalayas", remoteok: "RemoteOK", themuse: "The Muse",
  arbeitnow: "Arbeitnow", adzuna: "Adzuna", usajobs: "USAJobs", jooble: "Jooble", dreamwork: "Dreamwork", company_feeds: "Employers' career sites",
  greenhouse: "Greenhouse", lever: "Lever", ashby: "Ashby", smartrecruiters: "SmartRecruiters", workable: "Workable",
  recruitee: "Recruitee", workday: "Workday", oracle: "Oracle", successfactors: "SuccessFactors",
  unknown: "Not recorded",
};
const nameOf = (k) => SOURCE_TEXT[k] || k;
const VERIFIED_TEXT = {
  verified_open: "Open on the employer's site", employer_page_live: "Employer page is live",
  similar_title_open: "A similar title is open on the employer's site",
  unverified: "Not confirmed yet", not_checked: "Not checked", closed: "Closed", not_on_employer_site: "Not on the employer's site",
};

// ---------------------------------------------------------------- helpers
function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") el.className = v;
    else if (k === "style") el.style.cssText = v; // via CSSOM: allowed by the page's no-inline-styles policy
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "text") el.textContent = v;
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat()) {
    if (kid === null || kid === undefined || kid === false) continue;
    // direction-override characters in posting text would make it display differently than it reads
    el.append(kid instanceof Node ? kid : document.createTextNode(visible(kid)));
  }
  return el;
}

async function api(path, opts = {}) {
  const init = { method: opts.method || "GET", headers: { "X-JH-Token": TOKEN } };
  if (opts.body !== undefined) {
    if (opts.raw) { init.body = opts.body; Object.assign(init.headers, opts.headers || {}); }
    else { init.body = JSON.stringify(opts.body); init.headers["Content-Type"] = "application/json"; }
  }
  const res = await fetch(path, init);
  let data = {};
  try { data = await res.json(); } catch { data = {}; }
  if (!res.ok) { const err = new Error(data.error || `Request failed (${res.status})`); err.status = res.status; throw err; }
  return data;
}

// replaceChildren() would print "null" for skipped pieces and "[object ...]" for arrays
function setMain(...kids) {
  main.replaceChildren(...kids.flat(Infinity).filter((k) => k !== null && k !== undefined && k !== false));
}

let toastTimer;
function toast(msg) {
  const t = document.getElementById("toast");
  t.textContent = msg;
  t.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.remove("show"), 4200);
}

// Only real web links become links (a posting can't smuggle in javascript: or file: URLs).
function safeUrl(u) { return /^https?:\/\//i.test(String(u || "")) ? String(u) : null; }
function jobLink(j) { return safeUrl(j.employer_url) || safeUrl(j.job_url); }
// Characters that don't show on screen (zero-width, tag characters, direction overrides): posting
// text could use them to hide words in what you copy. Removed from everything shown or copied.
const INVISIBLE = /[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f-\u009f\u00ad\u034f\u061c\u115f\u1160\u17b4\u17b5\u180b-\u180f\u200b-\u200f\u202a-\u202e\u2060-\u206f\u3164\ufe00-\ufe0f\ufeff\uffa0\u{e0000}-\u{e0fff}]/gu;
const visible = (t) => String(t ?? "").replace(INVISIBLE, "");
function oneLine(t, n = 140) { return visible(t).replace(/\s+/g, " ").trim().slice(0, n); }
// For the "Ask Claude to..." prompts: one line, no quote marks to break out of the quotes around it.
const quoted = (t, n) => `"${oneLine(t, n).replace(/["\u201c\u201d]/g, "'")}"`;
function day(iso, long = false) {
  if (!iso) return "";
  const d = new Date(String(iso).length <= 10 ? `${iso}T12:00` : iso);
  if (Number.isNaN(d.getTime())) return String(iso).slice(0, 10);
  const opts = long ? { month: "long", day: "numeric", year: "numeric" } : { month: "short", day: "numeric" };
  if (!long && d.getFullYear() !== new Date().getFullYear()) opts.year = "numeric";
  return d.toLocaleDateString([], opts);
}
const SMALL = () => window.matchMedia("(max-width: 900px)").matches;

function money(n) {
  if (n === null || n === undefined || n === "" || Number.isNaN(Number(n))) return "";
  const v = Number(n);
  return v >= 1000 ? `$${Math.round(v / 1000)}k` : `$${v.toFixed(0)}`;
}

function annual(amount, interval) {
  if (amount === null || amount === undefined || Number.isNaN(Number(amount)) || Number(amount) <= 0) return null;
  const mult = { yearly: 1, year: 1, monthly: 12, weekly: 52, daily: 260, hourly: 2080 }[(interval || "").toLowerCase()];
  return Number(amount) * (mult || (Number(amount) < 500 ? 2080 : 1));
}

function payText(j) {
  const lo = annual(j.min_amount, j.interval), hi = annual(j.max_amount, j.interval);
  if (lo || hi) return lo && hi && lo !== hi ? `${money(lo)}-${money(hi)}` : money(hi || lo);
  if (j.pay_estimate) return `about ${money(j.pay_estimate)} typical`;
  return "Pay not posted";
}

function ago(seconds) {
  if (!seconds) return "";
  const d = new Date(seconds * 1000);
  return d.toLocaleString([], { weekday: "short", hour: "numeric", minute: "2-digit" });
}

async function copy(text, what) {
  try { await navigator.clipboard.writeText(text); toast(`Copied. Paste it into Claude Code to ${what}.`); }
  catch { window.prompt("Copy this and paste it into Claude Code:", text); }
}

function prompts(j) {
  // Title, company and link come from the posting, so they're quoted and cleaned: a posting can't
  // add sentences (or hidden text) to what you paste into Claude.
  const job = `the job ${quoted(j.title, 120)} at ${quoted(j.company, 80)}`;
  let link = "";
  try { link = jobLink(j) ? new URL(oneLine(jobLink(j), 500)).href : ""; } catch { link = ""; }
  const ref = link ? ` (${link})` : "";
  return [
    ["Tailor my resume", `Tailor my resume for ${job}${ref}.`, "tailor your resume"],
    ["Write a cover letter", `Write a cover letter for ${job}${ref}.`, "write the cover letter"],
    ["Fill in the application", `Apply to ${job}${ref}. Stop before submitting so I can review it.`, "fill in the application"],
    ["Prepare for the interview", `I have an interview for ${job}. Help me prepare.`, "prepare"],
  ];
}

function strip(j, weights, big = false) {
  const total = PARTS.reduce((s, [k]) => s + (weights[WEIGHT_KEY[k]] || 0), 0) || 1;
  const bar = h("span", { class: big ? "strip big" : "strip", role: "img",
    "aria-label": PARTS.map(([k, label]) => `${label} ${j[k] ?? "?"}`).join(", ") });
  for (const [k] of PARTS) {
    const w = (weights[WEIGHT_KEY[k]] || 0) / total;
    const seg = h("span", { style: `flex: ${w} 0 0` }, h("i", { style: `width: ${Math.max(0, Math.min(100, Number(j[k]) || 0))}%` }));
    bar.append(seg);
  }
  if (!big) return bar;
  const legend = h("div", { class: "strip-legend", "aria-hidden": "true" });
  legend.append(h("span", { class: "strip-note" }, "Each part's width is how much it counts; the dark fill is this job's score on it."));
  for (const [k, label] of PARTS) {
    legend.append(h("span", {}, `${label} `, h("b", {}, j[k] ?? "?"), ` (weight ${weights[WEIGHT_KEY[k]] || 0})`));
  }
  return h("div", {}, bar, legend);
}

function weakParts(j) {
  const weak = PARTS.filter(([k]) => j[k] !== null && j[k] !== undefined && Number(j[k]) < 45).map(([, label]) => label.toLowerCase());
  return weak.length ? `Weak on ${weak.join(", ")}` : "";
}

function splitList(text) { return String(text || "").split(/[\n,]+/).map((s) => s.trim()).filter(Boolean); }

// ---------------------------------------------------------------- app state
const state = {
  status: null,
  jobs: { set: "ranked", rows: [], weights: {}, selected: null, filter: "", minScore: 0, confirmedOnly: false, hideActed: false },
  setup: { step: 0, answers: {}, questions: [], suggestions: null },
  taskSince: 0, taskTimer: null,
};

async function refreshStatus() {
  try {
    state.status = await api("/api/status");
  } catch (e) { state.status = null; state.statusError = e.status; }
  const el = document.getElementById("run-state");
  const s = state.status;
  if (!s && state.statusError === 403) { el.textContent = "job-hunter was restarted. Open it again from the Start file."; return; }
  if (!s) { el.textContent = "Can't reach job-hunter. Is it still running?"; return; }
  if (s.task && s.task.running) el.textContent = `${taskLabel(s.task.name)} is running...`;
  else if (s.last_run && s.last_run.run_at) {
    const when = new Date(s.last_run.run_at);
    el.textContent = `Last search ${when.toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })}: ${s.last_run.new ?? 0} new`;
  } else el.textContent = s.has_profile ? "No searches yet" : "Not set up yet";
}

function taskLabel(name) {
  return { search: "Search", "search-no-verify": "Search", rank: "Re-ranking", discover: "Finding companies",
    "discover-add": "Finding companies", "data-update": "Updating the careers-site directory" }[name] || "A task";
}

// ---------------------------------------------------------------- routing
const VIEWS = { jobs: viewJobs, search: viewSearch, applications: viewApplications, companies: viewCompanies,
  stats: viewStats, setup: viewSetup, settings: viewSettings };

async function route() {
  const name = (location.hash || "#jobs").slice(1).split("?")[0];
  const view = VIEWS[name] ? name : "jobs";
  for (const a of document.querySelectorAll(".tabs a")) {
    if (a.dataset.view === view) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
  }
  document.removeEventListener("keydown", jobKeys);
  setMain(h("p", { class: "muted" }, "Loading..."));
  try { await VIEWS[view](); }
  catch (e) { setMain(h("div", { class: "notice bad" }, h("p", {}, e.message))); }
  document.title = `${name[0].toUpperCase()}${name.slice(1)}, job-hunter`;
}

// ---------------------------------------------------------------- Jobs
async function viewJobs() {
  const s = state.status || (await refreshStatus(), state.status);
  if (s && !s.has_profile) {
    setMain(h("div", { class: "empty" },
      h("h1", {}, "Let's set up your search"),
      h("p", {}, "Answer a few questions about the work you want, and job-hunter builds your search from them. It takes about five minutes."),
      h("a", { class: "btn primary", href: "#setup" }, "Start setup")));
    return;
  }
  const data = await api(`/api/jobs?set=${state.jobs.set}`);
  Object.assign(state.jobs, { rows: data.jobs, weights: data.weights });
  if (!data.jobs.length && state.jobs.set === "ranked") {
    setMain(h("div", { class: "empty" },
      h("h1", {}, "No new jobs to show"),
      h("p", {}, s && s.last_run && s.last_run.run_at
        ? "The last search didn't find anything new that cleared your filters. Excluded jobs are still listed under Excluded."
        : "Run your first search. It checks the job boards and employers' career sites for your titles, then ranks what it finds."),
      h("div", { class: "row" }, h("a", { class: "btn primary", href: "#search" }, "Go to search"),
        h("button", { class: "btn quiet", onclick: () => { state.jobs.set = "excluded"; viewJobs(); } }, "See excluded jobs"))));
    return;
  }
  renderJobs();
  document.addEventListener("keydown", jobKeys);
}

function visibleJobs() {
  const f = state.jobs;
  const q = f.filter.toLowerCase();
  return f.rows.filter((j) =>
    (!q || `${j.title} ${j.company} ${j.location}`.toLowerCase().includes(q)) &&
    (f.set !== "ranked" || (Number(j.rank_score) || 0) >= f.minScore) &&
    (!f.confirmedOnly || ["verified_open", "employer_page_live"].includes(j.verified)) &&
    (!f.hideActed || !j.status || j.status === "shortlisted"));
}

function renderJobs() {
  const f = state.jobs;
  const rows = visibleJobs();
  if (!rows.some((j) => j.job_url === f.selected)) f.selected = rows.length ? rows[0].job_url : null;
  const setBtn = (set, label) => h("button", { "aria-pressed": String(f.set === set), onclick: () => { f.set = set; f.selected = null; viewJobs(); } }, label);
  const toolbar = h("div", { class: "toolbar" },
    h("div", { class: "seg", role: "group", "aria-label": "Which jobs" }, setBtn("ranked", "New"), setBtn("excluded", "Excluded"), setBtn("all", "All found")),
    h("label", { class: "visually-hidden", for: "jf" }, "Filter by title, company or place"),
    h("input", { id: "jf", type: "search", placeholder: "Filter title, company, place", value: f.filter,
      oninput: (e) => { f.filter = e.target.value; renderList(); } }),
    h("details", { class: "more-filters", open: !SMALL() }, h("summary", { class: "btn quiet" }, "Filters"),
      h("div", { class: "row" },
        f.set === "ranked" ? h("label", { class: "row small" }, "Score at least ",
          h("select", { onchange: (e) => { f.minScore = Number(e.target.value); renderList(); } },
            [0, 30, 40, 50, 60].map((v) => h("option", { value: v, selected: f.minScore === v }, v === 0 ? "any" : String(v))))) : null,
        h("label", { class: "check small" }, h("input", { type: "checkbox", checked: f.confirmedOnly,
          onchange: (e) => { f.confirmedOnly = e.target.checked; renderList(); } }), "Confirmed open only"),
        h("label", { class: "check small" }, h("input", { type: "checkbox", checked: f.hideActed,
          onchange: (e) => { f.hideActed = e.target.checked; renderList(); } }), "Hide ones I've acted on"))),
    h("span", { class: "count", id: "jcount" }));
  const split = h("div", { class: "split", id: "split" },
    h("ul", { class: "list", id: "jlist", role: "listbox", "aria-label": "Jobs" }),
    h("section", { class: "reader", id: "reader", "aria-label": "Job details" }));
  setMain(toolbar, split);
  renderList();
  if (location.hash.includes("open") && SMALL()) openReader(false);
}

// On small screens the reading pane covers the list; it gets its own history entry so the
// phone's Back button closes it, and focus moves to its heading.
function openReader(push = true) {
  const split = document.getElementById("split");
  if (!split) return;
  split.classList.add("reading");
  if (push && !location.hash.includes("open")) history.pushState(null, "", "#jobs?open");
  const h1 = document.querySelector("#reader h1");
  if (h1) h1.focus();
}
function closeReader() {
  if (location.hash.includes("open")) history.back();
  else document.getElementById("split").classList.remove("reading");
}

function renderList() {
  const f = state.jobs;
  const rows = visibleJobs();
  if (!rows.some((j) => j.job_url === f.selected)) f.selected = rows.length ? rows[0].job_url : null;
  document.getElementById("jcount").textContent = `${rows.length} of ${f.rows.length}`;
  const list = document.getElementById("jlist");
  list.replaceChildren(...rows.map((j) => jobRow(j)));
  if (!rows.length) list.append(h("li", { class: "empty" }, h("p", {}, "Nothing matches these filters.")));
  renderReader();
}

function jobRow(j) {
  const f = state.jobs;
  const picked = j.status && j.status !== "skipped";
  const flags = [];
  if (j.excluded_reason) flags.push(h("span", { class: "flag" }, j.excluded_reason));
  if (["verified_open", "employer_page_live"].includes(j.verified)) flags.push(h("span", { class: "flag ok" }, "Confirmed open"));
  else if (j.verified === "similar_title_open") flags.push(h("span", { class: "flag" }, "Similar title open: check it's this job"));
  if (j.apply_by) flags.push(h("span", { class: "flag" }, `Apply by ${day(j.apply_by)}`));
  if (j.integrity_note) flags.push(h("span", { class: "flag" }, "Check posting"));
  if (j.repost_note) flags.push(h("span", { class: "flag" }, "Re-listed"));
  const weak = weakParts(j);
  if (weak) flags.push(h("span", { class: "flag quiet" }, weak));
  const li = h("li", { class: "job", role: "option", "aria-selected": String(j.job_url === f.selected), tabindex: j.job_url === f.selected ? "0" : "-1",
    "data-url": j.job_url, onclick: () => select(j.job_url, true),
    onkeydown: (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); select(j.job_url, true); } } },
    h("span", { class: "score" }, j.rank_score !== null && j.rank_score !== undefined ? Math.round(j.rank_score) : "-"),
    h("span", { class: "title" }, picked ? h("span", { class: "hl" }, j.title) : j.title),
    j.status ? h("span", { class: "side" }, h("span", { class: "status" }, STATUS_TEXT[j.status] || j.status)) : null,
    h("span", { class: "meta" }, [j.company, j.location, payText(j)].filter(Boolean).join(", ")),
    flags.length ? h("span", { class: "flags" }, flags) : null);
  return li;
}

function select(url, openOnSmall) {
  state.jobs.selected = url;
  const focusInList = document.activeElement && document.activeElement.closest && document.activeElement.closest("#jlist");
  for (const li of document.querySelectorAll("#jlist .job")) {
    const on = li.dataset.url === url;
    li.setAttribute("aria-selected", String(on));
    li.tabIndex = on ? 0 : -1;
    if (on) { li.scrollIntoView({ block: "nearest" }); if (focusInList) li.focus(); }
  }
  renderReader().then(() => { if (openOnSmall && SMALL()) openReader(); });
}

let readerToken = 0;
async function renderReader() {
  const reader = document.getElementById("reader");
  if (!reader) return;
  const j = state.jobs.rows.find((r) => r.job_url === state.jobs.selected);
  if (!j) { reader.replaceChildren(); return; }
  const mine = ++readerToken;
  const f = state.jobs;
  const verified = VERIFIED_TEXT[j.verified] || "Not checked";
  const gaps = String(j.gaps || "").split(";").map((s) => s.trim()).filter(Boolean);
  const why = String(j.why || "").split(",").map((s) => s.trim()).filter(Boolean);
  const labelBtn = (v, text) => h("button", { class: "btn quiet", "aria-pressed": String(j.label === v), onclick: () => setLabel(j, j.label === v ? "" : v) }, text);
  const inner = h("div", { class: "reader-inner" },
    h("button", { class: "btn quiet back-to-list", onclick: closeReader }, "Back to the list"),
    h("h1", { tabindex: "-1" }, j.status && j.status !== "skipped" ? h("span", { class: "hl" }, j.title) : j.title),
    h("p", { class: "where" }, [j.company, j.location].filter(Boolean).join(", ")),
    j.fit !== undefined && j.fit !== null ? strip(j, f.weights, true) : null,
    h("dl", { class: "facts" },
      j.rank_score !== null && j.rank_score !== undefined ? [h("dt", {}, "Score"), h("dd", {}, `${Math.round(j.rank_score)} of 100`)] : null,
      h("dt", {}, "Pay"), h("dd", {}, payText(j) + (j.pay_estimate && !j.max_amount && !j.min_amount ? " for this kind of job in this area (government data, not this employer's offer)" : "")),
      h("dt", {}, "Employer site"), h("dd", {}, verified),
      j.apply_by ? [h("dt", {}, "Apply by"), h("dd", {}, day(j.apply_by, true))] : null,
      j.date_posted ? [h("dt", {}, "Posted"), h("dd", {}, day(j.date_posted, true))] : null,
      j.status ? [h("dt", {}, "Your status"), h("dd", {}, STATUS_TEXT[j.status] || j.status)] : null),
    j.integrity_note ? h("div", { class: "notice bad" }, h("p", {}, "This posting contains hidden text or lines written for AI tools. Read it yourself before asking Claude to work on it.")) : null,
    h("div", { class: "row actions" },
      jobLink(j) ? h("a", { class: "btn primary", href: jobLink(j), target: "_blank", rel: "noopener noreferrer" }, "Open the posting") : null,
      h("button", { class: "btn", "aria-pressed": String(j.status === "shortlisted"), onclick: () => toggleShortlist(j) },
        j.status === "shortlisted" ? "Shortlisted (undo)" : "Shortlist"),
      h("button", { class: "btn quiet", onclick: () => track(j, "skipped") }, "Skip"),
      h("button", { class: "btn quiet", onclick: () => track(j, "submitted") }, "I applied")),
    h("details", { class: "prompts" }, h("summary", { class: "btn quiet" }, "Ask Claude to..."),
      h("div", { class: "prompt-list" },
        h("p", { class: "small muted" }, "Each button copies a request. Paste it into Claude Code in your job-hunter folder."),
        prompts(j).map(([label, text, what]) => h("button", { class: "btn quiet", onclick: () => copy(text, what) }, label)))),
    f.set === "ranked" ? h("div", { class: "section" }, h("h3", {}, "Would you apply?"),
      h("p", { class: "small muted" }, "Your answers teach the ranking what you like (Stats shows how well it matches you)."),
      h("div", { class: "label-row" }, labelBtn("2", "Yes"), labelBtn("1", "Maybe"), labelBtn("0", "No"))) : null,
    why.length ? h("div", { class: "section" }, h("h3", {}, "Your skills it mentions"), h("p", {}, why.join(", "))) : null,
    gaps.length ? h("div", { class: "section" }, h("h3", {}, "Worth knowing"), h("ul", { class: "list-plain" }, gaps.map((g) => h("li", {}, g)))) : null,
    h("div", { class: "section" }, h("h3", {}, "The posting"), h("p", { class: "posting muted", id: "posting" }, "Loading the posting...")),
    h("p", { class: "keys" }, "Keys: ", h("kbd", {}, "j"), " ", h("kbd", {}, "k"), " move, ", h("kbd", {}, "s"), " shortlist, ",
      h("kbd", {}, "x"), " skip, ", h("kbd", {}, "2"), " ", h("kbd", {}, "1"), " ", h("kbd", {}, "0"), " would you apply, ", h("kbd", {}, "o"), " open"));
  reader.replaceChildren(inner);
  reader.scrollTop = 0;
  try {
    const full = await api(`/api/job?url=${encodeURIComponent(j.job_url)}`);
    if (mine !== readerToken) return;
    const p = document.getElementById("posting");
    p.classList.remove("muted");
    p.textContent = visible(full.description) || (f.set === "ranked" ? "No description was saved for this job. Open the posting to read it."
      : "job-hunter keeps the full text only for the new jobs in your list. Open the posting to read it.");
  } catch (e) {
    if (mine === readerToken) document.getElementById("posting").textContent = e.message;
  }
}

async function toggleShortlist(j) {
  if (j.status !== "shortlisted") return track(j, "shortlisted");
  try {
    await api("/api/untrack", { method: "POST", body: { company: j.company, title: j.title, job_url: j.job_url, employer_url: j.employer_url } });
    j.status = null;
    toast("Taken off the shortlist.");
    renderList();
  } catch (e) { toast(e.message); }
}

async function track(j, status) {
  try {
    await api("/api/track", { method: "POST", body: { status, company: j.company, title: j.title, job_url: j.job_url,
      employer_url: j.employer_url, location: j.location, rank_score: j.rank_score } });
    j.status = status;
    toast({ shortlisted: "Shortlisted.", skipped: "Skipped.", submitted: "Marked as applied." }[status] || "Saved.");
    renderList();
  } catch (e) { toast(e.message); }
}

async function setLabel(j, value) {
  try {
    await api("/api/label", { method: "POST", body: { job_url: j.job_url, label: value } });
    j.label = value || null;
    renderReader();
  } catch (e) { toast(e.message); }
}

function jobKeys(e) {
  if (e.target.closest("input, select, textarea") || e.metaKey || e.ctrlKey || e.altKey) return;
  const rows = visibleJobs();
  const i = rows.findIndex((r) => r.job_url === state.jobs.selected);
  const j = rows[i];
  const k = e.key;
  if ((k === "j" || k === "ArrowDown") && i < rows.length - 1) { e.preventDefault(); select(rows[i + 1].job_url); }
  else if ((k === "k" || k === "ArrowUp") && i > 0) { e.preventDefault(); select(rows[i - 1].job_url); }
  else if (!j) return;
  else if (k === "s") toggleShortlist(j);
  else if (k === "x") track(j, "skipped");
  else if (["0", "1", "2"].includes(k) && state.jobs.set === "ranked") setLabel(j, j.label === k ? "" : k);
  else if (k === "o" && jobLink(j)) window.open(jobLink(j), "_blank", "noopener");
}

// ---------------------------------------------------------------- Search
async function viewSearch() {
  await refreshStatus();
  const s = state.status;
  if (!s.has_profile) { location.hash = "#setup"; return; }
  const sources = s.sources_on || [];
  const pick = new Set();
  const run = (name) => startTask(name, name.startsWith("search") ? [...pick] : []);
  const last = s.last_run || {};
  const srcRows = Object.entries(last.sources || {});
  setMain(
    h("div", { class: "page-head" }, h("h1", {}, "Search"),
      h("p", { class: "muted" }, `Looking for ${Object.values(s.tracks || {}).flat().length} titles in ${(s.locations || []).length} places${s.include_remote ? " and remote" : ""}.`)),
    h("div", { class: "row" },
      h("button", { class: "btn primary", id: "run-search", onclick: () => run(document.getElementById("fast").checked ? "search-no-verify" : "search") }, "Run search"),
      h("button", { class: "btn", id: "run-rank", onclick: () => run("rank") }, "Re-rank the last results"),
      h("button", { class: "btn quiet", id: "stop", onclick: stopTask, hidden: true }, "Stop")),
    h("p", { class: "check small", style: "margin-top: 12px" }, h("input", { type: "checkbox", id: "fast" }),
      h("label", { for: "fast" }, "Skip checking employers' sites (faster, but nothing gets confirmed open)")),
    h("details", {}, h("summary", { class: "small" }, "Only search some sources"),
      h("p", { class: "small muted" }, "Leave all unticked to search everything that's on."),
      h("div", { class: "row" }, sources.map((src) => h("label", { class: "check small" },
        h("input", { type: "checkbox", onchange: (e) => (e.target.checked ? pick.add(src) : pick.delete(src)) }), nameOf(src))))),
    h("p", { class: "small muted" }, "A full search takes 10 to 30 minutes. You can leave this page and come back."),
    h("pre", { class: "log", id: "log", "aria-live": "polite" }, s.task && s.task.name ? "" : "Output from the search shows here."),
    srcRows.length ? h("div", { class: "section" }, h("h2", {}, "Last search"),
      h("p", {}, `${last.scored ?? 0} jobs scored, ${last.new ?? 0} new, ${last.excluded ?? 0} excluded.`),
      (last.health_warnings || []).length ? h("div", { class: "notice" }, h("p", {}, "Sources that may have stopped working:"),
        h("ul", { class: "list-plain" }, last.health_warnings.map((w) => h("li", {}, w)))) : null,
      h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, "Source"), h("th", { class: "num" }, "Jobs"), h("th", { class: "num" }, "Failed requests"), h("th", { class: "num" }, "Seconds"))),
        h("tbody", {}, srcRows.map(([name, v]) => h("tr", {}, h("td", {}, nameOf(name)), h("td", { class: "num" }, v.rows), h("td", { class: "num" }, v.errors || ""),
          h("td", { class: "num" }, Math.round(v.seconds || 0))))))) : null);
  state.taskSince = 0;
  pollTask();
}

async function startTask(name, sources = []) {
  try {
    await api("/api/task", { method: "POST", body: { name, sources } });
    state.taskSince = 0;
    const log = document.getElementById("log");
    if (log) log.textContent = "";
    toast(`${taskLabel(name)} started.`);
    refreshStatus();
    pollTask();
  } catch (e) { toast(e.message); }
}

async function stopTask() {
  try { const r = await api("/api/task/stop", { method: "POST", body: {} }); toast(r.stopped ? "Stopping." : "Nothing is running."); }
  catch (e) { toast(e.message); }
}

async function pollTask() {
  clearTimeout(state.taskTimer);
  const log = document.getElementById("log");
  let t;
  try { t = await api(`/api/task?since=${state.taskSince}`); } catch { return; }
  if (log && t.lines.length) {
    const atBottom = log.scrollHeight - log.scrollTop - log.clientHeight < 40;
    for (const line of t.lines) log.append(h("span", { class: line.trimStart().startsWith("!") ? "warn" : "" }, line + "\n"));
    if (atBottom) log.scrollTop = log.scrollHeight;
  }
  state.taskSince = t.next;
  for (const id of ["run-search", "run-rank"]) { const b = document.getElementById(id); if (b) b.disabled = t.running; }
  const stop = document.getElementById("stop");
  if (stop) stop.hidden = !t.running;
  if (t.running) state.taskTimer = setTimeout(pollTask, 1000);
  else if (t.name && t.finished && log && !log.dataset.done) {
    log.dataset.done = "1";
    log.append(h("span", {}, t.returncode === 0 ? "\nFinished.\n" : `\nStopped with an error (code ${t.returncode}). The lines above say why.\n`));
    refreshStatus();
  }
}

// ---------------------------------------------------------------- Applications
const STATUS_ORDER = ["offer", "interviewing", "ready_for_review", "needs_account", "tailored", "shortlisted", "submitted", "rejected", "skipped"];

async function viewApplications() {
  const data = await api("/api/applications");
  const timers = {};
  // A status menu changed with the arrow keys fires on every step; save once it settles.
  const save = (a, status) => {
    clearTimeout(timers[a.id]);
    timers[a.id] = setTimeout(async () => {
      try {
        await api("/api/track", { method: "POST", body: { status, company: a.company, title: a.title, job_url: a.job_url, employer_url: a.employer_url } });
        a.status = status; toast(`${a.company}: ${STATUS_TEXT[status] || status}.`);
      } catch (err) { toast(err.message); }
    }, 700);
  };
  const card = (a) => h("li", { class: "app-card" },
    h("div", { class: "app-main" }, h("b", {}, a.title), h("span", { class: "muted" }, ` at ${a.company}`),
      h("div", { class: "small muted" }, [a.updated ? `Updated ${day(String(a.updated).slice(0, 10))}` : "", a.source ? `found on ${nameOf(a.source)}` : ""]
        .filter(Boolean).join(", "))),
    h("div", { class: "app-actions row" },
      h("label", { class: "visually-hidden", for: `st-${a.id}` }, `Status for ${a.title} at ${a.company}`),
      h("select", { id: `st-${a.id}`, onchange: (e) => save(a, e.target.value) },
        data.statuses.map((s) => h("option", { value: s, selected: s === a.status }, STATUS_TEXT[s] || s))),
      safeUrl(a.employer_url || a.job_url) ? h("a", { href: safeUrl(a.employer_url || a.job_url), target: "_blank", rel: "noopener noreferrer" }, "Posting") : null));
  const groups = STATUS_ORDER.map((st) => [st, data.applications.filter((a) => a.status === st)]).filter(([, rows]) => rows.length);
  setMain(
    h("div", { class: "page-head" }, h("h1", {}, "Applications"),
      h("p", { class: "muted" }, data.applications.length ? `${data.applications.length} jobs you've acted on.` : "")),
    groups.length ? groups.map(([st, rows]) => h("section", { class: "app-group" }, h("h2", {}, `${STATUS_TEXT[st] || st} (${rows.length})`),
      h("ul", { class: "app-list" }, rows.map(card))))
      : h("div", { class: "empty" }, h("p", {}, "Nothing tracked yet. Shortlist jobs on the Jobs page and they show up here."),
        h("a", { class: "btn primary", href: "#jobs" }, "Go to jobs")),
    data.waiting.length ? h("div", { class: "section" }, h("h2", {}, "No answer in three weeks"),
      h("p", { class: "muted" }, "A short follow-up can help. Claude drafts it; you decide whether to send it."),
      h("ul", { class: "list-plain" }, data.waiting.map((w) => h("li", {}, `${w.company}, ${w.title} (${w.days} days) `,
        h("button", { class: "btn quiet", onclick: () => copy(`Draft a follow-up for my ${oneLine(w.title, 120)} application at ${oneLine(w.company, 80)}.`, "draft the follow-up") },
          "Copy follow-up request"))))) : null);
}

// ---------------------------------------------------------------- Companies
async function viewCompanies() {
  const data = await api("/api/companies");
  const msg = h("p", { class: "small", "aria-live": "polite" });
  const change = async (body) => {
    msg.textContent = body.action === "remove" ? "Removing..." : "Looking it up. This can take a few seconds...";
    try { const r = await api("/api/companies", { method: "POST", body }); toast(r.message); await viewCompanies(); }
    catch (e) { msg.textContent = e.message; msg.className = "small error-text"; }
  };
  const name = h("input", { type: "text", id: "cname", class: "wide", placeholder: "Acme Health" });
  const url = h("input", { type: "url", id: "curl", class: "wide", placeholder: "https://careers.acme.com (optional)" });
  const track = h("select", { id: "ctrack" }, h("option", { value: "" }, "Closest title"), data.tracks.map((t) => h("option", { value: t }, t)));
  const burl = h("input", { type: "url", id: "burl", class: "wide", placeholder: "https://..." });
  const bname = h("input", { type: "text", id: "bname", class: "wide", placeholder: "A label (optional)" });
  setMain(
    h("div", { class: "page-head" }, h("h1", {}, "Companies and boards"),
      h("p", { class: "muted" }, "Employers' career sites get searched every run. Boards the script can't read go on a list Claude checks for you.")),
    h("div", { class: "section", style: "margin-top: 0" }, h("h2", {}, "Find employers that hire for your titles"),
      h("p", {}, "Uses your last search to find employers posting jobs like yours, and checks which have a career site job-hunter can read."),
      h("div", { class: "row" },
        h("button", { class: "btn", onclick: () => { startTask("discover"); location.hash = "#search"; } }, "Show me the list"),
        h("button", { class: "btn quiet", onclick: () => { startTask("discover-add"); location.hash = "#search"; } }, "Find and add them all"))),
    h("div", { class: "section" }, h("h2", {}, "Add a company"),
      h("form", { class: "stack", onsubmit: (e) => { e.preventDefault(); change({ action: "add-company", name: name.value, url: url.value, track: track.value }); } },
        h("div", {}, h("label", { class: "field", for: "cname" }, "Company name"), name),
        h("div", {}, h("label", { class: "field", for: "curl" }, "Careers page"), h("span", { class: "hint" }, "If you have it. Otherwise job-hunter looks the company up by name."), url),
        h("div", {}, h("label", { class: "field", for: "ctrack" }, "Which of your searches its jobs belong to"), track),
        h("button", { class: "btn primary", type: "submit" }, "Add company"), msg)),
    h("div", { class: "section" }, h("h2", {}, `Career sites searched every run (${data.companies.length})`),
      data.companies.length ? h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, "Company"), h("th", {}, "System"), h("th", {}, "Note"), h("th", {}, ""))),
        h("tbody", {}, data.companies.map((c) => h("tr", {}, h("td", {}, c.name), h("td", { class: "small" }, c.ats),
          h("td", { class: "small muted" }, c.note || (c.source === "discovered" ? "Found from your search" : "")),
          h("td", {}, h("button", { class: "btn quiet", onclick: () => change({ action: "remove", name: c.name }) }, `Remove`))))))
        : h("p", { class: "muted" }, "None yet. Add one above, or find them from your last search.")),
    h("div", { class: "section" }, h("h2", {}, "Boards to check by hand"),
      h("form", { class: "stack", onsubmit: (e) => { e.preventDefault(); change({ action: "add-board", url: burl.value, name: bname.value }); } },
        h("div", {}, h("label", { class: "field", for: "burl" }, "Board or careers page URL"),
          h("span", { class: "hint" }, "If it's a career site job-hunter can read, it joins the daily search instead."), burl),
        h("div", {}, h("label", { class: "field", for: "bname" }, "Label"), bname),
        h("button", { class: "btn", type: "submit" }, "Add board")),
      data.boards.length ? h("ul", { class: "list-plain", style: "margin-top: 16px" }, data.boards.map((b) => h("li", {},
        safeUrl(b.url) ? h("a", { href: b.url, target: "_blank", rel: "noopener noreferrer" }, b.name || b.url) : (b.name || b.url), " ",
        h("button", { class: "btn quiet", onclick: () => change({ action: "remove", url: b.url }) }, "Remove")))) : null));
}

// ---------------------------------------------------------------- Stats
async function viewStats() {
  const s = await api("/api/stats");
  const pct = (x) => (x === null || x === undefined ? "-" : `${Math.round(x * 100)}%`);
  const o = s.overall;
  const group = (title, rows) => h("div", { class: "section" }, h("h2", {}, title),
    h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, ""), h("th", { class: "num" }, "Sent"), h("th", { class: "num" }, "Heard back"), h("th", { class: "num" }, "Interviews"))),
      h("tbody", {}, Object.entries(rows).map(([k, g]) => h("tr", {}, h("td", {}, nameOf(k)), h("td", { class: "num" }, g.sent),
        h("td", { class: "num" }, pct(g.response_rate)), h("td", { class: "num" }, pct(g.interview_rate)))))));
  const rc = s.ranking_check;
  setMain(
    h("div", { class: "page-head" }, h("h1", {}, "How it's going")),
    o.sent ? h("p", { style: "font-size: var(--t-h3)" }, `${o.sent} applications sent. ${o.responses} heard back (${pct(o.response_rate)}), ${o.interviews} led to interviews (${pct(o.interview_rate)}).`)
      : h("div", { class: "empty" }, h("p", {}, "Nothing sent yet. When you mark jobs as applied, response rates show here.")),
    o.sent && o.sent < 20 ? h("p", { class: "notice" }, `With ${o.sent} applications, differences between the groups below are mostly chance.`) : null,
    o.sent ? Object.entries(s.by).map(([k, rows]) => group(`By ${k}`, rows)) : null,
    h("div", { class: "section" }, h("h2", {}, "Does the ranking match your judgment?"),
      rc ? h("p", {}, `Of your top 10 by score, ${rc.apply_in_top10} are jobs you said you'd apply to (from ${rc.labeled} you've rated).`)
        : h("p", {}, "Rate jobs on the Jobs page (Yes, Maybe, No). After about 50, this shows how well the order matches you."),
      rc && rc.labeled < 30 ? h("p", { class: "small muted" }, "Under 30 rated jobs, treat this as rough.") : null,
      h("p", { class: "small muted" }, "To have it suggest better weights, run: job-hunter eval-rank --tune")));
}

// ---------------------------------------------------------------- Setup: one question per page
const SETUP_LABELS = {
  resume: "Your resume", field: "Kind of work", titles: "Job titles", adjacent_titles: "Other titles", pivot_titles: "Career change titles",
  levels: "Levels", years_experience: "Years of experience", skills: "Skills", locations: "Cities", remote: "Remote",
  remote_like_top_city: "Remote ranks with your first city", pay_floor: "Lowest pay", pay_target: "Target pay",
  avoid_companies: "Companies to skip", avoid_keywords: "Words that rule a job out", target_companies: "Companies you'd like",
  discover_companies: "Find more companies",
};

async function viewSetup() {
  const st = state.setup;
  if (!st.questions.length) {
    const info = await api("/api/setup");
    st.questions = info.questions;
    st.hasProfile = info.has_profile;
    if (info.has_profile && !Object.keys(st.answers).length) st.answers = { ...(info.current || {}) };
  }
  renderSetup();
}

function answerText(q, v) {
  if (v === undefined || v === null || v === "" || (Array.isArray(v) && !v.length)) return "Not answered";
  if (q.kind === "bool") return v ? "Yes" : "No";
  if (Array.isArray(v)) return v.join(q.kind === "cities" ? "; " : ", ");
  return String(v);
}

function renderSetup() {
  const st = state.setup;
  const qs = st.questions;
  if (st.step >= qs.length) return renderSetupReview();
  const q = qs[st.step];
  const val = st.answers[q.key];
  const id = `q-${q.key}`;
  const [promptMain, ...promptRest] = q.prompt.split("\n");
  let input;
  const extras = [];
  if (q.kind === "path") {
    input = h("input", { type: "file", id, accept: ".pdf,.docx,.txt,.md" });
    if (val) extras.push(h("p", { class: "notice ok" }, `Uploaded. Saved as ${val} in your folder.`));
  } else if (q.kind === "bool") {
    const cur = val === undefined ? (q.default || "").startsWith("y") : val;
    input = h("div", { class: "stack", role: "radiogroup", "aria-labelledby": `${id}-h` },
      h("label", { class: "check" }, h("input", { type: "radio", name: id, value: "yes", checked: cur === true }), "Yes"),
      h("label", { class: "check" }, h("input", { type: "radio", name: id, value: "no", checked: cur === false }), "No"));
  } else if (["list", "levels", "cities"].includes(q.kind)) {
    input = h("textarea", { id, rows: "4" }, Array.isArray(val) ? val.join(q.kind === "cities" ? "\n" : ", ") : val || "");
  } else {
    input = h("input", { type: "text", id, class: "wide", value: val ?? "" });
  }
  const hint = {
    titles: "Separate them with commas. These are what get searched, so use the titles employers post.",
    adjacent_titles: "Same skills, different seat. Optional.",
    pivot_titles: "Optional. Jobs in a new direction you'd consider.",
    resume: "A PDF, Word or text file. Optional, but ranking works much better with it. It stays in your folder.",
    field: "In your own words, like hospital nursing, B2B software sales, or commercial real estate lending.",
    years_experience: "In this kind of work. A number is fine.",
    remote: "Remote jobs get searched alongside your cities.",
    remote_like_top_city: "Yes means a remote job scores as well as one in your first city.",
    discover_companies: "After your first search, job-hunter can find employers hiring for these roles and add their career sites.",
    levels: "Any of: intern, entry, mid, senior, manager, director, vp, executive.",
    skills: "Worded the way job postings say them. Separate with commas.",
    locations: "One per line, best first, like Chicago, IL.",
    pay_floor: "Per year, like 85k. Leave blank to skip.", pay_target: "Per year, like 110k. Leave blank to skip.",
    avoid_companies: "Like your current employer. Separate with commas.",
    avoid_keywords: "Like a kind of role you won't do. Separate with commas.",
    target_companies: "Their career sites get searched every run. Separate with commas.",
  }[q.key] || promptRest.join(" ").trim();

  if ((q.key === "adjacent_titles" || q.key === "skills") && st.suggestions) {
    const opts = q.key === "skills" ? st.suggestions.skills : st.suggestions.related_titles.map((r) => r.title);
    if (opts.length) {
      extras.push(h("p", { class: "small muted" }, q.key === "skills"
        ? "Skills postings in these occupations often ask for. Tap to add:" : "Titles in related occupations. Tap to add:"));
      extras.push(h("div", { class: "chips" }, opts.map((o) => h("button", { type: "button", class: "chip",
        "aria-pressed": String(splitList(input.value).includes(o)),
        onclick: (e) => {
          const cur = splitList(input.value);
          const on = cur.includes(o);
          input.value = (on ? cur.filter((x) => x !== o) : [...cur, o]).join(", ");
          e.target.setAttribute("aria-pressed", String(!on));
        } }, o))));
      extras.push(h("p", { class: "small muted" }, st.suggestions.attribution));
    }
  }

  const errorP = h("p", { class: "error-text", role: "alert" });
  const read = async () => {
    if (q.kind === "path") {
      const file = input.files && input.files[0];
      if (!file) return st.answers[q.key] || "";
      const r = await api("/api/setup/resume", { method: "POST", raw: true, body: file,
        headers: { "X-Filename": encodeURIComponent(file.name), "Content-Type": "application/octet-stream" } });
      return r.path;
    }
    if (q.kind === "bool") {
      const picked = main.querySelector(`input[name="${id}"]:checked`);
      return picked ? picked.value === "yes" : undefined;
    }
    if (q.kind === "cities") return input.value.split("\n").map((s) => s.trim()).filter(Boolean);
    if (q.kind === "list" || q.kind === "levels") return splitList(input.value);
    return input.value.trim();
  };
  const next = async (e) => {
    e.preventDefault();
    try {
      const v = await read();
      if (q.key === "titles" && !v.length) { errorP.textContent = "Add at least one job title. That's what gets searched."; return; }
      st.answers[q.key] = v;
      if (q.key === "titles" || q.key === "adjacent_titles") {
        try { st.suggestions = await api("/api/setup/suggest", { method: "POST", body: { titles: [...(st.answers.titles || []), ...(st.answers.adjacent_titles || [])] } }); }
        catch { st.suggestions = null; }
      }
      st.step = st.returnToReview ? qs.length : st.step + 1;
      st.returnToReview = false;
      renderSetup();
      main.focus();
    } catch (err) { errorP.textContent = err.message; }
  };
  setMain(h("form", { class: "wizard", onsubmit: next },
    st.hasProfile && st.step === 0 ? h("div", { class: "notice" },
      h("p", {}, "You already have a search set up, so your current answers are filled in. Change what you like."),
      h("p", {}, "Finishing replaces your search settings (the old ones are kept as profile.yaml.bak). Details setup doesn't ask about, like your name, contact and past titles, are kept; the old candidate.yaml is saved as candidate.yaml.bak.")) : null,
    h("p", { class: "progress" }, `Question ${st.step + 1} of ${qs.length}`),
    h("h1", { id: `${id}-h` }, h("label", { for: id }, SETUP_LABELS[q.key] || promptMain)),
    h("span", { class: "hint" }, hint || promptMain),
    input, extras, errorP,
    h("div", { class: "row nav" },
      st.step > 0 ? h("button", { type: "button", class: "btn quiet", onclick: async () => {
        if (q.kind !== "path") { try { st.answers[q.key] = await read(); } catch { /* keep the old answer */ } }
        st.step -= 1; renderSetup();
      } }, "Back") : null,
      h("button", { type: "submit", class: "btn primary" }, st.returnToReview ? "Save and go back to the summary" : "Continue"),
      q.key !== "titles" ? h("button", { type: "button", class: "btn quiet", onclick: () => { st.step = st.returnToReview ? qs.length : st.step + 1; st.returnToReview = false; renderSetup(); } }, "Skip") : null)));
  const first = main.querySelector("input, textarea");
  if (first && q.kind !== "bool") first.focus();
}

function renderSetupReview() {
  const st = state.setup;
  const errorP = h("p", { class: "error-text", role: "alert" });
  const submit = async (force) => {
    try {
      const r = await api("/api/setup", { method: "POST", body: { answers: st.answers, force } });
      state.setup = { step: 0, answers: {}, questions: [], suggestions: null };
      await refreshStatus();
      setMain(h("div", { class: "wizard stack" }, h("h1", {}, "Your search is set up"),
        r.messages.length ? h("ul", { class: "list-plain" }, r.messages.map((m) => h("li", {}, m.trim()))) : null,
        (() => {
          const off = r.problems.filter((p) => /^source \w+: off/.test(p)).map((p) => p.split(":")[0].replace("source ", ""));
          const rest = r.problems.filter((p) => !/^source \w+: off/.test(p));
          return [
            rest.length ? h("div", { class: "notice" }, h("p", {}, "Worth a look:"), h("ul", { class: "list-plain" }, rest.map((p) => h("li", {}, p)))) : null,
            off.length ? h("p", { class: "small muted" }, `More job sources (${off.join(", ")}) turn on with a free API key in your .env file. The README says where to get them.`) : null,
          ];
        })(),
        h("p", {}, "Next, run your first search. It takes 10 to 30 minutes."),
        state.status && state.status.folder ? h("p", { class: "small muted" }, `Your files are in ${state.status.folder}`) : null,
        h("div", { class: "row" }, h("a", { class: "btn primary", href: "#search" }, "Go to search"))));
    } catch (e) {
      if (e.status === 409 && !force) {
        errorP.replaceChildren(document.createTextNode("You already have a profile. "),
          h("button", { class: "btn", type: "button", onclick: () => submit(true) }, "Replace it (the old one is kept as a backup)"));
      } else errorP.textContent = e.message;
    }
  };
  setMain(h("div", { class: "wizard" },
    h("h1", {}, "Check your answers"),
    h("dl", { class: "answers" }, st.questions.map((q, i) => h("div", {},
      h("dt", {}, SETUP_LABELS[q.key] || q.key), h("dd", {}, answerText(q, st.answers[q.key])),
      h("dd", {}, h("button", { class: "btn quiet", type: "button", onclick: () => { st.step = i; st.returnToReview = true; renderSetup(); } },
        h("span", {}, "Change"), h("span", { class: "visually-hidden" }, ` ${SETUP_LABELS[q.key] || q.key}`)))))),
    errorP,
    h("div", { class: "row nav" }, h("button", { class: "btn primary", type: "button", onclick: () => submit(st.hasProfile) }, "Create my search"))));
}

// ---------------------------------------------------------------- Settings
async function viewSettings() {
  let s;
  try { s = await api("/api/settings"); }
  catch (e) {
    setMain(h("div", { class: "empty" }, h("p", {}, e.message), h("a", { class: "btn primary", href: "#setup" }, "Start setup")));
    return;
  }
  const w = s["ranking.weights"] || {};
  const num = (id, v) => h("input", { type: "number", id, value: v ?? "", min: "0", step: "1", style: "width: 8ch" });
  const weights = Object.fromEntries(["fit", "seniority", "location", "pay", "freshness"].map((k) => [k, num(`w-${k}`, w[k])]));
  const sum = h("span", { class: "small muted" });
  const updateSum = () => { sum.textContent = `Total ${Object.values(weights).reduce((t, el) => t + (Number(el.value) || 0), 0)} (they're relative; 100 is easiest to read)`; };
  Object.values(weights).forEach((el) => el.addEventListener("input", updateSum));
  updateSum();
  const box = (id, v) => h("input", { type: "checkbox", id, checked: !!v });
  const floor = h("input", { type: "number", id: "floor", value: s["ranking.pay_floor"] ?? "", min: "0", step: "1000", style: "width: 12ch" });
  const target = h("input", { type: "number", id: "target", value: s["ranking.pay_target"] ?? "", min: "0", step: "1000", style: "width: 12ch" });
  const hardFloor = box("hardfloor", s["ranking.pay_floor_is_hard"] ?? true);
  const estimates = box("estimates", s["ranking.pay_estimates"] ?? true);
  const sponsor = box("sponsor", s["filters.needs_sponsorship"]);
  const remote = box("remote", s["search.include_remote"] ?? true);
  const verify = box("verify", s["verify.enabled"] ?? true);
  const topn = num("topn", s["verify.top_n"] ?? 150);
  const exCo = h("textarea", { id: "exco" }, (s["filters.exclude_companies"] || []).join("\n"));
  const exKw = h("textarea", { id: "exkw" }, (s["filters.exclude_keywords"] || []).join("\n"));
  const sources = Object.entries(s.sources || {}).map(([k, v]) => [k, h("select", { id: `src-${k}`, "data-label": nameOf(k) },
    [["on", true], ["off", false], ["when its key is set", "auto"]].map(([label, val]) => h("option", { value: JSON.stringify(val), selected: v === val }, label)))]);
  const err = h("p", { class: "error-text", role: "alert" });
  const save = async (e) => {
    e.preventDefault();
    const body = {
      "ranking.weights": Object.fromEntries(Object.entries(weights).map(([k, el]) => [k, Number(el.value) || 0])),
      "ranking.pay_floor": floor.value === "" ? null : Number(floor.value), "ranking.pay_target": target.value === "" ? null : Number(target.value),
      "ranking.pay_floor_is_hard": hardFloor.checked, "ranking.pay_estimates": estimates.checked,
      "filters.needs_sponsorship": sponsor.checked, "search.include_remote": remote.checked,
      "verify.enabled": verify.checked, "verify.top_n": Number(topn.value) || 150,
      "filters.exclude_companies": exCo.value.split("\n").map((x) => x.trim()).filter(Boolean),
      "filters.exclude_keywords": exKw.value.split("\n").map((x) => x.trim()).filter(Boolean),
      sources: Object.fromEntries(sources.map(([k, el]) => [k, JSON.parse(el.value)])),
    };
    try { const r = await api("/api/settings", { method: "POST", body }); err.textContent = ""; toast(`Saved. The previous version is in ${r.backup}. Re-rank or search to see the effect.`); }
    catch (ex) { err.textContent = ex.message; }
  };
  const fieldRow = (label, control, hint) => h("div", {}, h("label", { class: "field", for: control.id }, label), hint ? h("span", { class: "hint" }, hint) : null, control);
  const checkRow = (control, label, hint) => h("div", { class: "check" }, control, h("label", { for: control.id }, label, hint ? h("span", { class: "hint" }, hint) : null));
  setMain(h("form", { class: "stack", onsubmit: save, style: "max-width: 70ch" },
    h("div", { class: "page-head" }, h("h1", {}, "Settings"),
      h("p", { class: "muted" }, "The rest of your search (titles, places, skills) is in profile.yaml, or run Setup again."),
      state.status && state.status.folder ? h("p", { class: "small muted" }, `Your files are in ${state.status.folder}`) : null),
    h("h2", {}, "Pay"),
    h("div", { class: "row" }, fieldRow("Lowest pay", floor, "Per year"), fieldRow("Target pay", target, "Per year")),
    checkRow(hardFloor, "Drop jobs that post pay under the lowest", "Jobs that don't post pay are kept."),
    checkRow(estimates, "Estimate pay when a job doesn't post it", "From government data for the occupation and area. Counts at half strength, never drops a job."),
    h("h2", {}, "What matters in the score"),
    h("div", { class: "row" }, Object.entries(weights).map(([k, el]) => fieldRow({ fit: "Fit", seniority: "Level", location: "Place", pay: "Pay", freshness: "Freshness" }[k], el))),
    sum,
    h("h2", {}, "Filters"),
    fieldRow("Companies to skip", exCo, "One per line."),
    fieldRow("Words that rule a job out", exKw, "One per line. Checked in the title and the start of the description."),
    checkRow(sponsor, "I need visa sponsorship", "Drops postings that say they won't sponsor or need U.S. citizenship or a clearance."),
    checkRow(remote, "Include remote jobs"),
    h("h2", {}, "Checking employers' sites"),
    checkRow(verify, "Confirm jobs on the employer's own site"),
    fieldRow("How many of the top jobs to check", topn),
    h("h2", {}, "Sources"),
    h("div", { class: "row" }, sources.map(([k, el]) => fieldRow(nameOf(k), el))),
    err,
    h("div", { class: "row" }, h("button", { class: "btn primary", type: "submit" }, "Save settings"))));
}

// ---------------------------------------------------------------- start
function needKey() {
  setMain(h("div", { class: "notice" },
    h("h1", {}, "Open job-hunter from its Start file"),
    h("p", {}, "For your privacy this page only works when job-hunter opens it. Double-click Start job-hunter "
      + "(or the job-hunter shortcut on your desktop) and it will open a working page.")));
}

if (!TOKEN) needKey();
else {
  window.addEventListener("hashchange", route);
  refreshStatus().then(route);
  setInterval(refreshStatus, 15000);
}
