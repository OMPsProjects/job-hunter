"""Setup, company/board lists, run store and health, file safety, validation, ranking eval,
log redaction, and a CLI walk-through. All offline."""
import json
import os
import sys
from pathlib import Path

import pandas as pd
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from jobhunter import cli, evalrank, fileio, logs, setup, store, targets, validate  # noqa: E402
from jobhunter.profile import load_profile  # noqa: E402

ANSWERS = {
    "field": "hospital nursing", "titles": "Registered Nurse, ICU Nurse", "adjacent_titles": "Charge Nurse",
    "levels": "mid, senior", "years_experience": "6", "skills": "critical care, patient assessment, epic",
    "locations": "Denver, CO; Boise, ID", "remote": "n", "remote_like_top_city": "n",
    "pay_floor": "85k", "pay_target": "110000", "avoid_companies": "Acme Health", "avoid_keywords": "travel nurse",
    "target_companies": "", "discover_companies": "y",
}


# ----------------------------- setup ----------------------------------------

def test_setup_builds_valid_profile(tmp_path):
    res = setup.run_setup(tmp_path, ANSWERS, ask=None)
    p = load_profile(res["profile"])
    assert p.tracks == {"core": ["Registered Nurse", "ICU Nurse"], "adjacent": ["Charge Nurse"]}
    assert [k for k, _ in p.regions] == ["den", "boise"]
    assert p.pay_floor == 85000 and p.pay_target == 110000
    assert p.exclude_companies == ["Acme Health"] and p.exclude_keywords == ["travel nurse"]
    assert p.sites == ["indeed"]  # LinkedIn is opt-in
    assert not p.include_remote
    cand = yaml.safe_load(res["candidate"].read_text())
    assert cand["target_levels"] == ["mid", "senior"] and "critical care" in cand["skills"]["core"]
    errs, _ = validate.validate_profile(yaml.safe_load(res["profile"].read_text()))
    assert errs == []


def test_setup_refuses_to_overwrite(tmp_path):
    setup.run_setup(tmp_path, ANSWERS, ask=None)
    with pytest.raises(SystemExit):
        setup.run_setup(tmp_path, ANSWERS, ask=None)
    setup.run_setup(tmp_path, {**ANSWERS, "titles": "Nurse Manager"}, ask=None, force=True)
    assert (tmp_path / "profile.yaml.bak").exists()


def test_setup_interactive_reprompts(tmp_path):
    replies = iter(["", "", "", "Staff Accountant", "", "", "nonsense", "senior", "", "", "", "", "", "", "", "", "", "", "", "", ""])
    said = []
    setup.ask_all({}, ask=lambda prompt: next(replies), say=said.append)
    assert any("At least one title" in s for s in said)
    assert any("Use words from" in s for s in said)


def test_city_parsing():
    assert setup._parse("cities", "Chicago, IL; New York, NY", "") == ["Chicago, IL", "New York, NY"]
    assert setup._parse("cities", "Chicago, IL, New York, NY", "") == ["Chicago, IL", "New York, NY"]
    assert setup.region_for("Washington, DC")[0] == "dc"
    assert setup.region_for("Smallville, KS") == ("smallv", "smallville")
    assert setup._parse("money", "120k", "") == 120000
    assert setup._parse("money", "55-65k", "") == 55000
    assert setup._parse("money", "$45/hr", "") == 45 * 2080
    assert setup._parse("money", "1,200", "") == 1200 and setup._parse("money", "5", "") is None
    assert setup.region_for("Chicago IL")[0] == "chi" and setup.region_for("New York City")[0] == "nyc"


# ----------------------------- companies / boards ---------------------------

def test_targets_add_and_dedupe(tmp_path):
    t = targets.Targets(tmp_path / "companies.yaml")
    assert t.add_company("Acme", "greenhouse", "acme")[0]
    assert not t.add_company("Acme Inc.", "greenhouse", "acme")[0]  # same company
    assert t.add_board("https://www.selectleaders.com", "SelectLeaders")[0]
    assert not t.add_board("https://selectleaders.com/", None)[0]
    again = targets.Targets(tmp_path / "companies.yaml")
    assert len(again.companies) == 1 and len(again.browse_boards) == 1
    assert again.remove("Acme") and not again.companies


def test_add_from_url_routes(tmp_path, monkeypatch):
    t = targets.Targets(tmp_path / "companies.yaml")
    monkeypatch.setattr(targets.ats, "list_postings", lambda *a, **k: [{"title": "x", "job_url": "https://x"}])
    ok, msg = targets.add_from_url(t, "https://jobs.lever.co/acme/123", name="Acme")
    assert ok and t.companies[0]["ats"] == "lever" and "1 open roles" in msg
    ok, _ = targets.add_from_url(t, "builtin.com/jobs", name="Built In")
    assert ok and t.browse_boards[0]["url"] == "https://builtin.com/jobs"


