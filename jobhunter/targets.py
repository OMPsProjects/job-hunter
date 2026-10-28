"""companies.yaml: the employers' career sites searched every run, and the boards you've added.

Kept apart from profile.yaml so `job-hunter companies add` / `boards add` / `companies discover`
can rewrite it freely without touching your hand-edited settings. Safe to edit by hand too.

  companies:      employers whose career site the script can read (an ATS with a public API).
                  Every run pulls their open roles and keeps the ones close to your search titles.
  browse_boards:  job boards and career pages the script can't read. The Claude skill searches
                  these in your browser when you ask for a full sweep.
"""
from __future__ import annotations

import datetime as dt
import urllib.parse
from collections import Counter
from pathlib import Path

import yaml

from .common import company_key
from .fileio import write_text_atomic
from .logs import log
from .sources import ats

HEADER = """# companies.yaml - career sites and job boards job-hunter searches.
# Managed by `job-hunter companies ...` and `job-hunter boards ...`; editing by hand is fine.
#   companies:     career sites read by script every run (ats: greenhouse | lever | ashby |
#                  smartrecruiters | workable | recruitee | workday). track is optional.
#   browse_boards: sites the script can't read; the Claude skill searches them in your browser.
"""


class Targets:
    def __init__(self, path: Path):
        self.path = Path(path)
        data: dict = {}
        if self.path.exists():
            data = yaml.safe_load(self.path.read_text(encoding="utf-8")) or {}
        self.companies: list[dict] = list(data.get("companies") or [])
        self.browse_boards: list[dict] = list(data.get("browse_boards") or [])

    def save(self):
        body = yaml.safe_dump({"companies": self.companies, "browse_boards": self.browse_boards},
                              sort_keys=False, allow_unicode=True, width=1000)
        write_text_atomic(self.path, HEADER + body, private=False)

    # -- lookups ---------------------------------------------------------------
    def has_company(self, name=None, ats_kind=None, slug=None):
        for c in self.companies:
            if name and company_key(c.get("name")) == company_key(name):
                return c
            if ats_kind and slug and c.get("ats") == ats_kind and str(c.get("slug")).lower() == str(slug).lower():
                return c
        return None

    def has_board(self, url):
        host = urllib.parse.urlparse(url).netloc.lower().removeprefix("www.")
        path = urllib.parse.urlparse(url).path.rstrip("/")
        for b in self.browse_boards:
            u = urllib.parse.urlparse(b.get("url", ""))
            if u.netloc.lower().removeprefix("www.") == host and u.path.rstrip("/") == path:
                return b
        return None

    # -- adding ----------------------------------------------------------------
    def add_company(self, name, kind, slug, track=None, source="you", confirmed=None, how=None):
        existing = self.has_company(name, kind, slug)
        if existing:
            return False, f"{existing['name']} is already on the list ({existing['ats']}/{existing['slug']})"
        entry = {"name": name, "ats": kind, "slug": slug}
        if track:
            entry["track"] = track
        entry.update({"source": source, "added": dt.date.today().isoformat()})
        if confirmed is False:
            entry["note"] = ("found in the careers-site directory by name" if how == "directory"
                             else "board found by name guess") + "; check it's the right company"
        self.companies.append(entry)
        self.save()
        return True, f"added {name} ({kind}/{slug})"

    def add_board(self, url, name=None, note=None):
        if self.has_board(url):
            return False, f"{url} is already on the browse list"
        host = urllib.parse.urlparse(url).netloc.removeprefix("www.")
        entry = {"name": name or host, "url": url, "added": dt.date.today().isoformat()}
        if note:
            entry["note"] = note
        self.browse_boards.append(entry)
        self.save()
        return True, f"added {entry['name']} to the browser-search list"

    def remove(self, name_or_url):
        before = len(self.companies) + len(self.browse_boards)
        self.companies = [c for c in self.companies if company_key(c.get("name")) != company_key(name_or_url)]
        self.browse_boards = [b for b in self.browse_boards
                              if b.get("url") != name_or_url and company_key(b.get("name")) != company_key(name_or_url)]
        changed = before != len(self.companies) + len(self.browse_boards)
        if changed:
            self.save()
        return changed


# ----------------------------- resolving a URL or name ------------------------

def resolve_url(url):
    """(ats, slug) when the URL is a careers site on a readable ATS, else (None, None)."""
    kind, slug = ats.ats_from_url(url)
    if kind in ats.FETCHERS:
        return kind, slug
    return None, None


def add_from_url(targets: Targets, url, name=None, track=None):
    """`boards add URL`: a readable ATS becomes a company feed (after checking it answers);
    anything else goes on the browser-search list."""
    if not urllib.parse.urlparse(url).scheme:
        url = "https://" + url
    kind, slug = resolve_url(url)
    if kind:
        try:
            rows = ats.list_postings(kind, name or slug, slug, with_description=False)
        except Exception as e:
            return targets.add_board(url, name, note=f"looks like {kind} but its API didn't answer ({e})")
        label = name or slug.split("|")[0].replace("-", " ").title()
        ok, msg = targets.add_company(label, kind, slug, track=track, source="you")
        return ok, f"{msg}: {len(rows)} open roles right now" if ok else msg
    return targets.add_board(url, name)


