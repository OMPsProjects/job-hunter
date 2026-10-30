"""LinkedIn read by Claude in the person's browser, kept small and within a token budget.

job-hunter can't see Claude's token meter while Claude works, so the budget is kept two ways:
- before: `job-hunter linkedin plan` hands out only as many searches and job descriptions as the
  day's and the week's budget leave room for (estimated from what earlier runs really used), and
  records them as spent, so asking twice doesn't get more;
- after: `job-hunter linkedin usage` reads Claude Code's own record of the LinkedIn helper's run
  (~/.claude/projects/.../subagents/) and replaces the estimate with what it really used.

"Tokens" here are counted the way they cost: new input + output + cache writes, plus a tenth of
cache reads (re-reading the same conversation each step is billed at about a tenth).

profile.yaml:
    linkedin:
      daily_tokens: 150000
      weekly_tokens: 600000
      max_searches: 6          # per day
      max_descriptions: 15     # per day; 0 = titles only (cheapest)
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import statistics
import uuid
from pathlib import Path
from urllib.parse import urlencode

DEFAULTS = {"daily_tokens": 150_000, "weekly_tokens": 600_000, "max_searches": 6, "max_descriptions": 15}
# Starting estimates until real runs are measured [rough: a small helper on a fast model, reading
# pages with one script per search instead of screenshots]
EST = {"session": 25_000, "search": 15_000, "description": 3_000}
AGENT_LABEL = "job-hunter LinkedIn read"
MAX_TITLES_PER_SEARCH = 4
LEVEL_CODES = {"intern": "1", "entry": "2", "associate": "3", "mid": "4", "senior": "4", "lead": "4",
               "manager": "4", "director": "5", "vp": "6", "executive": "6"}


def settings(p) -> dict:
    s = dict(DEFAULTS)
    s.update({k: v for k, v in (p.raw.get("linkedin") or {}).items() if k in DEFAULTS and v is not None})
    return s


def ledger_path(p) -> Path:
    return p.resolve(p.output_dir or "results") / "linkedin_usage.json"


def load_ledger(p) -> dict:
    try:
        data = json.loads(ledger_path(p).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) and isinstance(data.get("sessions"), list) else {"sessions": []}
    except (OSError, ValueError):
        return {"sessions": []}


def save_ledger(p, data: dict) -> None:
    path = ledger_path(p)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def scale(ledger: dict) -> float:
    """How far off the estimates have been: median of measured / estimated over recent runs."""
    ratios = [s["measured"] / s["estimated"] for s in ledger["sessions"][-10:]
              if s.get("measured") and s.get("estimated")]
    return min(4.0, max(0.25, statistics.median(ratios))) if ratios else 1.0


def estimate(searches: int, descriptions: int, k: float = 1.0) -> int:
    if not searches:
        return 0
    return int(k * (EST["session"] + EST["search"] * searches + EST["description"] * descriptions))


def spent(ledger: dict, since: dt.date, until: dt.date) -> int:
    return sum(s.get("measured") or s.get("estimated") or 0 for s in ledger["sessions"]
               if since <= dt.date.fromisoformat(s["date"]) <= until)


def status(p, today: dt.date | None = None) -> dict:
    today = today or dt.date.today()
    cfg, led = settings(p), load_ledger(p)
    day, week = spent(led, today, today), spent(led, today - dt.timedelta(days=6), today)
    return {"today": day, "week": week, "daily_tokens": cfg["daily_tokens"], "weekly_tokens": cfg["weekly_tokens"],
            "left": max(0, min(cfg["daily_tokens"] - day, cfg["weekly_tokens"] - week)),
            "measured_runs": sum(1 for s in led["sessions"] if s.get("measured")), "scale": round(scale(led), 2)}


# ---------------------------------------------------------------- the day's searches

def _window(p, ledger: dict, today: dt.date) -> str:
    """LinkedIn's posted-within filter: only what's new since the last LinkedIn run."""
    last = max((dt.date.fromisoformat(s["date"]) for s in ledger["sessions"] if s.get("searches")), default=None)
    days = (today - last).days if last else p.hours_old / 24
    if days <= 1:
        return "r86400"
    if days <= 7:
        return "r604800"
    return "r1209600" if days <= 14 else "r2592000"


def _keywords(titles) -> str:
    """Several titles in one search: LinkedIn job search takes quoted phrases joined by OR."""
    return " OR ".join(f'"{t}"' for t in titles) if len(titles) > 1 else titles[0]


def searches(p, window: str, levels=()) -> list[dict]:
    """One search per place (all core titles together), then the other tracks' titles, remote last."""
    groups = []
    for _track, titles in p.tracks.items():
        titles = [t for t in titles if t]
        for i in range(0, len(titles), MAX_TITLES_PER_SEARCH):
            groups.append(titles[i:i + MAX_TITLES_PER_SEARCH])
    places: list[tuple[str, dict]] = [] if p.remote_only else [(loc, {}) for loc in p.locations]
    if p.include_remote:
        places.append(("United States", {"f_WT": "2"}))
    codes = sorted({LEVEL_CODES[lv] for lv in levels if lv in LEVEL_CODES})
    out = []
    for gi, titles in enumerate(groups):
        for loc, extra in places:
            q = {"keywords": _keywords(titles), "location": loc, "f_TPR": window, "sortBy": "DD", **extra}
            if codes:
                q["f_E"] = ",".join(codes)
            out.append({"key": f"{'|'.join(titles)}@{loc}", "titles": titles, "place": loc, "group": gi,
                        "url": "https://www.linkedin.com/jobs/search/?" + urlencode(q)})
    return out


