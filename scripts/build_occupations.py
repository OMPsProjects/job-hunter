#!/usr/bin/env python3
"""Build jobhunter/data/occupations.json.gz from the O*NET database (text version).

    python scripts/build_occupations.py db_31_0_text.zip

Download the zip from https://www.onetcenter.org/database.html ("Text" format). The output keeps
only what job-hunter uses: each occupation's title, job zone, related occupations, in-demand
software and top knowledge areas, plus an index of ~60,000 job titles (official, alternate and
reported) pointing at their occupation. Licensed CC BY 4.0; see jobhunter/data/README.md.
"""
from __future__ import annotations

import csv
import gzip
import io
import json
import re
import sys
import zipfile
from collections import defaultdict

VERSION = "31.0"


def read(z, name):
    path = next(n for n in z.namelist() if n.endswith("/" + name))
    text = z.read(path).decode("utf-8", errors="replace")
    return list(csv.DictReader(io.StringIO(text), delimiter="\t"))


def norm(s):
    return re.sub(r"[^a-z0-9]+", " ", str(s or "").lower()).strip()


def main(zip_path, out_path="jobhunter/data/occupations.json.gz"):
    z = zipfile.ZipFile(zip_path)
    occ = {r["O*NET-SOC Code"]: {"t": r["Title"]} for r in read(z, "Occupation Data.txt")}
    for r in read(z, "Job Zones.txt"):
        if r["O*NET-SOC Code"] in occ:
            occ[r["O*NET-SOC Code"]]["z"] = int(r["Job Zone"])

    related = defaultdict(list)
    for r in read(z, "Related Occupations.txt"):
        if r["Relatedness Tier"].startswith("Primary"):
            related[r["O*NET-SOC Code"]].append((int(r["Index"]), r["Related O*NET-SOC Code"]))
    for code, rel in related.items():
        if code in occ:
            occ[code]["r"] = [c for _, c in sorted(rel)[:10] if c in occ]

    software = defaultdict(list)
    for r in read(z, "Software Skills.txt"):
        rank = (r.get("In Demand") == "Y") * 2 + (r.get("Hot Technology") == "Y")
        if rank:
            software[r["O*NET-SOC Code"]].append((-rank, r["Workplace Example"]))
    for code, items in software.items():
        if code in occ:
            occ[code]["s"] = [name for _, name in sorted(items)[:12]]

    knowledge = defaultdict(list)
    for r in read(z, "Knowledge.txt"):
        if r["Scale ID"] == "IM" and r.get("Recommend Suppress") != "Y":
            knowledge[r["O*NET-SOC Code"]].append((-float(r["Data Value"]), r["Element Name"]))
    for code, items in knowledge.items():
        if code in occ:
            occ[code]["k"] = [name for v, name in sorted(items)[:6] if -v >= 3.0]

    examples = defaultdict(list)  # titles people in the occupation reported; used as suggestions
    for r in read(z, "Sample of Reported Titles.txt"):
        examples[r["O*NET-SOC Code"]].append((r.get("Shown in My Next Move") != "Y", r["Reported Job Title"]))
    for code, items in examples.items():
        if code in occ:
            occ[code]["e"] = [t for _, t in sorted(items, key=lambda x: x[0])[:6]]

    titles: dict[str, list[str]] = {}
    sources = [(r["Title"], r["O*NET-SOC Code"]) for r in read(z, "Occupation Data.txt")]
    sources += [(r["Reported Job Title"], r["O*NET-SOC Code"]) for r in read(z, "Sample of Reported Titles.txt")]
    sources += [(r["Job Title"], r["O*NET-SOC Code"]) for r in read(z, "Job Titles.txt")]
    for title, code in sources:
        k = norm(title)
        if not k or code not in occ:
            continue
        codes = titles.setdefault(k, [])
        if code not in codes and len(codes) < 3:
            codes.append(code)
    data = {"version": VERSION, "occupations": occ, "titles": titles}
    raw = json.dumps(data, separators=(",", ":"), sort_keys=True).encode("utf-8")
    with open(out_path, "wb") as fh, gzip.GzipFile(fileobj=fh, mode="wb", mtime=0) as gz:  # reproducible bytes
        gz.write(raw)
    print(f"{out_path}: {len(occ)} occupations, {len(titles)} titles")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    main(*sys.argv[1:])
