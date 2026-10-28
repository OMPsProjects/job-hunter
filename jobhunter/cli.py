"""job-hunter command line. Run `job-hunter -h` or `job-hunter <command> -h`.

Getting started:
  setup             answer a few questions -> profile.yaml, candidate.yaml, companies.yaml
  check             validate your settings without searching

Daily:
  search            search every source, confirm on employer sites, rank   (the default)
  rank              re-rank the last run (after changing candidate.yaml or weights)
  health            run history and any source that looks broken

Where to search:
  companies add NAME | discover | list | remove     employers' career sites searched every run
  boards add URL | list | remove                    job boards / career pages you've found

Applying:
  resume FILE       read a resume into candidate.yaml (+ plain text copy)
  render YAML       tailored resume YAML -> PDF, with a page-count check
  lint YAML         flag AI-sounding words and numbers that aren't in your source resume
  answers ...       saved application answers: match | add | fact | check | list
  track ...         application tracker: set | list
  verify            check one posting against the employer's job board

Tuning:
  labels            write a sheet of last run's jobs for you to label (apply / maybe / no)
  eval-rank         score the ranking against your labels; --tune suggests better weights

Everything personal stays in gitignored files: profile.yaml, candidate.yaml, candidate/,
answers.yaml, applications.csv, applications/, companies.yaml, results/, .env.
"""
from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import json
import sys
from pathlib import Path

import pandas as pd

from . import __version__, tracker
from . import answers as answers_mod
from .candidate import draft_candidate, llm_fill, load_candidate, read_resume_text
from .fileio import RunLock, load_dotenv, write_csv_atomic, write_jsonl_atomic, write_text_atomic
from .logs import log
from .logs import setup as setup_logging
from .profile import load_profile

PROJECT = Path(__file__).resolve().parent.parent

OUT_COLS = ["rank", "rank_score", "fit", "seniority", "location_score", "pay_score", "freshness",
            "verified", "title", "company", "location", "pay_top", "min_amount", "max_amount", "interval",
            "date_posted", "years_required", "why", "gaps", "track", "site", "employer_url", "job_url",
            "verify_note", "fit_score", "matched"]


def default_profile() -> Path:
    """./profile.yaml if you're in a folder with one, else the one next to the code."""
    here = Path.cwd() / "profile.yaml"
    return here if here.exists() or not (PROJECT / "profile.yaml").exists() else PROJECT / "profile.yaml"


def out_dir_for(p, args):
    d = Path(args.out) if getattr(args, "out", None) else p.resolve(p.output_dir or "results")
    d.mkdir(parents=True, exist_ok=True)
    return d


def _cols(df, cols):
    return df[[c for c in cols if c in df.columns]]


# ----------------------------- setup / check --------------------------------

def cmd_setup(p, args):
    from .setup import run_setup
    answers_in = None
    if args.from_file:
        import yaml
        answers_in = yaml.safe_load(Path(args.from_file).read_text(encoding="utf-8")) or {}
    print("Let's set up your job search. Press Enter to skip anything optional.")
    # with --from, anything missing from the file takes its default instead of waiting for typing
    interactive = not (args.no_input or args.from_file) and sys.stdin.isatty()
    res = run_setup(p.base, answers_in, ask=input if interactive else None, force=args.force)
    print(f"\nWrote {res['profile'].name} and {res['candidate'].name}.")
    prof = load_profile(res["profile"])
    cmd_check(prof, args)
    print("\nNext: `job-hunter search`." + (
        " Then `job-hunter companies discover --add` to find more employers hiring for these roles."
        if res["answers"].get("discover_companies") else ""))
    return 0


