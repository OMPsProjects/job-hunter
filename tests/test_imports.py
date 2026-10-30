"""LinkedIn read in the person's browser comes in through `job-hunter import` and joins the search."""
import json
import os
import sys
import time
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from jobhunter import imports, setup, sources, store  # noqa: E402
from jobhunter.cli import main  # noqa: E402
from jobhunter.profile import Profile  # noqa: E402

ROWS = [
    {"title": "Senior Underwriter", "company": "Acme Capital", "location": "New York, NY",
     "url": "https://www.linkedin.com/jobs/view/111/", "date_posted": "2026-10-28",
     "description": "<p>Underwrite <b>multifamily</b> loans.</p>", "query": "Commercial Real Estate Underwriter"},
    {"title": "Underwriter", "company": "Remote Co", "location": "Remote", "url": "https://www.linkedin.com/jobs/view/222/",
     "date_posted": "3 days ago", "query": "Underwriter"},
    {"title": "=HYPERLINK(\"x\")", "company": "Evil", "url": "https://www.linkedin.com/jobs/view/333/"},
    {"title": "No link", "company": "X", "url": "javascript:alert(1)"},
    {"title": "No company", "url": "https://www.linkedin.com/jobs/view/444/"},
    "not an object",
]


def _write(path, rows, lines=True):
    path.write_text("\n".join(json.dumps(r) for r in rows) if lines else json.dumps(rows), encoding="utf-8")
    return path


def test_import_cleans_and_dedupes(tmp_path):
    src = _write(tmp_path / "in.jsonl", ROWS)
    kept, skipped = imports.import_file(src, tmp_path / "results", "linkedin")
    assert (kept, skipped) == (3, 3)
    rows = imports.load_rows(tmp_path / "results", hours=24)
    by_url = {r["job_url"]: r for r in rows}
    first = by_url["https://www.linkedin.com/jobs/view/111/"]
    assert first["description"] == "Underwrite multifamily loans." and first["site"] == "linkedin"
    assert first["date_posted"] == "2026-10-28" and not first["is_remote"]
    second = by_url["https://www.linkedin.com/jobs/view/222/"]
    assert second["is_remote"] and second["date_posted"] == ""  # "3 days ago" isn't a date
    assert not by_url["https://www.linkedin.com/jobs/view/333/"]["title"].startswith("=")  # spreadsheet formula defused
    # a second import of the same file adds nothing; a JSON array works too
    assert imports.import_file(_write(tmp_path / "again.json", ROWS[:2], lines=False), tmp_path / "results",
                               "linkedin") == (0, 2)


def test_bad_source_name(tmp_path):
    src = _write(tmp_path / "in.jsonl", ROWS[:1])
    for bad in ("../x", "LinkedIn", ""):
        try:
            imports.import_file(src, tmp_path, bad)
        except ValueError:
            continue
        raise AssertionError(bad)


def test_old_imports_drop_out(tmp_path):
    imports.import_file(_write(tmp_path / "in.jsonl", ROWS[:1]), tmp_path, "linkedin")
    f = next((tmp_path / "imported").glob("*.jsonl"))
    old = time.time() - 15 * 86400
    os.utime(f, (old, old))
    assert imports.load_rows(tmp_path, hours=336) == []


def test_imported_jobs_join_the_search(tmp_path):
    imports.import_file(_write(tmp_path / "in.jsonl", ROWS[:2]), tmp_path / "results", "linkedin")
    off = {k: False for k in sources.ALL_SOURCES if k != "imported"}
    p = Profile({"search": {"locations": ["New York, NY"], "include_remote": True},
                 "regions": [{"key": "nyc", "pattern": "new york"}],
                 "tracks": {"core": ["Commercial Real Estate Underwriter"], "adjacent": ["Underwriter"]},
                 "sources": off}, path=tmp_path / "profile.yaml")
    jobs, stats = sources.gather(p)
    assert stats["imported"]["rows"] == 2
    assert dict(zip(jobs["company"], jobs["track"], strict=True)) == {"Acme Capital": "core", "Remote Co": "adjacent"}
    assert set(jobs["site"]) == {"linkedin"}


def test_imported_never_flagged_broken(tmp_path):
    db = store.Store(tmp_path / "s.db")
    for rows in (5, 4, 6, 0, 0):
        rid = db.start_run()
        db.record_sources(rid, {"imported": {"rows": rows, "errors": 0, "seconds": 0}})
    assert db.health() == []


def test_setup_linkedin_means_browser(tmp_path):
    setup.run_setup(tmp_path, {"titles": ["Underwriter"], "linkedin": True}, ask=None, say=lambda *_: None)
    raw = yaml.safe_load((tmp_path / "profile.yaml").read_text().split("\n", 4)[-1])
    assert raw["search"]["sites"] == ["indeed"] and raw["search"]["linkedin_browser"] is True
    assert Profile(raw, path=tmp_path / "profile.yaml").linkedin_browser
    assert setup.current_answers(tmp_path)["linkedin"] is True


def test_cli_import(tmp_path, capsys, monkeypatch):
    setup.run_setup(tmp_path, {"titles": ["Underwriter"]}, ask=None, say=lambda *_: None)
    src = _write(tmp_path / "li.jsonl", ROWS[:2])
    monkeypatch.chdir(tmp_path)
    assert main(["--profile", str(tmp_path / "profile.yaml"), "import", str(src)]) == 0
    assert "Imported 2 linkedin posting" in capsys.readouterr().out
    assert len(imports.load_rows(tmp_path / "results", 24)) == 2


def test_setup_writes_budget_and_cli_plan(tmp_path, capsys):
    setup.run_setup(tmp_path, {"titles": ["Underwriter"], "locations": ["Chicago, IL"], "linkedin": True},
                    ask=None, say=lambda *_: None)
    raw = yaml.safe_load((tmp_path / "profile.yaml").read_text().split("\n", 4)[-1])
    assert raw["linkedin"]["daily_tokens"] == 150_000 and raw["linkedin"]["max_descriptions"] == 15
    prof = str(tmp_path / "profile.yaml")
    assert main(["--profile", prof, "linkedin", "plan"]) == 0
    out = capsys.readouterr().out
    assert "LinkedIn today:" in out and "job-hunter LinkedIn read" in out
    plan = json.loads((tmp_path / "results" / "linkedin-plan.json").read_text())
    assert plan["allowed"] and plan["searches"][0]["url"].startswith("https://www.linkedin.com/jobs/search/?")
    assert main(["--profile", prof, "linkedin", "usage", "--session", plan["session"], "--tokens", "42000"]) == 0
    assert main(["--profile", prof, "linkedin", "status"]) == 0
    assert "about 42k of 150k today" in capsys.readouterr().out
