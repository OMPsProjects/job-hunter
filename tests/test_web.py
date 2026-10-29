"""The local web page's server: security checks, every endpoint, and the background task runner."""
import json
import os
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from jobhunter.web import server as web  # noqa: E402


@pytest.fixture
def demo(tmp_path):
    import make_demo
    folder = tmp_path / "demo"
    make_demo.build(folder)
    return folder


@pytest.fixture
def ui(demo):
    holder = {}
    ready = threading.Event()

    def on_ready(srv, app):
        holder.update(server=srv, app=app)
        ready.set()
    t = threading.Thread(target=web.serve, args=(demo / "profile.yaml",), kwargs={"port": 0, "open_browser": False, "ready": on_ready},
                         daemon=True)
    t.start()
    assert ready.wait(10)
    app = holder["app"]
    base = f"http://127.0.0.1:{app.port}"

    def call(path, body=None, token=True, headers=None, raw=None):
        h = {"X-JH-Token": app.token} if token else {}
        h.update(headers or {})
        data = None
        if raw is not None:
            data = raw
        elif body is not None:
            data = json.dumps(body).encode()
            h["Content-Type"] = "application/json"
        req = urllib.request.Request(base + path, data=data, headers=h, method="POST" if data is not None else "GET")
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return r.status, json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")
    yield types_ns(call=call, app=app, base=base, folder=demo)
    holder["server"].shutdown()


def types_ns(**kw):
    import types
    return types.SimpleNamespace(**kw)


def test_page_never_carries_the_key_and_has_strict_headers(ui):
    with urllib.request.urlopen(ui.base + "/") as r:
        html = r.read().decode()
        assert ui.app.token not in html and "jh-token" not in html
        assert "default-src 'self'" in r.headers["Content-Security-Policy"]
        assert "object-src 'none'" in r.headers["Content-Security-Policy"]
        assert r.headers["X-Frame-Options"] == "DENY"
        assert r.headers["Cross-Origin-Resource-Policy"] == "same-origin"
    for name in ("app.js", "app.css", "favicon.svg"):
        with urllib.request.urlopen(f"{ui.base}/{name}") as r:
            assert ui.app.token.encode() not in r.read()


def test_key_only_in_a_private_launcher(ui):
    from jobhunter.web.server import LAUNCHER
    f = ui.folder / LAUNCHER
    text = f.read_text()
    assert f"127.0.0.1:{ui.app.port}/#k={ui.app.token}" in text
    if os.name == "posix":
        assert (f.stat().st_mode & 0o077) == 0
    for name in ("app.js", "app.css", "fonts/atkinson-Regular.woff2", "favicon.svg"):
        with urllib.request.urlopen(f"{ui.base}/{name}") as r:
            assert r.status == 200


def test_api_needs_the_token_and_a_local_host(ui):
    assert ui.call("/api/status", token=False)[0] == 403
    assert ui.call("/api/status", headers={"X-JH-Token": "wrong"})[0] == 403
    status, body = ui.call("/api/status", headers={"Host": "evil.example.com"})
    assert status == 403 and "localhost" in body["error"]
    assert ui.call("/../../etc/passwd")[0] == 404


def test_status_and_jobs(ui):
    status, s = ui.call("/api/status")
    assert status == 200 and s["has_profile"] and s["last_run"]["new"] >= 5
    status, j = ui.call("/api/jobs?set=ranked")
    assert status == 200 and len(j["jobs"]) >= 5 and set(j["weights"]) >= {"fit", "pay"}
    first = j["jobs"][0]
    assert "description" not in first  # the list stays light; details come from /api/job
    assert next(x for x in j["jobs"] if x["company"] == "Lakeshore Community Bank")["status"] == "shortlisted"
    status, one = ui.call("/api/job?url=" + urllib.request.quote(first["job_url"], safe=""))
    assert status == 200 and one["description"]
    assert ui.call("/api/job?url=https%3A%2F%2Fnope")[0] == 404
    assert ui.call("/api/jobs?set=bogus")[0] == 400
    status, ex = ui.call("/api/jobs?set=excluded")
    assert status == 200 and any("sponsor" in (x.get("excluded_reason") or "") or x.get("excluded_reason") for x in ex["jobs"])