def cmd_check(p, args):
    n = len(p.all_titles())
    passes = len(p.locations) + (1 if p.include_remote else 0)
    on = [k for k in p.sources if p.source_on(k)]
    print(f"Profile OK: {len(p.tracks)} tracks, {n} titles x {passes} location passes "
          f"= {n * passes} board searches, {sum(len(f['companies']) for f in p.feeds) + len(p.target_companies)} "
          f"company career sites.")
    print(f"Sources on: {', '.join(on)}" + (f"; boards: {', '.join(p.sites)}" if p.source_on("jobspy") else ""))
    cand = load_candidate(p.resolve(p.candidate_file))
    print(f"Candidate file: {'found' if cand else 'missing (ranking falls back to keyword scores)'}"
          + (f", {len(cand.skills)} skills, {len(cand.target_titles)} target titles" if cand else ""))
    if p.browse_boards:
        print(f"Browser-search list (the Claude skill): {', '.join(b.get('name', '?') for b in p.browse_boards)}")
    problems = p.problems()
    for msg in problems:
        print(f"  - {msg}")
    return 1 if any("no tracks" in m or "bad regex" in m for m in problems) else 0


# ----------------------------- search ---------------------------------------

def score_verify_rank(jobs, p, args, out):
    from .rank import rank
    from .scoring import score_row
    from .verify import verify_frame

    jobs = jobs.copy()
    if jobs.empty:
        return jobs.assign(fit_score=[], matched=[]), pd.DataFrame(), pd.DataFrame()
    jobs[["fit_score", "matched"]] = jobs.apply(score_row, axis=1, p=p)
    jobs = jobs[jobs.fit_score >= p.min_score].sort_values("fit_score", ascending=False)
    if p.verify_enabled and not getattr(args, "no_verify", False) and len(jobs):
        top = jobs.head(p.verify_top_n)
        rest = jobs.iloc[len(top):]
        log.info(f"\nVerifying the top {len(top)} on employer sites...")
        jobs = pd.concat([verify_frame(top, p, out / "ats_cache.json"), rest])
    cand = load_candidate(p.resolve(p.candidate_file))
    ranked, excluded = rank(jobs, p, cand, tracker.load(p.resolve(p.tracker_file)))
    return jobs, ranked, excluded


def write_outputs(out, jobs, ranked, excluded, new_urls, write_all=True):
    detail_cols = OUT_COLS + ["description", "region", "req_id", "note", "query", "job_url_direct"]
    if write_all:
        write_csv_atomic(_cols(jobs, OUT_COLS + ["job_url_direct"]), out / "jobs_all.csv")
    if ranked.empty:
        for name in ("ranked.csv", "jobs_new.csv"):
            write_csv_atomic(pd.DataFrame(columns=OUT_COLS), out / name)
        write_text_atomic(out / "jobs_new_details.jsonl", "")
    else:
        new_ranked = ranked[ranked["job_url"].isin(new_urls)].drop(columns=["rank"]).reset_index(drop=True)
        new_ranked.insert(0, "rank", range(1, len(new_ranked) + 1))
        write_csv_atomic(_cols(new_ranked, OUT_COLS), out / "ranked.csv")
        write_csv_atomic(_cols(new_ranked, OUT_COLS), out / "jobs_new.csv")  # kept for older scripts
        write_jsonl_atomic(_cols(new_ranked, detail_cols), out / "jobs_new_details.jsonl")
        ranked = new_ranked
    exc_cols = ["excluded_reason", "verified", "title", "company", "location", "employer_url", "job_url", "verify_note"]
    write_csv_atomic(_cols(excluded, exc_cols) if len(excluded) else pd.DataFrame(columns=exc_cols), out / "excluded.csv")
    return ranked