def test_profile_merges_companies_file(tmp_path):
    setup.run_setup(tmp_path, ANSWERS, ask=None)
    t = targets.Targets(tmp_path / "companies.yaml")
    t.add_company("Acme", "greenhouse", "acme")
    t.add_board("https://example.org/careers", "Example")
    p = load_profile(tmp_path / "profile.yaml")
    assert p.target_companies[0]["slug"] == "acme"
    assert any(b["url"] == "https://example.org/careers" for b in p.browse_boards)


def test_discovery_uses_apply_links_and_skips_empty_boards(tmp_path, monkeypatch):
    t = targets.Targets(tmp_path / "companies.yaml")
    monkeypatch.setattr(targets.ats, "list_postings",
                        lambda kind, name, slug, **k: [] if slug == "empty" else [{"title": "ICU Nurse", "job_url": "u"}])
    import jobhunter.verify as verify
    monkeypatch.setattr(verify, "discover", lambda name: {"ats": "greenhouse", "slug": "empty", "confirmed": False})
    jobs = pd.DataFrame([
        {"company": "Big Hospital", "job_url": "https://indeed.com/1", "job_url_direct": "https://jobs.lever.co/bighosp/1"},
        {"company": "Big Hospital", "job_url": "https://indeed.com/2"},
        {"company": "Tiny Clinic", "job_url": "https://indeed.com/3"},
        {"company": "Nurse Staffing Solutions", "job_url": "https://indeed.com/4"},
    ])
    emp = targets.employers_from_results(jobs)
    assert emp[0][0] == "Big Hospital" and emp[0][1] == 2
    prof = setup.build_profile(setup.ask_all(ANSWERS, ask=None))
    from jobhunter.profile import Profile
    rows = targets.discover_companies(t, emp, profile=Profile(prof), add=True)
    by = {r["name"]: r for r in rows}
    assert by["Big Hospital"]["status"] == "added" and by["Big Hospital"]["ats"] == "lever"
    assert "no open roles" in by["Tiny Clinic"]["status"]
    assert "staffing" in by["Nurse Staffing Solutions"]["status"]


# ----------------------------- store / health -------------------------------

def test_store_seen_and_health(tmp_path):
    s = store.Store(tmp_path / "jh.db")
    for rows in ([30, 12], [28, 10], [31, 0], [0, 0], [0, 0]):
        rid = s.start_run()
        s.record_sources(rid, {"indeed": {"rows": rows[0], "errors": 0, "seconds": 1},
                               "remotive": {"rows": rows[1], "errors": 0, "seconds": 1}})
        s.finish_run(rid, "ok", {})
    warnings = s.health()
    assert any(w.startswith("indeed: 0 jobs for 2 runs") for w in warnings)
    assert any(w.startswith("remotive") for w in warnings)
    s.mark_seen([("u1", "A", "T"), ("u2", "B", "T")])
    s.mark_seen([("u1", "A", "T")])
    assert s.seen_urls() == {"u1", "u2"}
    rid = s.start_run()
    s.record_sources(rid, {"jooble": {"rows": 0, "errors": 5, "seconds": 1}})
    s.finish_run(rid, "ok", {})
    assert any("every request failed" in w for w in s.health(["jooble"]))
    s.close()


def test_store_imports_legacy_seen_csv(tmp_path):
    pd.DataFrame({"job_url": ["a", "b"]}).to_csv(tmp_path / "seen_jobs.csv", index=False)
    s = store.Store(tmp_path / "jh.db")
    assert s.import_seen_csv(tmp_path / "seen_jobs.csv") == 2
    assert s.import_seen_csv(tmp_path / "seen_jobs.csv") == 0  # only once
    s.close()


# ----------------------------- file safety ----------------------------------

def test_atomic_write_and_private(tmp_path):
    p = tmp_path / "answers.yaml"
    fileio.write_text_atomic(p, "a: 1\n")
    assert p.read_text() == "a: 1\n"
    if os.name == "posix":
        assert oct(p.stat().st_mode)[-3:] == "600"
    assert not [x for x in tmp_path.iterdir() if x.name.endswith(".tmp")]


def test_run_lock(tmp_path):
    with fileio.RunLock(tmp_path), pytest.raises(RuntimeError), fileio.RunLock(tmp_path):
        pass
    with fileio.RunLock(tmp_path):  # released after the first
        pass


