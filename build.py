#!/usr/bin/env python3
"""Aggregate data/jobs.jsonl into site/data.json, the one file the page loads.

What the page needs: posts per month; remote share per year; pay medians per year (posts that state
pay, USD only); the durable companies (years active, months, roles, latest post); role families over
time; top locations per year; the latest month's posts in full; a compact search index (company,
role, location, month, url) for every post with a company.
"""
from __future__ import annotations

import json
import re
import statistics
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
JOBS = ROOT / "data" / "jobs.jsonl"
OUT = ROOT / "site" / "data.json"

FAMILIES = [
    ("AI / ML", re.compile(r"\b(ai|ml|machine learning|llm|deep learning|data scien|nlp|computer vision)\b", re.I)),
    ("Frontend", re.compile(r"\b(frontend|front-end|react|javascript|typescript|ui engineer|web developer)\b", re.I)),
    ("Backend", re.compile(r"\b(backend|back-end|api|server|distributed|platform engineer)\b", re.I)),
    ("Full stack", re.compile(r"\bfull[- ]?stack\b", re.I)),
    ("Mobile", re.compile(r"\b(ios|android|mobile)\b", re.I)),
    ("Infra / DevOps / SRE", re.compile(r"\b(devops|sre|infrastructure|site reliability|kubernetes|cloud engineer)\b", re.I)),
    ("Data engineering", re.compile(r"\b(data engineer|analytics engineer|etl|pipeline)\b", re.I)),
    ("Security", re.compile(r"\b(security|appsec|infosec)\b", re.I)),
    ("Design", re.compile(r"\b(designer|ux|product design)\b", re.I)),
    ("Product / PM", re.compile(r"\b(product manager|pm\b|head of product)\b", re.I)),
    ("Leadership", re.compile(r"\b(cto|vp|director|head of|engineering manager|lead)\b", re.I)),
    ("Embedded / Hardware", re.compile(r"\b(embedded|firmware|hardware|fpga|robotics)\b", re.I)),
]


def norm_company(name: str) -> str:
    n = re.sub(r"\s*\((yc|y combinator)[^)]*\)", "", name, flags=re.I)
    n = re.sub(r"\b(inc|llc|ltd|corp|co)\.?$", "", n.strip(), flags=re.I).strip(" ,.")
    return n


def main() -> None:
    rows = [json.loads(l) for l in JOBS.open()]
    months = sorted({r["month"] for r in rows})
    per_month = Counter(r["month"] for r in rows)

    by_year = defaultdict(list)
    for r in rows:
        by_year[r["month"][:4]].append(r)
    years = sorted(by_year)

    remote_share = {}
    pay_median = {}
    pay_n = {}
    for y in years:
        rs = by_year[y]
        tagged = [r for r in rs if r["remote"]]
        remote_share[y] = round(100 * sum(1 for r in tagged if r["remote"] in ("remote", "hybrid")) / len(tagged)) if tagged else None
        usd = [r for r in rs if r["pay_lo"] and r["cur"] == "$" and 30000 <= r["pay_lo"] <= 600000]
        mids = [((r["pay_lo"] + r["pay_hi"]) / 2 if r["pay_hi"] else r["pay_lo"]) for r in usd]
        pay_median[y] = round(statistics.median(mids)) if mids else None
        pay_n[y] = len(mids)

    # Durable companies
    comp = defaultdict(lambda: {"months": set(), "roles": Counter(), "locations": Counter(), "remote": Counter(), "latest": None, "posts": 0})
    for r in rows:
        if not r["company"] or r.get("conf") != "head":
            continue  # durable list is built only from structured first lines, never from guesses
        key = norm_company(r["company"])
        if len(key) < 2:
            continue
        c = comp[key]
        c["months"].add(r["month"])
        c["posts"] += 1
        if r["role"]:
            c["roles"][r["role"][:60]] += 1
        if r["location"]:
            c["locations"][r["location"][:40]] += 1
        if r["remote"]:
            c["remote"][r["remote"]] += 1
        if c["latest"] is None or r["month"] > c["latest"]["month"]:
            c["latest"] = {"month": r["month"], "head": r["head"][:160], "url": r["url"]}
    companies = []
    for name, c in comp.items():
        ys = sorted({m[:4] for m in c["months"]})
        companies.append({
            "name": name,
            "years": len(ys),
            "first": min(c["months"]),
            "last": max(c["months"]),
            "months": len(c["months"]),
            "posts": c["posts"],
            "roles": [k for k, _ in c["roles"].most_common(3)],
            "locations": [k for k, _ in c["locations"].most_common(2)],
            "remote": c["remote"].most_common(1)[0][0] if c["remote"] else None,
            "latest": c["latest"],
        })
    companies.sort(key=lambda c: (-c["years"], -c["months"], c["name"].lower()))
    durable = [c for c in companies if c["years"] >= 3][:600]

    # Role families by year (share of posts with a role)
    fam = {y: Counter() for y in years}
    fam_n = {y: 0 for y in years}
    for r in rows:
        if not r["role"]:
            continue
        y = r["month"][:4]
        fam_n[y] += 1
        for name, rx in FAMILIES:
            if rx.search(r["role"]):
                fam[y][name] += 1
    families = {name: [round(100 * fam[y][name] / fam_n[y], 1) if fam_n[y] else None for y in years] for name, _ in FAMILIES}

    # Top locations per year
    loc_year = {y: Counter() for y in years}
    for r in rows:
        if r["location"]:
            loc_year[r["month"][:4]][re.sub(r",.*", "", r["location"]).strip()[:30]] += 1
    top_locations = {y: loc_year[y].most_common(8) for y in years}

    latest_month = months[-1]
    latest = [
        {"company": r["company"], "role": r["role"], "location": r["location"], "remote": r["remote"],
         "pay_lo": r["pay_lo"], "pay_hi": r["pay_hi"], "cur": r["cur"], "head": r["head"][:200], "url": r["url"]}
        for r in rows if r["month"] == latest_month
    ]
    index = [
        [r["month"], (r["company"] or "")[:60], (r["role"] or "")[:80], (r["location"] or "")[:40], r["remote"] or "", r["id"]]
        for r in rows if r["company"]
    ]

    out = {
        "built": __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M"),
        "threads": len(months),
        "posts": len(rows),
        "months": months,
        "per_month": [per_month[m] for m in months],
        "years": years,
        "remote_share": [remote_share[y] for y in years],
        "pay_median": [pay_median[y] for y in years],
        "pay_n": [pay_n[y] for y in years],
        "families": families,
        "top_locations": top_locations,
        "durable": durable,
        "latest_month": latest_month,
        "latest": latest,
        "index": index,
    }
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(out, separators=(",", ":")))
    print(f"{len(rows)} posts, {len(months)} months, {len(durable)} durable companies, {len(index)} indexed → {OUT} ({OUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