def cmd_search(p, args):
    from .sources import NoResults, gather
    from .store import Store

    out = out_dir_for(p, args)
    setup_logging(out, verbose=args.verbose)
    for msg in p.problems():
        log.warning(msg)
    store = Store(out / "jobhunter.db")
    imported = store.import_seen_csv(out / "seen_jobs.csv")
    if imported:
        log.info(f"Imported {imported} previously seen jobs from seen_jobs.csv.")
    try:
        with RunLock(out):
            run_id = store.start_run()
            try:
                log.info("Searching...")
                only = None
                if getattr(args, "sources", None):
                    from .sources import ALL_SOURCES
                    only = {s.strip() for s in args.sources.split(",") if s.strip()}
                    unknown = only - set(ALL_SOURCES)
                    if unknown:
                        log.error(f"Unknown source(s): {', '.join(sorted(unknown))}. Use: {', '.join(ALL_SOURCES)}")
                        store.finish_run(run_id, "failed", {"error": "unknown source"})
                        return 1
                    off = [s for s in only if not p.source_on(s)]
                    if off:
                        log.warning(f"Turned off in your profile (or missing API keys), so skipped: {', '.join(off)}")
                try:
                    jobs, stats = gather(p, only=only)
                except NoResults as e:
                    store.finish_run(run_id, "failed", {"error": str(e)})
                    log.error(str(e))
                    return 1
                store.record_sources(run_id, stats)
                seen = store.seen_urls()
                jobs, ranked, excluded = score_verify_rank(jobs, p, args, out)
                if ranked.empty and excluded.empty:
                    log.info("\nNo jobs cleared min_score this run. Nothing to rank.")
                new_urls = set(jobs.job_url) - seen if len(jobs) else set()
                new_ranked = write_outputs(out, jobs, ranked, excluded, new_urls)
                if len(jobs):
                    store.mark_seen(zip(jobs["job_url"], jobs["company"], jobs["title"], strict=True))
                if getattr(args, "llm", False):
                    llm_rerank(out, p)
                health = store.health(list(stats))
                summary = {"run_at": dt.datetime.now().isoformat(timespec="minutes"), "scored": int(len(jobs)),
                           "new": int(len(new_ranked)), "excluded": int(len(excluded)),
                           "verified": jobs["verified"].value_counts().to_dict() if "verified" in jobs and len(jobs) else {},
                           "sources": stats, "health_warnings": health}
                write_text_atomic(out / "run_summary.json", json.dumps(summary, indent=1, default=str))
                store.finish_run(run_id, "ok", summary)
            except BaseException as e:
                store.finish_run(run_id, "failed", {"error": f"{type(e).__name__}: {e}"})
                raise
    except RuntimeError as e:  # lock held by another run
        log.error(str(e))
        return 1
    finally:
        store.close()

    log.info(f"\n{len(jobs)} scored, {len(new_ranked)} new and ranked, {len(excluded)} excluded "
             f"(files in {out}/).")
    for w in health:
        log.warning(f"source health: {w}")
    if len(new_ranked):
        log.info("Top 20 new:\n" + _cols(new_ranked, ["rank", "rank_score", "verified", "title", "company", "location"])
                 .head(20).to_string(index=False))
    return 0


def cmd_health(p, args):
    from .store import Store
    out = out_dir_for(p, args)
    path = out / "jobhunter.db"
    if not path.exists():
        print("No runs recorded yet. Run `job-hunter search` first.")
        return 0
    store = Store(path)
    try:
        print("Recent runs:")
        for rid, started, _finished, status, summary in store.last_runs(args.runs):
            s = json.loads(summary or "{}")
            print(f"  #{rid} {started} {status:7} scored {s.get('scored', '-')}, new {s.get('new', '-')}"
                  + (f"  error: {s['error']}" if s.get("error") else ""))
        names = [r[0] for r in store.db.execute("SELECT DISTINCT source FROM source_stats ORDER BY source")]
        if names:
            print("\nJobs per source, most recent run first:")
            for name in names:
                h = store.history(name, 8)
                print(f"  {name:14} " + " ".join(f"{r[2]:>4}" + ("!" if r[3] else " ") for r in h))
            print("  (! = some requests failed that run)")
        warnings = store.health(names)
        print("\n" + ("\n".join(f"WARNING {w}" for w in warnings) if warnings else "All sources look healthy."))
        return 2 if warnings else 0
    finally:
        store.close()


def cmd_rank(p, args):
    """Re-rank the last run's new jobs without searching (e.g. after editing candidate.yaml)."""
    from .rank import rank
    from .scoring import score_row

    out = out_dir_for(p, args)
    src = out / "jobs_new_details.jsonl"
    if not src.exists():
        print(f"No {src}. Run a search first.")
        return 1
    jobs = pd.read_json(src, lines=True) if src.stat().st_size else pd.DataFrame()
    if not len(jobs):
        print("Last run had no new jobs.")
        return 0
    jobs[["fit_score", "matched"]] = jobs.apply(score_row, axis=1, p=p)
    ranked, excluded = rank(jobs, p, load_candidate(p.resolve(p.candidate_file)),
                            tracker.load(p.resolve(p.tracker_file)))
    try:
        with RunLock(out):
            ranked = write_outputs(out, jobs, ranked, excluded, set(jobs.job_url), write_all=False)
    except RuntimeError as e:
        print(e)
        return 1
    if len(ranked):
        print(_cols(ranked, ["rank", "rank_score", "verified", "title", "company", "location"]).head(20).to_string(index=False))
    else:
        print("Nothing left after filters; see excluded.csv.")
    return 0