def test_track_label_stats(ui):
    status, j = ui.call("/api/jobs")
    job = j["jobs"][1]
    status, row = ui.call("/api/track", {"status": "submitted", "company": job["company"], "title": job["title"],
                                         "job_url": job["job_url"], "employer_url": job.get("employer_url")})
    assert status == 200 and row["status"] == "submitted" and row["source"] == "indeed"
    assert ui.call("/api/track", {"status": "teleported", "company": "A", "title": "B"})[0] == 400
    assert ui.call("/api/label", {"job_url": job["job_url"], "label": "2"})[0] == 200
    assert ui.call("/api/label", {"job_url": job["job_url"], "label": "7"})[0] == 400
    _, j2 = ui.call("/api/jobs")
    again = next(x for x in j2["jobs"] if x["job_url"] == job["job_url"])
    assert again["status"] == "submitted" and again["label"] == "2"
    status, st = ui.call("/api/stats")
    assert status == 200 and st["overall"]["sent"] >= 3 and st["ranking_check"]["labeled"] == 1
    status, apps = ui.call("/api/applications")
    assert status == 200 and len(apps["applications"]) >= 4 and "submitted" in apps["statuses"]


def test_companies(ui, monkeypatch):
    from jobhunter import targets
    monkeypatch.setattr(targets, "add_by_name", lambda t, name, track=None: (True, f"added {name}"))
    status, c = ui.call("/api/companies")
    assert status == 200 and len(c["companies"]) == 2 and c["boards"][0]["url"].startswith("https://cre-jobs")
    assert ui.call("/api/companies", {"action": "add-company", "name": "Acme"})[1]["message"] == "added Acme"
    assert ui.call("/api/companies", {"action": "add-company"})[0] == 400
    status, r = ui.call("/api/companies", {"action": "remove", "name": "Meridian Trust"})
    assert r["ok"] is True
    assert len(ui.call("/api/companies")[1]["companies"]) == 1


def test_settings_round_trip(ui):
    status, s = ui.call("/api/settings")
    assert status == 200 and s["ranking.weights"]["fit"] == 40
    body = {"ranking.pay_floor": "100000", "filters.needs_sponsorship": True, "ranking.weights": {"fit": 50, "seniority": 20,
            "location": 10, "pay": 10, "freshness": 10}, "filters.exclude_keywords": ["sales", "", " origination "],
            "sources": {"remoteok": False}}
    status, r = ui.call("/api/settings", body)
    assert status == 200 and r["backup"] == "profile.yaml.bak"
    import yaml
    data = yaml.safe_load((ui.folder / "profile.yaml").read_text())
    assert data["ranking"]["pay_floor"] == 100000 and data["filters"]["needs_sponsorship"] is True
    assert data["filters"]["exclude_keywords"] == ["sales", "origination"]
    assert data["sources"]["remoteok"] is False
    text = (ui.folder / "profile.yaml").read_text()
    assert "# Confirm each posting on the employer's own careers site." in text  # comments survive
    bak = ui.folder / "profile.yaml.bak"
    assert bak.exists() and (bak.stat().st_mode & 0o077) == 0 or __import__("os").name != "posix"
    for bad in ({"ranking.weights": {"fit": -5}}, {"ranking.weights": {"__evil__": 1}}, {"ranking.weights": {"fit": 0, "pay": 0}},
                {"ranking.weights": [1, 2]}, {"ranking.pay_floor": float("inf")}, {"verify.top_n": -5},
                {"filters.needs_sponsorship": "false"}, {"filters.exclude_companies": "Acme"},
                {"sources": {"made_up_source": True}}, {"sources": {"remoteok": "maybe"}}, {"output_dir": "/etc"}):
        status, _ = ui.call("/api/settings", json.loads(json.dumps(bad).replace("Infinity", "1e999")))
        assert status == 400, bad


