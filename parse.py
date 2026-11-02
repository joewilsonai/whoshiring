#!/usr/bin/env python3
"""Turn the raw thread trees into one line per job post: data/jobs.jsonl.

A "job post" is a top-level comment on a "Who is hiring?" thread. Since about 2013 HN posters follow a
convention on the first line: `Company | Role | Location | REMOTE or ONSITE | $pay`. Older posts are
freeform. This parser reads the first line by that convention when it is there and falls back to
patterns in the whole text when it is not. It is heuristic on purpose: good enough for the atlas, and
every record links back to the HN comment so anyone can check it.
"""
from __future__ import annotations

import glob
import html
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "jobs.jsonl"
INDEX = ROOT / "data" / "threads.json"

TAG = re.compile(r"<[^>]+>")
URL = re.compile(r"https?://\S+")
PAREN_URL = re.compile(r"\((?:https?://)?[\w.-]+\.[a-z]{2,}[^)]*\)", re.I)
ROLE_WORDS = re.compile(
    r"\b(engineers?|developers?|devs?|designers?|managers?|scientists?|researchers?|founders?|interns?|"
    r"leads?|head of|directors?|devops|sre|analysts?|product|architects?|cto|vp|recruiters?|marketers?|"
    r"writers?|support|ops|operations|data|ml|ai|security|qa|mobile|ios|android|frontend|front-end|"
    r"backend|back-end|full[- ]?stack|swe|sde|programmers?|positions?|roles?|openings?)\b", re.I)
COUNTRIES = {
    "usa", "us", "united states", "uk", "united kingdom", "england", "canada", "germany", "france", "netherlands",
    "australia", "india", "israel", "spain", "sweden", "switzerland", "poland", "portugal", "ireland", "brazil",
    "japan", "europe", "eu", "austria", "belgium", "denmark", "norway", "finland", "italy", "mexico", "argentina",
    "singapore", "china", "scotland", "wales", "czech republic", "estonia", "latvia", "lithuania", "hungary",
    "romania", "ukraine", "russia", "turkey", "south africa", "new zealand", "worldwide", "global", "anywhere",
    "north america", "latam", "emea", "apac", "nyc", "sf", "la", "dc", "bay area",
}
REMOTE = re.compile(r"\bremote\b", re.I)
ONSITE = re.compile(r"\bon-?site\b", re.I)
HYBRID = re.compile(r"\bhybrid\b", re.I)
VISA = re.compile(r"\bvisa\b", re.I)
INTERN = re.compile(r"\bintern(ship)?s?\b", re.I)
CONTRACT = re.compile(r"\b(contract|contractor|part[- ]time|freelance)\b", re.I)
FULLTIME = re.compile(r"\b(full[- ]?time|fulltime)\b", re.I)
# $120k, $120K, $120,000, $120k-$160k, 120-160k, £80k, €90k, $100-150k
PAY = re.compile(
    r"(?P<cur>[$£€])\s?(?P<lo>\d{2,3})(?:,(?P<lo3>\d{3}))?\s?(?P<lok>k)?"
    r"(?:\s?(?:-|–|—|to)\s?(?P<cur2>[$£€])?\s?(?P<hi>\d{2,3})(?:,(?P<hi3>\d{3}))?\s?(?P<hik>k)?)?",
    re.I)
CITY_HINTS = [
    "San Francisco", "SF", "Bay Area", "Palo Alto", "Mountain View", "Menlo Park", "Oakland", "San Jose",
    "New York", "NYC", "Brooklyn", "Seattle", "Austin", "Boston", "Cambridge", "Chicago", "Los Angeles",
    "LA", "San Diego", "Denver", "Boulder", "Portland", "Atlanta", "Washington", "DC", "Philadelphia",
    "Pittsburgh", "Toronto", "Vancouver", "Montreal", "London", "Berlin", "Amsterdam", "Paris", "Dublin",
    "Zurich", "Munich", "Stockholm", "Copenhagen", "Lisbon", "Barcelona", "Madrid", "Tel Aviv", "Bangalore",
    "Bengaluru", "Singapore", "Sydney", "Melbourne", "Tokyo", "Hong Kong", "Minneapolis", "Salt Lake City",
    "Phoenix", "Dallas", "Houston", "Miami", "Raleigh", "Durham", "Nashville", "Detroit", "St. Louis",
    "Kansas City", "Madison", "Ann Arbor", "Columbus", "Cincinnati", "Cleveland", "Charlotte", "Tampa",
    "Orlando", "Las Vegas", "Sacramento", "Santa Monica", "Pasadena", "Irvine", "Remote",
]
STATE = re.compile(r"\b([A-Z][a-zA-Z.]+(?: [A-Z][a-zA-Z.]+)?), ([A-Z]{2})\b")


def clean(raw_html: str) -> str:
    text = raw_html.replace("<p>", "\n").replace("<br>", "\n").replace("<br/>", "\n")
    text = TAG.sub(" ", text)
    text = html.unescape(text)
    return re.sub(r"[ \t]+", " ", text).strip()


def first_line(text: str) -> str:
    line = text.split("\n", 1)[0].strip()
    return line[:220]


NOISE = re.compile(
    r"^(full[- ]?time|part[- ]?time|fulltime|onsite|on-site|remote|hybrid|visa|no visa|visa sponsorship|"
    r"contract|intern(ship)?s?|location|salary|equity|relocation( available)?|us only|usa|us|uk|eu|"
    r"worldwide|anywhere|global|h1b|h-1b|\$[\d,k$ -]+|\d{2,3}k?[-–]\d{2,3}k?|yc [sw]\d\d|w\d\d|s\d\d)$", re.I)