def llm_rerank(out, p):
    """Optional: ask Claude for a fit note on the top N (needs ANTHROPIC_API_KEY)."""
    import re
    try:
        import anthropic
    except ImportError:
        log.warning("pip install anthropic to use --llm")
        return
    summary = p.candidate_summary
    cand = load_candidate(p.resolve(p.candidate_file))
    if cand and cand.raw.get("summary"):
        summary = summary or cand.raw["summary"]
    if not summary:
        log.warning("No candidate summary (llm.candidate_summary or candidate.yaml summary); skipping --llm")
        return
    path = out / "jobs_new_details.jsonl"
    if not path.stat().st_size:
        return
    df = pd.read_json(path, lines=True)
    client = anthropic.Anthropic()
    df["llm_fit"], df["llm_note"] = pd.NA, ""
    for idx in df.head(p.llm_top_n).index:
        r = df.loc[idx]
        prompt = (f"Candidate:\n{summary}\n\nJob: {r['title']} at {r['company']} ({r['location']})\n"
                  f"{str(r.get('description', ''))[:3500]}\n\nReturn ONLY JSON: "
                  '{"fit": 0-100, "gap": "biggest gap in <=15 words", "why": "why it fits in <=20 words"}')
        try:
            msg = client.messages.create(model=p.llm_model, max_tokens=300, messages=[{"role": "user", "content": prompt}])
            data = json.loads(re.sub(r"```json|```", "", msg.content[0].text).strip())
            df.at[idx, "llm_fit"], df.at[idx, "llm_note"] = data["fit"], f"{data['why']} | gap: {data['gap']}"
        except Exception as e:
            log.warning(f"llm skipped {r['title']}: {e}")
    write_jsonl_atomic(df, path)
    write_csv_atomic(_cols(df, OUT_COLS + ["llm_fit", "llm_note"]), out / "ranked.csv")


def cmd_verify(p, args):
    from .verify import Verifier
    out = out_dir_for(p, args)
    v = Verifier(p, out / "ats_cache.json")
    res = v.verify_one({"title": args.title, "company": args.company, "location": args.location,
                        "job_url": args.url, "job_url_direct": args.url})
    v.save()
    print(json.dumps(res, indent=1))
    return 0 if res["verified"] in ("verified_open", "employer_page_live") else 2


# ----------------------------- companies / boards ---------------------------

def _targets(p):
    from .targets import Targets
    return Targets(p.resolve(p.companies_file))


def cmd_companies(p, args):
    from .targets import add_by_name, add_from_url, discover_companies, employers_from_results
    t = _targets(p)
    if args.action == "list":
        if not t.companies:
            print("No companies yet. Add one: job-hunter companies add \"Name\"  (or: companies discover)")
        for c in t.companies:
            print(f"  {c['name']:35} {c['ats']}/{c['slug']}" + (f"  track={c['track']}" if c.get("track") else "")
                  + (f"  ({c['source']})" if c.get("source") else "") + (f"  note: {c['note']}" if c.get("note") else ""))
        return 0
    if args.action == "remove":
        print("removed" if t.remove(args.name) else f"{args.name} isn't on the list")
        return 0
    if args.action == "add":
        if not args.name:
            print('companies add needs a name: job-hunter companies add "Acme Bank"')
            return 1
        ok, msg = add_from_url(t, args.url, name=args.name, track=args.track) if args.url else add_by_name(t, args.name, args.track)
        print(msg)
        return 0 if ok else 2
    if args.action == "discover":
        return _discover(p, args, t, discover_companies, employers_from_results)
    return 1