def title_words(p) -> list[str]:
    """Words a card's title needs one of before its description is worth reading."""
    stop = {"and", "of", "the", "for", "in", "senior", "sr", "junior", "jr", "lead", "manager", "director", "vp",
            "vice", "president", "associate", "assistant", "i", "ii", "iii", "iv", "&", "-", "/"}
    words = {w for _, t in p.all_titles() for w in re.findall(r"[a-z][a-z0-9+#]+", t.lower()) if w not in stop}
    return sorted(words)


def page_script(per: int, words) -> str:
    """The page-reading script with this run's settings filled in, comments and indentation removed
    (Claude sends it once per search, so every character costs)."""
    from importlib.resources import files
    src = (files("jobhunter") / "data" / "linkedin_page.js").read_text(encoding="utf-8")
    lines = [ln.strip() for ln in src.splitlines()]
    code = "\n".join(ln for ln in lines if ln and not ln.startswith("//"))
    return code.replace("__PARAMS__", json.dumps({"per": per, "w": list(words)}, separators=(",", ":")))


def plan(p, levels=(), today: dt.date | None = None) -> dict:
    """Today's LinkedIn work within budget; recorded as spent. allowed=False when there's no room."""
    today = today or dt.date.today()
    cfg, led = settings(p), load_ledger(p)
    k = scale(led)
    st = status(p, today)
    left = st["left"]
    all_s = searches(p, _window(p, led, today), levels)
    room = int((left / k - EST["session"]) // EST["search"]) if left > estimate(1, 0, k) else 0
    n = min(len(all_s), cfg["max_searches"], max(0, room))
    if n <= 0:
        return {"allowed": False, "reason": _no_room(st), "status": st}
    # least recently run first, so a long list rotates through over the days
    last_run = led.get("last_run") or {}
    order = sorted(all_s, key=lambda s: (last_run.get(s["key"], ""), s["group"]))
    chosen = order[:n]
    d_room = int((left / k - EST["session"] - EST["search"] * n) // EST["description"])
    d = max(0, min(cfg["max_descriptions"], d_room))
    per = -(-d // n) if d else 0  # spread over the searches, rounded up
    sid = uuid.uuid4().hex[:8]
    est = estimate(n, d, k)
    for s in chosen:
        last_run[s["key"]] = today.isoformat()
    led["last_run"] = last_run
    led["sessions"].append({"id": sid, "date": today.isoformat(), "searches": n, "descriptions": d, "estimated": est})
    save_ledger(p, led)
    return {"allowed": True, "session": sid, "agent_description": f"{AGENT_LABEL} {sid}",
            "searches": [{"url": s["url"], "query": " / ".join(s["titles"]), "place": s["place"]} for s in chosen],
            "descriptions_per_search": per, "script": page_script(per, title_words(p)),
            "estimated_tokens": est, "status": status(p, today),
            "save_to": str(p.resolve(p.output_dir or "results") / "linkedin" / f"{sid}-<n>.jsonl"),
            "not_run": len(all_s) - n}


def _no_room(st: dict) -> str:
    if st["today"] >= st["daily_tokens"] or st["daily_tokens"] - st["today"] <= st["weekly_tokens"] - st["week"]:
        return (f"Today's LinkedIn budget is used: about {st['today']:,} of {st['daily_tokens']:,} tokens. "
                f"It resets tomorrow.")
    return (f"This week's LinkedIn budget is used: about {st['week']:,} of {st['weekly_tokens']:,} tokens "
            f"over the last 7 days.")


def record_import(p, session: str, jobs: int, descriptions: int) -> None:
    led = load_ledger(p)
    for s in led["sessions"]:
        if s.get("id") == session:
            s["jobs"], s["descriptions_read"] = s.get("jobs", 0) + jobs, s.get("descriptions_read", 0) + descriptions
    save_ledger(p, led)


# ---------------------------------------------------------------- what it really used

def claude_dirs() -> list[Path]:
    home = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
    return [home / "projects"] if (home / "projects").is_dir() else []


def billed_tokens(usage: dict) -> int:
    return int((usage.get("input_tokens") or 0) + (usage.get("output_tokens") or 0)
               + (usage.get("cache_creation_input_tokens") or 0) + (usage.get("cache_read_input_tokens") or 0) / 10)


def transcript_tokens(path: Path) -> int:
    """Sum of a Claude Code transcript's usage, each API message counted once."""
    seen, total = set(), 0
    with path.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if '"usage"' not in line:
                continue
            try:
                msg = json.loads(line).get("message") or {}
            except ValueError:
                continue
            mid = msg.get("id")
            if not isinstance(msg.get("usage"), dict) or mid in seen:
                continue
            seen.add(mid)
            total += billed_tokens(msg["usage"])
    return total


def find_runs(roots=None, since_days: int = 14) -> dict[str, int]:
    """session id -> tokens, from Claude Code's records of helpers labelled 'job-hunter LinkedIn read <id>'."""
    cutoff = dt.datetime.now().timestamp() - since_days * 86400
    found: dict[str, int] = {}
    for root in roots if roots is not None else claude_dirs():
        for meta in Path(root).glob("*/*/subagents/*.meta.json"):
            try:
                if meta.stat().st_mtime < cutoff:
                    continue
                desc = str(json.loads(meta.read_text(encoding="utf-8")).get("description") or "")
            except (OSError, ValueError):
                continue
            m = re.search(re.escape(AGENT_LABEL) + r" ([0-9a-f]{8})", desc)
            log = meta.with_name(meta.name.replace(".meta.json", ".jsonl"))
            if m and log.exists():
                found[m.group(1)] = found.get(m.group(1), 0) + transcript_tokens(log)
    return found


def measure(p, roots=None, manual: dict | None = None) -> list[tuple[str, int, int]]:
    """Replace estimates with measured use. Returns (session, estimated, measured) for updated runs."""
    led = load_ledger(p)
    runs = dict(find_runs(roots))
    runs.update(manual or {})
    changed = []
    for s in led["sessions"]:
        got = runs.get(s.get("id"))
        if got and got != s.get("measured"):
            s["measured"] = got
            changed.append((s["id"], s.get("estimated", 0), got))
    if changed:
        save_ledger(p, led)
    return changed