def test_unshortlist_and_damaged_files(ui):
    _, j = ui.call("/api/jobs")
    job = next(x for x in j["jobs"] if x["status"] == "shortlisted")
    assert ui.call("/api/untrack", {"job_url": job["job_url"], "company": job["company"], "title": job["title"]})[1]["removed"] is True
    _, j = ui.call("/api/jobs")
    assert next(x for x in j["jobs"] if x["job_url"] == job["job_url"])["status"] is None
    (ui.folder / "applications.csv").write_text("")
    assert ui.call("/api/applications")[0] == 200 and ui.call("/api/jobs")[0] == 200
    (ui.folder / "results" / "labels.csv").write_text("label\n2\n")
    assert ui.call("/api/jobs")[0] == 200
    (ui.folder / "results" / "jobs_new_details.jsonl").write_text('{"title": "half')
    status, body = ui.call("/api/jobs")
    assert status == 500 and "damaged" in body["error"]


def test_bad_content_length(ui):
    import http.client
    c = http.client.HTTPConnection("127.0.0.1", ui.app.port)
    c.putrequest("POST", "/api/track")
    c.putheader("X-JH-Token", ui.app.token)
    c.putheader("Content-Length", "-5")
    c.endheaders()
    assert c.getresponse().status == 400


def test_setup_rerun_keeps_details(ui):
    import yaml
    before = yaml.safe_load((ui.folder / "candidate.yaml").read_text())
    _, info = ui.call("/api/setup")
    assert info["current"]["titles"] and info["current"]["locations"]
    status, _ = ui.call("/api/setup", {"answers": {"titles": ["Credit Officer"]}, "force": True})
    assert status == 200
    after = yaml.safe_load((ui.folder / "candidate.yaml").read_text())
    assert after["name"] == before["name"] and after.get("past_titles") == before.get("past_titles")
    assert (ui.folder / "candidate.yaml.bak").exists()


def test_setup_flow(ui, tmp_path):
    status, info = ui.call("/api/setup")
    assert status == 200 and info["has_profile"] and any(q["key"] == "titles" for q in info["questions"])
    status, sug = ui.call("/api/setup/suggest", {"titles": ["Credit Analyst"]})
    assert status == 200 and sug["related_titles"]
    status, up = ui.call("/api/setup/resume", raw=b"Jordan Rivera\nUnderwriter", headers={"X-Filename": "my%20resume.txt"})
    assert status == 200 and up["path"] == "candidate/base_resume.txt"
    assert ui.call("/api/setup/resume", raw=b"MZ...", headers={"X-Filename": "evil.exe"})[0] == 400
    assert ui.call("/api/setup", {"answers": {"titles": []}})[0] == 400
    answers = {"resume": up["path"], "titles": ["Credit Analyst"], "locations": ["Chicago, IL"], "remote": False}
    status, r = ui.call("/api/setup", {"answers": answers})
    assert status == 409  # a profile exists: needs force
    status, r = ui.call("/api/setup", {"answers": answers, "force": True})
    assert status == 200 and isinstance(r["problems"], list)
    assert (ui.folder / "profile.yaml.bak").exists()


def test_background_task(ui, monkeypatch):
    monkeypatch.setattr(ui.app, "cli", lambda *a: [sys.executable, "-c", "import time\nfor i in range(3): print('line', i)\n"])
    status, st = ui.call("/api/task", {"name": "search"})
    assert status == 200
    import time
    for _ in range(50):
        _, st = ui.call("/api/task?since=0")
        if not st["running"] and st["returncode"] is not None:
            break
        time.sleep(0.1)
    assert st["returncode"] == 0 and st["lines"] == ["line 0", "line 1", "line 2"]
    _, later = ui.call(f"/api/task?since={st['next']}")
    assert later["lines"] == []
    assert ui.call("/api/task", {"name": "rm -rf"})[0] == 400


def test_one_task_at_a_time(ui, monkeypatch):
    monkeypatch.setattr(ui.app, "cli", lambda *a: [sys.executable, "-c", "import time; time.sleep(5)"])
    assert ui.call("/api/task", {"name": "rank"})[0] == 200
    status, body = ui.call("/api/task", {"name": "search"})
    assert status == 409 and "still running" in body["error"]
    assert ui.call("/api/task/stop", {})[1]["stopped"] is True