def _discover(p, args, t, discover_companies, employers_from_results):
    """Employers posting roles like yours -> their career sites -> (optionally) added."""
    out = out_dir_for(p, args)
    setup_logging(None)
    src = out / "jobs_all.csv"
    if src.exists() and not args.fresh:
        jobs = pd.read_csv(src)
        log.info(f"Using employers from your last search ({len(jobs)} jobs). --fresh runs a quick new search.")
    else:
        from .sources import NoResults, gather
        log.info("Running a quick search to see who's hiring for your titles...")
        quick = set(args.quick_sources.split(","))
        try:
            jobs, _ = gather(p, only=quick)
        except NoResults as e:
            log.error(str(e))
            return 1
    employers = employers_from_results(jobs, min_posts=args.min_posts,
                                       exclude=p.exclude_companies + [c["name"] for c in t.companies])
    if not employers:
        print("No employers found in the results.")
        return 0
    log.info(f"Checking career sites for the top {min(args.limit, len(employers))} employers...")
    rows = discover_companies(t, employers, profile=p, limit=args.limit, add=args.add, track=args.track)
    found = [r for r in rows if r.get("ats")]
    print(f"\n{len(found)} of {len(rows)} have a career site job-hunter can read"
          + (" and were added to companies.yaml." if args.add else ". Run again with --add to add them."))
    none = [r["name"] for r in rows if r.get("status") == "no readable career site found"]
    if none:
        print("No readable site (add their careers page with `boards add URL` if you want them): " + ", ".join(none[:15]))
    return 0


def cmd_boards(p, args):
    from .targets import add_from_url
    t = _targets(p)
    if args.action == "list":
        if not t.browse_boards and not p.browse_boards:
            print("No boards added yet. Add one: job-hunter boards add https://...")
        for b in p.browse_boards:
            print(f"  {b.get('name', '?'):30} {b.get('url')}" + (f"  note: {b['note']}" if b.get("note") else ""))
        return 0
    if args.action == "remove":
        print("removed" if t.remove(args.url) else f"{args.url} isn't on the list")
        return 0
    if args.action == "add":
        if not args.url:
            print("boards add needs a URL: job-hunter boards add https://jobs.example.com")
            return 1
        ok, msg = add_from_url(t, args.url, name=args.name, track=args.track)
        print(msg)
        return 0 if ok else 2
    return 1


# ----------------------------- resume ---------------------------------------

def cmd_resume(p, args):
    import yaml
    src = Path(args.file)
    if not src.exists():
        print(f"No file at {src}")
        return 1
    text = read_resume_text(src)
    folder = p.resolve("candidate")
    folder.mkdir(exist_ok=True)
    write_text_atomic(folder / "resume.txt", text, private=True)
    cand_path = p.resolve(p.candidate_file)
    if cand_path.exists() and not args.force:
        print(f"Saved the text to {folder / 'resume.txt'}. {cand_path.name} already exists; use --force to redraft it.")
        return 0
    data = draft_candidate(text, src.resolve())
    if args.llm:
        data = llm_fill(data, text, p.llm_model)
    header = ("# candidate.yaml - your resume, structured. Private (gitignored).\n"
              "# Ranking uses skills, titles, levels and years. Tailoring may only use facts from\n"
              "# base_resume and facts_files. Fill the empty lists in, or ask Claude to.\n")
    write_text_atomic(cand_path, header + yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=1000))
    print(f"Wrote {cand_path} and {folder / 'resume.txt'} ({len(text.split())} words). "
          f"Years of experience guessed: {data.get('years_experience')}.")
    empty = [k for k in ("target_titles", "past_titles", "target_levels", "skills")
             if not data.get(k) or data.get(k) == {"core": [], "other": []}]
    if empty:
        print(f"Still empty: {', '.join(empty)}. Fill these in (or run with --llm, or ask Claude).")
    return 0


def cmd_render(p, args):
    from .render import render
    out = Path(args.output or Path(args.yaml).with_suffix(".pdf"))
    res = render(args.yaml, out, target_pages=args.pages)
    print(json.dumps({"pdf": str(out), **res}))
    if not res["fits"]:
        print(f"Over {args.pages} page(s) even at {res['font_size']}pt: cut bullets.", file=sys.stderr)
        return 2
    return 0


