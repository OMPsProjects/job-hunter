"""LinkedIn in the person's browser stays inside its token budget: the plan hands out only what
fits, records it as spent, and what Claude really used replaces the estimate."""
import datetime as dt
import json
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from jobhunter import imports, linkedin  # noqa: E402
from jobhunter.profile import Profile  # noqa: E402

DAY = dt.date(2026, 11, 2)


def prof(tmp_path, li=None, **search):
    s = {"locations": ["Washington, DC", "New York, NY"], "include_remote": True, "linkedin_browser": True,
         "hours_old": 336, **search}
    data = {"search": s, "tracks": {"core": ["Commercial Real Estate Underwriter", "Credit Analyst"],
                                    "adjacent": ["Asset Manager"]}}
    if li is not None:
        data["linkedin"] = li
    return Profile(data, path=tmp_path / "profile.yaml")


def test_combined_searches(tmp_path):
    p = prof(tmp_path)
    s = linkedin.searches(p, "r86400", ["senior", "director"])
    assert len(s) == 6  # 2 title groups x (2 cities + remote)
    q = parse_qs(urlparse(s[0]["url"]).query)
    assert q["keywords"] == ['"Commercial Real Estate Underwriter" OR "Credit Analyst"']
    assert q["location"] == ["Washington, DC"] and q["f_TPR"] == ["r86400"] and q["f_E"] == ["4,5"]
    remote = [x for x in s if x["place"] == "United States"]
    assert all(parse_qs(urlparse(x["url"]).query)["f_WT"] == ["2"] for x in remote)
    only = linkedin.searches(prof(tmp_path, remote_only=True), "r86400")
    assert [x["place"] for x in only] == ["United States", "United States"]


def test_plan_stays_inside_daily_and_weekly_limits(tmp_path):
    p = prof(tmp_path, {"daily_tokens": 100_000, "weekly_tokens": 180_000, "max_searches": 6, "max_descriptions": 10})
    first = linkedin.plan(p, today=DAY)
    assert first["allowed"] and first["estimated_tokens"] <= 100_000
    assert len(first["searches"]) == 5  # 25k + 5 x 15k = 100k: no room for descriptions
    assert first["descriptions_per_search"] == 0 and first["not_run"] == 1
    assert first["searches"][0]["url"] in json.dumps(first)
    again = linkedin.plan(p, today=DAY)  # asking twice doesn't get more
    assert not again["allowed"] and "Today's" in again["reason"]
    nxt = linkedin.plan(p, today=DAY + dt.timedelta(days=1))
    assert nxt["allowed"] and nxt["estimated_tokens"] <= 80_000  # the week has 80k left
    # the search that didn't fit yesterday goes first, and only new postings are asked for
    assert "New York" in nxt["searches"][0]["place"] or "United States" in nxt["searches"][0]["place"]
    assert "f_TPR=r86400" in nxt["searches"][0]["url"]
    third = linkedin.plan(p, today=DAY + dt.timedelta(days=2))
    assert not third["allowed"] and "week" in third["reason"]
    later = linkedin.plan(p, today=DAY + dt.timedelta(days=7))
    assert later["allowed"]


def test_zero_turns_it_off(tmp_path):
    assert not linkedin.plan(prof(tmp_path, {"daily_tokens": 0}), today=DAY)["allowed"]


def test_descriptions_spread_and_script(tmp_path):
    p = prof(tmp_path, {"daily_tokens": 200_000, "max_searches": 2, "max_descriptions": 9})
    out = linkedin.plan(p, today=DAY)
    assert len(out["searches"]) == 2 and out["descriptions_per_search"] == 5
    script = out["script"]
    assert '"per":5' in script and "underwriter" in script and "__PARAMS__" not in script
    assert "\n//" not in script and len(script) < 6000  # small: it's sent once per search
    assert out["agent_description"] == f"job-hunter LinkedIn read {out['session']}"


def _transcript(folder, agent, desc, usages):
    sub = folder / "projects" / "-home-me" / "sess1" / "subagents"
    sub.mkdir(parents=True, exist_ok=True)
    (sub / f"agent-{agent}.meta.json").write_text(json.dumps({"agentType": "job-hunter-linkedin", "description": desc}))
    lines = []
    for mid, u in usages:
        for _ in range(2):  # one API message is logged once per content block
            lines.append(json.dumps({"type": "assistant", "message": {"id": mid, "usage": u}}))
    lines.append(json.dumps({"type": "user", "message": {"content": "x"}}))
    (sub / f"agent-{agent}.jsonl").write_text("\n".join(lines))


def test_measured_use_replaces_the_estimate(tmp_path):
    p = prof(tmp_path, {"daily_tokens": 400_000, "weekly_tokens": 900_000})
    out = linkedin.plan(p)
    u = {"input_tokens": 10, "output_tokens": 2_000, "cache_creation_input_tokens": 20_000,
         "cache_read_input_tokens": 300_000}
    _transcript(tmp_path / "claude", "a1", out["agent_description"], [("m1", u), ("m2", u)])
    _transcript(tmp_path / "claude", "a2", "Find CRE employers", [("m3", u)])  # not ours
    assert linkedin.transcript_tokens(next((tmp_path / "claude").rglob("agent-a1.jsonl"))) == 2 * (10 + 2_000 + 20_000 + 30_000)
    changed = linkedin.measure(p, roots=[tmp_path / "claude" / "projects"])
    assert changed == [(out["session"], out["estimated_tokens"], 104_020)]
    st = linkedin.status(p)
    assert st["today"] == 104_020 and st["measured_runs"] == 1
    assert st["scale"] == round(104_020 / out["estimated_tokens"], 2)
    # a figure typed in by hand works too
    linkedin.measure(p, roots=[], manual={out["session"]: 50_000})
    assert linkedin.status(p)["today"] == 50_000