def test_dotenv(tmp_path, monkeypatch):
    monkeypatch.delenv("JH_TEST_KEY", raising=False)
    monkeypatch.setenv("JH_EXISTING", "keep")
    (tmp_path / ".env").write_text('# keys\nJH_TEST_KEY="abc"\nexport JH_EXISTING=override\n')
    fileio.load_dotenv(tmp_path / ".env")
    assert os.environ["JH_TEST_KEY"] == "abc" and os.environ["JH_EXISTING"] == "keep"


def test_log_redaction():
    out = logs.redact("mail jo@example.com phone (312) 555-0199 ssn 123-45-6789 url ?app_key=SECRET&x=1")
    assert "jo@example.com" not in out and "010-0199" not in out and "123-45-6789" not in out and "SECRET" not in out


# ----------------------------- validation -----------------------------------

def test_validation_messages():
    errs, warns = validate.validate_profile({"serch": {}, "search": {"locations": "DC"},
                                             "ranking": {"pay_floor": 200, "pay_target": 100}})
    assert any("search.locations" in e for e in errs) and any("pay_floor" in e for e in errs)
    assert any("did you mean 'search'" in w for w in warns)
    errs, _ = validate.validate_candidate({"target_levels": ["guru"]})
    assert errs


def test_bad_profile_exits_cleanly(tmp_path):
    (tmp_path / "profile.yaml").write_text("tracks: [oops\n")
    with pytest.raises(SystemExit) as e:
        load_profile(tmp_path / "profile.yaml")
    assert "isn't valid YAML" in str(e.value)


# ----------------------------- ranking eval ---------------------------------

def test_eval_rank_and_tune():
    ranked = pd.DataFrame({
        "job_url": [f"u{i}" for i in range(12)],
        "fit": [90, 80, 30, 85, 20, 70, 60, 50, 95, 40, 10, 75],
        "seniority": [50] * 12, "location_score": [100, 50] * 6, "pay_score": [50] * 12,
        "freshness": [100 - i for i in range(12)],
    })
    labels = pd.DataFrame({"job_url": ranked["job_url"],
                           "label": ["2", "2", "0", "2", "0", "1", "1", "0", "2", "0", "0", "1"]})
    w = {"fit": 100, "seniority": 0, "location": 0, "pay": 0, "freshness": 0}
    r = evalrank.evaluate(ranked, labels, w)
    assert r["labeled"] == 12 and r["ndcg@10"] > 0.95
    worse = evalrank.evaluate(ranked, labels, {"fit": 0, "seniority": 0, "location": 0, "pay": 0, "freshness": 100})
    assert worse["ndcg@10"] < r["ndcg@10"]
    best = evalrank.tune(ranked, labels, step=25)
    assert best[0][0] >= r["ndcg@10"] - 1e-9  # the search includes fit-only, so it can't do worse


# ----------------------------- CLI walk-through -----------------------------

def run(tmp_path, *argv):
    return cli.main(["--profile", str(tmp_path / "profile.yaml"), *argv])


def test_cli_walkthrough(tmp_path, capsys):
    (tmp_path / "ans.yaml").write_text(yaml.safe_dump(ANSWERS))
    assert run(tmp_path, "setup", "--from", str(tmp_path / "ans.yaml")) == 0
    assert run(tmp_path, "check") == 0
    assert run(tmp_path, "boards", "add", "https://example.org/careers", "--name", "Example") == 0
    assert run(tmp_path, "boards", "list") == 0
    assert "Example" in capsys.readouterr().out
    assert run(tmp_path, "answers", "add", "Are you willing to relocate?", "No") == 0
    assert run(tmp_path, "answers", "add", "Gender", "x") == 2
    assert run(tmp_path, "track", "set", "--status", "shortlisted", "--company", "A", "--title", "B") == 0
    assert run(tmp_path, "health") == 0
    out = tmp_path / "results"
    out.mkdir(exist_ok=True)
    pd.DataFrame({"job_url": ["u1", "u2"], "title": ["t", "t"], "company": ["c", "d"], "location": ["", ""],
                  "rank": [1, 2], "rank_score": [80, 70], "fit": [80, 40], "seniority": [50, 50],
                  "location_score": [100, 100], "pay_score": [50, 50], "freshness": [90, 90]}).to_csv(out / "ranked.csv", index=False)
    assert run(tmp_path, "labels") == 0
    lab = pd.read_csv(out / "labels.csv", dtype=str)
    lab["label"] = lab["job_url"].map({"u1": "2", "u2": "0"})
    lab.to_csv(out / "labels.csv", index=False)
    assert run(tmp_path, "eval-rank", "--tune", "--step", "50") == 0
    assert "precision@10" in capsys.readouterr().out