def cmd_lint(p, args):
    from .humanize import fact_check, lint_text, read_sources
    from .render import all_bullets, load_resume, resume_text
    data = load_resume(args.yaml)
    text = resume_text(data)
    issues = lint_text(text, all_bullets(data))
    sources = list(args.sources or [])
    cand = load_candidate(p.resolve(p.candidate_file))
    if not sources:
        if cand:
            sources += [cand.raw.get("base_resume", "")] + list(cand.raw.get("facts_files", []) or [])
        sources.append(str(p.resolve("candidate/resume.txt")))
    src_texts = read_sources([p.resolve(s) for s in sources if s])
    missing = fact_check(text, src_texts, allowed=[cand.years] if cand else []) if src_texts else []
    for level, msg in issues:
        print(f"[{level}] {msg}")
    for m in missing:
        print(f"[error] number {m} isn't in your source resume or facts files: check it isn't invented")
    if not src_texts:
        print("[warn] no source resume found, so numbers weren't fact-checked")
    errors = sum(1 for lvl, _ in issues if lvl == "error") + len(missing)
    print(f"{errors} error(s), {sum(1 for lvl, _ in issues if lvl == 'warn')} warning(s)")
    return 1 if errors else 0


# ----------------------------- answers / tracker ----------------------------

def cmd_answers(p, args):
    bank = answers_mod.AnswerBank(p.resolve(p.answers_file))
    if args.action == "match":
        hit = bank.match(args.question)
        reason = answers_mod.blocked(args.question)
        print(json.dumps(hit if hit else {"match": None, "blocked": reason}, indent=1, default=str))
        return 0 if hit else 1
    if args.action == "add":
        ok, msg = bank.add(args.question, args.answer, source=args.source)
        print(msg)
        return 0 if ok else 2
    if args.action == "fact":
        ok, msg = bank.set_fact(args.question, args.answer)
        print(msg)
        return 0 if ok else 2
    if args.action == "check":
        reason = answers_mod.blocked(args.question, args.answer or "")
        print(json.dumps({"blocked": reason}))
        return 2 if reason else 0
    print(json.dumps({"facts": bank.facts, "answers": bank.answers}, indent=1, default=str))
    return 0


def cmd_track(p, args):
    path = p.resolve(p.tracker_file)
    if args.action == "list":
        df = tracker.load(path)
        print(df.to_string(index=False) if len(df) else "No applications tracked yet.")
        return 0
    if not (args.status and args.company and args.title):
        print("track set needs --status, --company and --title")
        return 1
    row = tracker.upsert(path, args.status, args.company, args.title, location=args.location,
                         job_url=args.url, employer_url=args.employer_url, resume_pdf=args.resume,
                         rank_score=args.score, notes=args.notes)
    print(json.dumps(row, default=str))
    return 0


# ----------------------------- ranking evaluation ---------------------------

def cmd_labels(p, args):
    from .evalrank import make_label_sheet
    out = out_dir_for(p, args)
    src = out / "ranked.csv"
    dest = out / "labels.csv"
    if not src.exists() or not src.stat().st_size:
        print("No ranked.csv yet. Run a search first.")
        return 1
    ranked = pd.read_csv(src)
    existing = pd.read_csv(dest, dtype={"label": str}) if dest.exists() else None
    sheet = make_label_sheet(ranked, n=args.n, existing=existing)
    added = len(sheet) - (len(existing) if existing is not None else 0)
    write_csv_atomic(sheet, dest)
    print(f"{dest}: {len(sheet)} jobs ({added} new from the last run; your existing labels are kept).\n"
          f"Fill in label: 2 = would apply, 1 = maybe, 0 = no. Then run: job-hunter eval-rank")
    return 0