def test_descriptions_fill_in_later(tmp_path):
    rows = [{"url": "https://www.linkedin.com/jobs/view/1/", "title": "Underwriter", "company": "A",
             "query": "Commercial Real Estate Underwriter / Credit Analyst"},
            {"_meta": {"q": "x", "n": 1}}]
    src = tmp_path / "a.jsonl"
    src.write_text("\n".join(json.dumps(r) for r in rows))
    assert imports.import_file(src, tmp_path, "linkedin") == (1, 0)
    rows[0]["description"] = "Underwrite loans. " * 30
    src.write_text(json.dumps(rows[0]))
    assert imports.import_file(src, tmp_path, "linkedin") == (1, 0)
    assert imports.import_file(src, tmp_path, "linkedin") == (0, 1)
    got = imports.load_rows(tmp_path, 24)
    assert len(got) == 1 and got[0]["description"].startswith("Underwrite")
    p = prof(tmp_path)
    p.output_dir = str(tmp_path)
    assert imports.as_frame_rows(p, tmp_path)[0]["track"] == "core"


FIXTURE = """<!doctype html><html><body><div id="list" style="height:300px;overflow-y:auto">%s</div>
<div id="pane"></div><script>
const DESC = {%s};
document.querySelectorAll('a[href*="/jobs/view/"]').forEach((a) => a.addEventListener('click', (e) => {
  e.preventDefault(); const id = a.href.match(/view\\/(\\d+)/)[1];
  history.replaceState(null, '', location.pathname + location.search.replace(/&currentJobId=\\d+/, '') + '&currentJobId=' + id);
  document.getElementById('pane').innerHTML = '<div id="job-details">About the job ' + DESC[id] + '</div>';
}));
</script></body></html>"""


@pytest.mark.skipif(not shutil.which("node"), reason="needs node")
def test_page_script_reads_cards_and_descriptions(tmp_path):
    pytest.importorskip("playwright")
    cards, descs = [], []
    jobs = [("101", "Commercial Real Estate Underwriter", "Acme Capital", "Washington, DC"),
            ("102", "Software Engineer", "Other Co", "Remote"),
            ("103", "Credit Analyst II", "Bank of Somewhere", "New York, NY")]
    for jid, title, co, loc in jobs:
        cards.append(f'<li data-occludable-job-id="{jid}" style="height:120px"><a href="/jobs/view/{jid}/" '
                     f'aria-label="{title} with verification">{title}</a><div>{title}</div><div>{co}</div>'
                     f'<div>{loc}</div><div>Promoted</div><time datetime="2026-10-29">3 days ago</time></li>')
        descs.append(f'"{jid}": "{title} duties. ' + "Underwrite multifamily loans. " * 12 + '"')
    page = tmp_path / "jobs" / "search" / "index.html"
    page.parent.mkdir(parents=True)
    page.write_text(FIXTURE % ("".join(cards), ",".join(descs)))
    script = linkedin.page_script(5, ["underwriter", "credit"])
    runner = tmp_path / "run.py"
    runner.write_text(
        "import sys, json\nfrom playwright.sync_api import sync_playwright\n"
        "with sync_playwright() as p:\n"
        "    b = p.chromium.launch()\n    pg = b.new_page()\n"
        "    pg.route('https://www.linkedin.com/**', lambda r: r.fulfill(path=sys.argv[1], content_type='text/html'))\n"
        "    pg.goto('https://www.linkedin.com/jobs/search/?keywords=%22A%22+OR+%22B%22&location=DC')\n"
        "    out = pg.evaluate(open(sys.argv[2]).read())\n"
        "    print(out)\n    b.close()\n")
    (tmp_path / "s.js").write_text(script)
    try:
        res = subprocess.run([sys.executable, str(runner), str(page), str(tmp_path / "s.js")], capture_output=True,
                             text=True, timeout=120)
    except subprocess.TimeoutExpired:
        pytest.skip("browser too slow here")
    if res.returncode and "Executable doesn't exist" in res.stderr:
        pytest.skip("no browser installed")
    assert res.returncode == 0, res.stderr[-2000:]
    lines = [json.loads(x) for x in res.stdout.strip().splitlines()]
    meta, rows = lines[0]["_meta"], lines[1:]
    assert meta["q"] == "A / B" and meta["n"] == 3 and meta["read"] == 2
    by = {r["url"]: r for r in rows}
    a = by["https://www.linkedin.com/jobs/view/101/"]
    assert (a["title"], a["company"], a["location"], a["date_posted"]) == \
        ("Commercial Real Estate Underwriter", "Acme Capital", "Washington, DC", "2026-10-29")
    assert a["description"].startswith("Commercial Real Estate Underwriter duties")
    assert "description" not in by["https://www.linkedin.com/jobs/view/102/"]  # title doesn't fit: not opened
    assert by["https://www.linkedin.com/jobs/view/103/"]["description"]
    # what it returns imports as-is
    f = tmp_path / "out.jsonl"
    f.write_text(res.stdout)
    assert imports.import_file(f, tmp_path / "res", "linkedin") == (3, 0)