def test_stranger_on_the_port_is_not_trusted(tmp_path, capsys, monkeypatch):
    """Another program (or another account) holding the port, even one imitating job-hunter's page,
    is never treated as job-hunter: no browser is pointed at it, and job-hunter uses a free port."""
    import http.server

    class Fake(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            body = b'<meta name="jh-token" content="x">fake'
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass
    fake = http.server.HTTPServer(("127.0.0.1", 0), Fake)
    threading.Thread(target=fake.serve_forever, daemon=True).start()
    port = fake.server_address[1]
    (tmp_path / "profile.yaml").write_text("x: 1\n")
    opened = []
    monkeypatch.setattr(web, "_open", lambda p: opened.append(p))
    got = {}

    def ready(srv, app):
        got["port"] = app.port
        threading.Thread(target=srv.shutdown, daemon=True).start()
    try:
        assert web.serve(tmp_path / "profile.yaml", port=port, open_browser=False, ready=ready) == 0
    finally:
        fake.shutdown()
    assert got["port"] != port and not opened
    assert "is taken by another program" in capsys.readouterr().out
    assert not (tmp_path / web.LAUNCHER).exists()  # removed when job-hunter stops


def _serve_in_thread(folder, **kw):
    holder, ready = {}, threading.Event()

    def on_ready(srv, app):
        holder.update(server=srv, app=app)
        ready.set()
    t = threading.Thread(target=web.serve, args=(folder / "profile.yaml",),
                         kwargs={"port": 0, "open_browser": False, "ready": on_ready, **kw}, daemon=True)
    t.start()
    assert ready.wait(10)
    return t, holder["app"]


def _post(app, path, token=True):
    h = {"Content-Type": "application/json", **({"X-JH-Token": app.token} if token else {})}
    req = urllib.request.Request(f"http://127.0.0.1:{app.port}{path}", data=b"{}", headers=h, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


def test_quit_button_stops_it(demo):
    from jobhunter.web.server import LAUNCHER
    t, app = _serve_in_thread(demo)
    assert _post(app, "/api/quit", token=False) == 403  # another page can't close it
    assert t.is_alive()
    assert _post(app, "/api/quit") == 200
    t.join(5)
    assert not t.is_alive() and not (demo / LAUNCHER).exists()


def test_stops_by_itself_when_no_page_is_open(demo, monkeypatch):
    monkeypatch.setattr(web, "IDLE_CHECK_SECONDS", 0.05)
    monkeypatch.setattr(web, "IDLE_MINUTES", 0.3 / 60)
    t, app = _serve_in_thread(demo, quit_when_idle=True)
    t.join(5)
    assert not t.is_alive()


def test_stays_up_without_the_idle_option(demo, monkeypatch):
    monkeypatch.setattr(web, "IDLE_CHECK_SECONDS", 0.05)
    monkeypatch.setattr(web, "IDLE_MINUTES", 0.1 / 60)
    t, app = _serve_in_thread(demo)
    t.join(0.6)
    assert t.is_alive()
    assert _post(app, "/api/quit") == 200
    t.join(5)


def test_setup_reads_the_resume_and_offers_lists(ui):
    resume = (b"Jordan Rivera\nChicago, IL | jordan@example.com\nEXPERIENCE\n"
              b"Lakeshore Community Bank, Chicago, IL     2021 - Present\nSenior Credit Underwriter\n"
              b"SKILLS: Excel, Argus\n")
    status, up = ui.call("/api/setup/resume", raw=resume, headers={"X-Filename": "resume.txt"})
    assert status == 200 and up["city"] == "Chicago, IL" and up["titles"] == ["Senior Credit Underwriter"]
    assert up["search_titles"] == ["Credit Underwriter"] and up["current_employers"] == ["Lakeshore Community Bank"]
    assert {"Excel", "Argus"} <= set(up["skills"])
    status, info = ui.call("/api/setup")
    assert "Washington, DC" in info["cities"] and info["fields"]
    status, found = ui.call("/api/setup/titles?q=nurse")
    assert status == 200 and any("Nurse" in t for t in found["titles"])
    # a new resume of another type replaces the old one
    status, up2 = ui.call("/api/setup/resume", raw=b"x", headers={"X-Filename": "resume.md"})
    assert status == 200 and not (ui.folder / "candidate" / "base_resume.txt").exists()