def cmd_eval_rank(p, args):
    from .evalrank import evaluate, tune
    out = out_dir_for(p, args)
    labels_p = Path(args.labels) if args.labels else out / "labels.csv"
    if not labels_p.exists():
        print("No labels yet. Run `job-hunter labels` and fill in the label column.")
        return 1
    labels = pd.read_csv(labels_p, dtype={"label": str})
    ranked_p = out / "ranked.csv"
    ranked = pd.read_csv(ranked_p) if ranked_p.exists() and ranked_p.stat().st_size else None
    res = evaluate(ranked, labels, p.weights, low_fit_threshold=p.low_fit_threshold)
    if not res:
        print("No usable labels yet (use 2, 1 or 0 in the label column).")
        return 1
    print(f"Your current weights {p.weights}:\n  {res}")
    if res["labeled"] < 30:
        print(f"  Only {res['labeled']} labeled jobs: treat these numbers as rough (aim for 50+).")
    if args.tune:
        best = tune(ranked, labels, low_fit_threshold=p.low_fit_threshold, step=args.step)
        print("\nBest weight sets on your labels (ndcg@10, precision@10):")
        for nd, pr, w in best:
            print(f"  {nd:.3f} {pr:.3f}  {w}")
        print("Copy one into profile.yaml -> ranking.weights if it beats yours by a clear margin. With few labels,"
              " big swings are likely noise.")
    return 0


# ----------------------------- CLI ------------------------------------------

def _common(parser, suppress):
    """Options that work before or after the command (job-hunter search --no-verify)."""
    def d(v):
        return argparse.SUPPRESS if suppress else v
    parser.add_argument("--profile", default=d(None), help="profile file (default: ./profile.yaml)")
    parser.add_argument("--out", default=d(None), help="results folder (default: profile output_dir, else ./results)")
    parser.add_argument("-v", "--verbose", action="store_true", default=d(False), help="more detail on screen")