def add_by_name(targets: Targets, name, track=None):
    """`companies add NAME`: find the company's ATS by probing likely board names."""
    from .verify import discover
    found = discover(name)
    hint = f'If you have its careers page URL, run: job-hunter boards add <url> --name "{name}"'
    if not found.get("ats"):
        why = "" if found.get("definitive", True) else " (some lookups failed; try again later)"
        return False, f"Couldn't find a readable career site for {name}{why}. {hint}"
    postings = _postings(found, name)
    if not postings and found.get("how") == "directory":  # the directory can be out of date
        retry = discover(name, use_directory=False)
        if retry.get("ats"):
            found, postings = retry, _postings(retry, name)
    if not postings:
        # a name match on an empty board is usually someone else's dormant account
        return False, (f"Found a {found['ats']} board called '{found['slug']}', but it lists no open roles, "
                       f"so it's probably not {name}'s. {hint}")
    ok, msg = targets.add_company(name, found["ats"], found["slug"], track=track, source="you",
                                  confirmed=found.get("confirmed"), how=found.get("how"))
    return ok, f"{msg}: {len(postings)} open roles right now" if ok else msg


def _postings(found, name):
    try:
        return ats.list_postings(found["ats"], name, found["slug"], with_description=False)
    except Exception:
        return []


# ----------------------------- discovery -------------------------------------

def employers_from_results(jobs, min_posts=1, exclude=()):
    """Companies posting roles like yours, most frequent first: [(name, count, [urls])].
    The urls (employer / direct apply links) often point straight at the company's ATS."""
    if jobs is None or jobs.empty or "company" not in jobs:
        return []
    blocked = {company_key(x) for x in exclude}
    counts, display, urls = Counter(), {}, {}
    for _, r in jobs.iterrows():
        n = r.get("company")
        if not isinstance(n, str) or not n.strip():
            continue
        k = company_key(n)
        if not k or k in blocked:
            continue
        counts[k] += 1
        display.setdefault(k, n.strip())
        for col in ("employer_url", "job_url_direct", "job_url"):
            u = r.get(col)
            if isinstance(u, str) and u.startswith("http"):
                urls.setdefault(k, []).append(u)
    return [(display[k], c, urls.get(k, [])) for k, c in counts.most_common() if c >= min_posts]


STAFFING_HINTS = ("staffing", "recruit", "talent", "search", "consult", "jobs", "careers", "hire", "placement",
                  "resourcing", "associates llc")


def looks_like_agency(name):
    n = str(name).lower()
    return any(h in n for h in STAFFING_HINTS)


def _board_from_urls(urls):
    for u in urls:
        kind, slug = resolve_url(u)
        if kind:
            return {"ats": kind, "slug": slug, "confirmed": True, "how": "apply link"}
    return None


def discover_companies(targets: Targets, employers, profile=None, limit=40, add=False, track=None):
    """Find each employer's career site (from its apply links first, then by probing likely board
    names), and keep it only if the board lists open roles. Returns rows of
    dict(name, posts, ats, slug, confirmed, open_roles, matching, status)."""
    from .sources.apis import best_track
    from .verify import discover
    results = []
    for item in employers[:limit]:
        name, posts, urls = (item + ([],))[:3] if len(item) == 2 else item
        if looks_like_agency(name):
            results.append({"name": name, "posts": posts, "status": "skipped: looks like a staffing agency"})
            continue
        if targets.has_company(name):
            results.append({"name": name, "posts": posts, "status": "already on your list"})
            continue
        found = _board_from_urls(urls) or discover(name)
        row = {"name": name, "posts": posts, "ats": found.get("ats"), "slug": found.get("slug"),
               "confirmed": found.get("confirmed")}
        if not found.get("ats"):
            row["status"] = "no readable career site found"
        else:
            try:
                postings = ats.list_postings(found["ats"], name, found["slug"], with_description=False)
            except Exception:
                postings = []
            row["open_roles"] = len(postings)
            row["matching"] = sum(1 for r in postings if profile and best_track(r.get("title"), profile)[0])
            if not postings:
                row["status"] = "board found but it lists no open roles (likely the wrong board); skipped"
                row["ats"] = None
            elif add:
                confirmed = found.get("confirmed") or row["matching"] > 0
                ok, msg = targets.add_company(name, found["ats"], found["slug"], track=track, source="discovered",
                                              confirmed=confirmed, how=found.get("how"))
                row["status"] = "added" if ok else msg
            else:
                row["status"] = "found"
        extra = f" ({row['ats']}/{row['slug']}, {row.get('open_roles', 0)} open, {row.get('matching', 0)} like yours)" \
            if row.get("ats") else ""
        log.info(f"  {name[:40]:40} {posts:>3} posts  {row['status']}{extra}")
        results.append(row)
    return results