def test_cli_search_with_fake_sources(tmp_path, monkeypatch):
    """search end to end with sources stubbed: writes outputs, records the run, marks seen."""
    (tmp_path / "ans.yaml").write_text(yaml.safe_dump({**ANSWERS, "remote": "y"}))
    run(tmp_path, "setup", "--from", str(tmp_path / "ans.yaml"))
    import jobhunter.sources as sources
    jobs = pd.DataFrame([{"title": "ICU Nurse", "company": "Denver Health", "location": "Denver, CO", "is_remote": False,
                          "job_url": "https://x/1", "description": "critical care, patient assessment, epic. 3+ years experience",
                          "site": "indeed", "track": "core", "date_posted": "2026-10-27", "max_amount": 100000,
                          "min_amount": 90000, "interval": "yearly", "region": "den"}])
    monkeypatch.setattr(sources, "gather", lambda p, only=None: (jobs.copy(), {"indeed": {"rows": 1, "errors": 0, "seconds": 0.1}}))
    assert run(tmp_path, "search", "--no-verify") == 0
    out = tmp_path / "results"
    ranked = pd.read_csv(out / "ranked.csv")
    assert ranked.iloc[0]["company"] == "Denver Health"
    summary = json.loads((out / "run_summary.json").read_text())
    assert summary["new"] == 1 and summary["sources"]["indeed"]["rows"] == 1
    assert run(tmp_path, "search", "--no-verify") == 0  # second run: nothing new
    assert json.loads((out / "run_summary.json").read_text())["new"] == 0
    assert (out / "logs").exists()


def test_setup_without_titles_writes_nothing(tmp_path):
    with pytest.raises(SystemExit):
        setup.run_setup(tmp_path, {**ANSWERS, "titles": ""}, ask=None)
    assert not (tmp_path / "profile.yaml").exists()


def test_setup_reads_messy_answers(tmp_path):
    a = setup.ask_all({**ANSWERS, "levels": "Mid-level, Senior", "remote": "Yes please", "pay_floor": "55-65k",
                       "locations": "Chicago IL; Remote"}, ask=None, say=lambda m: None)
    prof = setup.build_profile(a)
    assert a["levels"] == ["mid", "senior"] and a["remote"] is True and a["pay_floor"] == 55000
    assert [r["key"] for r in prof["regions"]] == ["chi"] and prof["search"]["include_remote"] is True


def test_companies_add_rejects_empty_boards(tmp_path, monkeypatch):
    import jobhunter.verify as verify
    t = targets.Targets(tmp_path / "companies.yaml")
    monkeypatch.setattr(verify, "discover", lambda name: {"ats": "workable", "slug": "apple", "confirmed": True})
    monkeypatch.setattr(targets.ats, "list_postings", lambda *a, **k: [])
    ok, msg = targets.add_by_name(t, "Apple")
    assert not ok and "no open roles" in msg and not t.companies


def test_label_sheet_survives_new_runs(tmp_path):
    ranked1 = pd.DataFrame({"job_url": ["u1", "u2"], "title": ["a", "b"], "company": ["c", "d"], "location": ["", ""],
                            "fit": [80, 30], "seniority": [50, 50], "location_score": [100, 100], "pay_score": [50, 50],
                            "freshness": [90, 90]})
    sheet = evalrank.make_label_sheet(ranked1)
    sheet["label"] = sheet["job_url"].map({"u1": "2.0", "u2": "0"})
    ranked2 = ranked1.assign(job_url=["u3", "u4"])
    merged = evalrank.make_label_sheet(ranked2, existing=sheet)
    assert len(merged) == 4 and set(merged.loc[merged["label"] != "", "job_url"]) == {"u1", "u2"}
    res = evalrank.evaluate(None, merged, {"fit": 100, "seniority": 0, "location": 0, "pay": 0, "freshness": 0})
    assert res and res["labeled"] == 2 and res["precision@10"] == 0.5


def test_runlock_takes_over_from_a_killed_run(tmp_path):
    import os
    import subprocess

    from jobhunter.fileio import RunLock
    if os.name != "posix":
        return
    dead = subprocess.Popen(["true"])
    dead.wait()
    (tmp_path / ".run.lock").write_text(str(dead.pid))
    with RunLock(tmp_path):
        assert (tmp_path / ".run.lock").read_text() == str(os.getpid())
    (tmp_path / ".run.lock").write_text(str(os.getppid()))  # a live process: still respected
    import pytest
    with pytest.raises(RuntimeError), RunLock(tmp_path):
        pass