def build_parser():
    ap = argparse.ArgumentParser(prog="job-hunter", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", action="version", version=f"job-hunter {__version__}")
    _common(ap, False)
    ap.add_argument("--check", action="store_true", help="validate the profile and exit")
    ap.add_argument("--llm", action="store_true", default=False, help=argparse.SUPPRESS)
    ap.add_argument("--no-verify", action="store_true", default=False, help=argparse.SUPPRESS)
    ap.add_argument("--sources", default=None, help=argparse.SUPPRESS)
    sub = ap.add_subparsers(dest="cmd", metavar="command")

    def add(name, **kw):
        sp = sub.add_parser(name, **kw)
        _common(sp, True)
        return sp

    st = add("setup", help="answer a few questions to build your profile")
    st.add_argument("--from", dest="from_file", help="read answers from a YAML file instead of asking")
    st.add_argument("--force", action="store_true", help="replace an existing profile.yaml (kept as .bak)")
    st.add_argument("--no-input", action="store_true", help="don't ask; use defaults for anything not in --from")
    # (also non-interactive automatically when --from is given or input isn't a terminal)
    add("check", help="validate your settings")
    se = add("search", help="search, verify, rank (default)")
    se.add_argument("--llm", action="store_true", default=argparse.SUPPRESS, help="add a Claude fit note to the top matches")
    se.add_argument("--no-verify", action="store_true", default=argparse.SUPPRESS, help="skip employer-site verification")
    se.add_argument("--sources", default=argparse.SUPPRESS, help="only these sources, e.g. jobspy,remotive,company_feeds")
    add("rank", help="re-rank the last run")
    hl = add("health", help="run history and broken-looking sources")
    hl.add_argument("--runs", type=int, default=10)
    v = add("verify", help="check one posting on the employer's site")
    v.add_argument("--url", required=True)
    v.add_argument("--company", required=True)
    v.add_argument("--title", required=True)
    v.add_argument("--location", default="")

    co = add("companies", help="employers' career sites searched every run")
    co.add_argument("action", choices=["add", "discover", "list", "remove"])
    co.add_argument("name", nargs="?", default="", help="company name (add / remove)")
    co.add_argument("--url", help="add: the company's careers page, if you have it")
    co.add_argument("--track", help="which of your tracks these jobs belong to (default: closest title)")
    co.add_argument("--add", action="store_true", help="discover: add what's found to companies.yaml")
    co.add_argument("--limit", type=int, default=40, help="discover: how many employers to check")
    co.add_argument("--min-posts", type=int, default=1, help="discover: only employers with at least this many matching posts")
    co.add_argument("--fresh", action="store_true", help="discover: run a quick new search instead of using the last one")
    co.add_argument("--quick-sources", default="jobspy,himalayas,remotive", help="discover --fresh: sources to use")
    bo = add("boards", help="job boards and career pages you've found")
    bo.add_argument("action", choices=["add", "list", "remove"])
    bo.add_argument("url", nargs="?", default="")
    bo.add_argument("--name", help="a label for it")
    bo.add_argument("--track", help="which track its jobs belong to (career sites only)")

    r = add("resume", help="read a resume file into candidate.yaml")
    r.add_argument("file")
    r.add_argument("--force", action="store_true", help="overwrite an existing candidate.yaml")
    r.add_argument("--llm", action="store_true", help="have Claude fill titles/levels/skills (needs ANTHROPIC_API_KEY)")
    rd = add("render", help="tailored resume YAML -> PDF")
    rd.add_argument("yaml")
    rd.add_argument("--output", "-o")
    rd.add_argument("--pages", type=int, help="target page count (1 or 2)")
    ln = add("lint", help="humanizer lint + fact check for a tailored resume YAML")
    ln.add_argument("yaml")
    ln.add_argument("--sources", nargs="*", help="files to fact-check against (default: from candidate.yaml)")
    an = add("answers", help="saved application answers")
    an.add_argument("action", choices=["match", "add", "fact", "check", "list"])
    an.add_argument("question", nargs="?", default="")
    an.add_argument("answer", nargs="?", default="")
    an.add_argument("--source", default="you", choices=["you", "resume"])
    tr = add("track", help="application tracker")
    tr.add_argument("action", choices=["set", "list"])
    tr.add_argument("--status", choices=tracker.STATUSES)
    tr.add_argument("--company")
    tr.add_argument("--title")
    tr.add_argument("--location")
    tr.add_argument("--url")
    tr.add_argument("--employer-url")
    tr.add_argument("--resume")
    tr.add_argument("--score")
    tr.add_argument("--notes")

    lb = add("labels", help="add the last run's jobs to your label sheet (keeps existing labels)")
    lb.add_argument("-n", type=int, default=60)
    ev = add("eval-rank", help="score the ranking against your labels")
    ev.add_argument("--labels", help="labels file (default: results/labels.csv)")
    ev.add_argument("--tune", action="store_true", help="search for better weights")
    ev.add_argument("--step", type=int, default=10, help="--tune grid step")
    return ap


COMMANDS = {
    "setup": cmd_setup, "check": cmd_check, "search": cmd_search, "rank": cmd_rank, "health": cmd_health,
    "verify": cmd_verify, "companies": cmd_companies, "boards": cmd_boards, "resume": cmd_resume,
    "render": cmd_render, "lint": cmd_lint, "answers": cmd_answers, "track": cmd_track,
    "labels": cmd_labels, "eval-rank": cmd_eval_rank,
}
NEEDS_PROFILE = {"search", "rank", "check", "verify", "companies", "boards", "health", "labels", "eval-rank"}


def main(argv=None):
    # Job titles are full of en dashes and accents; never crash printing them to a Windows
    # console or a redirected log in a legacy code page.
    for stream in (sys.stdout, sys.stderr):
        with contextlib.suppress(AttributeError, ValueError):
            stream.reconfigure(errors="replace")
    args = build_parser().parse_args(argv)
    cmd = args.cmd or "search"
    profile_path = Path(args.profile) if args.profile else default_profile()
    load_dotenv(profile_path.parent / ".env")  # API keys live in .env, never in profile.yaml
    setup_logging(None, verbose=getattr(args, "verbose", False))
    if args.check:
        cmd = "check"
    p = load_profile(profile_path, required=cmd in NEEDS_PROFILE)
    try:
        return COMMANDS[cmd](p, args)
    except KeyboardInterrupt:
        print("\nStopped.")
        return 130
    except BrokenPipeError:  # output piped into `head` etc.
        return 0


if __name__ == "__main__":
    sys.exit(main())