STOP = {"we", "we're", "we are", "our", "the", "location", "hiring", "i", "i'm", "my", "a", "an", "this",
        "company", "job", "jobs", "position", "positions", "role", "roles", "title", "about", "who", "what",
        "senior", "junior", "software", "engineer", "engineers", "developer", "developers", "remote", "onsite",
        "full time", "full-time", "fulltime", "part time", "contract", "intern", "interns", "visa", "full", "part",
        "hi", "hey", "hello", "yc", "undisclosed", "undisclosed company name", "stealth", "stealth startup",
        "multiple positions", "various", "n/a", "tbd", "see below", "details", "note", "edit", "update"}


def classify(seg: str) -> str:
    """One head segment is a location, a role, noise, or (by elimination) the company."""
    s = seg.strip()
    if NOISE.match(s):
        return "noise"
    if STATE.search(s) or re.fullmatch(r"(remote|onsite|hybrid)[\w ,/()-]*", s, re.I):
        return "location"
    low = s.lower().strip(" .")
    if re.fullmatch(r"[A-Z]{2}", s) or low in COUNTRIES:
        return "location"
    if low in STOP:
        return "noise"
    if len(s) <= 70:
        for h in CITY_HINTS:
            hl = h.lower()
            if hl in ("sf", "la", "dc"):
                if re.search(rf"\b{hl.upper()}\b", s):
                    return "location"
            elif re.search(rf"\b{re.escape(hl)}\b", low):
                return "location"
    if ROLE_WORDS.search(s) and len(s) < 100:
        return "role"
    if 1 < len(s) <= 60:
        return "company"
    return "noise"


def money(m: re.Match) -> tuple[int | None, int | None, str]:
    def val(n, n3, k):
        if n is None:
            return None
        if n3:
            return int(n + n3)
        v = int(n)
        return v * 1000 if (k or v < 1000) else v
    lo = val(m.group("lo"), m.group("lo3"), m.group("lok"))
    hi = val(m.group("hi"), m.group("hi3"), m.group("hik") or m.group("lok"))
    if lo and lo < 20000:  # "$5k signing bonus" style noise
        return None, None, m.group("cur")
    if hi and lo and hi < lo:
        hi = None
    return lo, hi, m.group("cur")


def parse_post(thread: dict, c: dict) -> dict | None:
    if not c.get("text") or c.get("author") is None:
        return None
    text = clean(c["text"])
    if len(text) < 40:
        return None
    head = first_line(text)
    if "|" in head:
        segs = re.split(r"\s*\|\s*", head)
    else:
        segs = re.split(r"\s+[-–—]+\s+|\s*[—–]\s*", head)
    segs = [URL.sub("", PAREN_URL.sub("", s)).strip(" ,.;:|()-–—") for s in segs]
    segs = [s for s in segs if s]
    company = None
    role = None
    location = None
    conf = "head"  # company came from the structured first line; "guess" = freeform fallback
    if len(segs) >= 2:
        for s in segs:
            kind = classify(s)
            if kind == "location" and location is None:
                location = s[:80]
            elif kind == "role" and role is None:
                role = s[:120]
            elif kind == "company" and company is None:
                company = s
    if company is None:
        # Freeform: take the leading capitalized run; if that run is a place, try the run after it.
        conf = "guess"
        for m in re.finditer(r"([A-Z][\w.&'+-]*(?:\s[A-Z0-9][\w.&'+-]*){0,4})", head):
            cand = m.group(1).strip()
            if classify(cand) == "company" and cand.lower() not in STOP:
                company = cand
                break
    if company:
        company = re.sub(r"\s*\([^)]*$", "", company).strip(" ,.;:|()-")  # unbalanced "(YC W12"
        if company.lower() in STOP or classify(company) != "company":
            company = None
    if location is None:
        m = STATE.search(head) or STATE.search(text[:600])
        if m:
            location = f"{m.group(1)}, {m.group(2)}"
        else:
            for h in CITY_HINTS:
                if h in ("SF", "LA", "DC", "Remote"):
                    continue
                if re.search(rf"\b{re.escape(h)}\b", head):
                    location = h
                    break
    scope = head + " " + text[:400]
    remote = "remote" if REMOTE.search(scope) else None
    if HYBRID.search(scope):
        remote = "hybrid"
    elif remote is None and ONSITE.search(scope):
        remote = "onsite"
    pay_lo = pay_hi = None
    cur = None
    for m in PAY.finditer(text):
        lo, hi, cur = money(m)
        if lo:
            pay_lo, pay_hi = lo, hi
            break
    if company and (len(company) > 60 or len(company) < 2):
        company = None
    return {
        "id": c["id"],
        "month": thread["created_at"][:7],
        "author": c.get("author"),
        "company": company,
        "conf": conf if company else None,
        "role": role,
        "location": location,
        "remote": remote,
        "pay_lo": pay_lo,
        "pay_hi": pay_hi,
        "cur": cur,
        "visa": bool(VISA.search(text)),
        "intern": bool(INTERN.search(head)),
        "contract": bool(CONTRACT.search(scope)),
        "fulltime": bool(FULLTIME.search(scope)),
        "head": head,
        "url": f"https://news.ycombinator.com/item?id={c['id']}",
        "len": len(text),
    }


def main() -> None:
    threads = {t["id"]: t for t in json.loads(INDEX.read_text())}
    n = 0
    with OUT.open("w") as out:
        for path in sorted(glob.glob(str(RAW / "*.json"))):
            data = json.loads(Path(path).read_text())
            thread = threads.get(str(data["id"])) or {"created_at": data["created_at"]}
            for c in data.get("children") or []:
                rec = parse_post(thread, c)
                if rec:
                    out.write(json.dumps(rec) + "\n")
                    n += 1
    print(f"{n} job posts → {OUT}")


if __name__ == "__main__":
    main()
