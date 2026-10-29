"""Field packs: employers and recruiters known to hire for one kind of work, ready to add to the
daily search in one step. Each pack is a YAML file in jobhunter/data/packs/:

    name: Commercial real estate finance
    keywords: [commercial real estate, cre, underwriter, ...]   # matched against field and titles
    employers:
      - {name: Acme Capital, ats: greenhouse, slug: acmecapital}   # read directly every run
      - {name: Other Co, url: https://...}                         # not readable: browser-search list
    recruiters:
      - {name: Some Search Firm, url: https://..., focus: "debt and equity capital markets"}

Entries with an `ats` and `slug` were checked when the pack was made; anything else goes on the
browser-search list, which the Claude skill checks on request.
"""
from __future__ import annotations

import re
from functools import lru_cache
from importlib.resources import files

import yaml


@lru_cache(maxsize=1)
def all_packs() -> dict:
    out = {}
    folder = files("jobhunter") / "data" / "packs"
    if not folder.is_dir():
        return out
    for f in sorted(folder.iterdir(), key=lambda p: p.name):
        if f.name.endswith(".yaml"):
            data = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
            out[f.name[:-5]] = data
    return out


def summary(pack_id: str) -> dict:
    p = all_packs()[pack_id]
    emp, rec = p.get("employers") or [], p.get("recruiters") or []
    return {"id": pack_id, "name": p.get("name", pack_id), "employers": len(emp), "recruiters": len(rec),
            "readable": sum(1 for e in emp + rec if e.get("ats") and e.get("slug"))}


def matching(field: str = "", titles=()) -> list[str]:
    """Packs whose keywords appear in the field or any title."""
    text = " ".join([str(field or ""), *map(str, titles or ())]).lower()
    hits = []
    for pid, p in all_packs().items():
        if any(re.search(rf"\b{re.escape(k.lower())}\b", text) for k in p.get("keywords") or []):
            hits.append(pid)
    return hits


def apply(targets, pack_id: str, skip=()) -> tuple[int, int]:
    """Add a pack's employers and recruiters to companies.yaml. `skip`: company names left out
    (like your current employer). Returns (added to the daily search, added to the browse list)."""
    from .common import company_id
    p = all_packs()[pack_id]
    skip_ids = {company_id(s) for s in skip}
    direct = browse = 0
    for kind, entries in (("employer", p.get("employers") or []), ("recruiter", p.get("recruiters") or [])):
        for e in entries:
            name = e["name"]
            if company_id(name) in skip_ids:
                continue
            if e.get("ats") and e.get("slug"):
                ok, _ = targets.add_company(name, e["ats"], e["slug"], source=f"pack:{pack_id}")
                direct += ok
            elif e.get("url"):
                note = e.get("focus") or ("recruiter" if kind == "recruiter" else None)
                ok, _ = targets.add_board(e["url"], name, note=note)
                browse += ok
    return direct, browse
