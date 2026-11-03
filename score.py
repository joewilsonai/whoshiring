#!/usr/bin/env python3
"""The judgment layer: Claude reads each job post and labels it for a mid-career reader.

Karpathy's trick was not the pile, it was the sifting. Here, for one month (default: the newest),
every top-level post is read by Claude once and gets a label, a few flags, and one plain line.
Results land in data/scores/<month>.jsonl, one JSON per post id; re-running skips ids already
scored, so a crash or a cap costs nothing. Spend is logged per call so the Bet's COST is exact.

Usage: score.py [--month 2026-10] [--workers 6] [--limit N] [--model claude-sonnet-5-5]
Needs ANTHROPIC_API_KEY in the environment.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RAW = ROOT / "data" / "raw"
JOBS = ROOT / "data" / "jobs.jsonl"
SCORES = ROOT / "data" / "scores"
SPEND = ROOT / "data" / "spend.jsonl"
API = "https://api.anthropic.com/v1/messages"
VERSION = "2023-06-01"
# $ per million tokens, claude-sonnet-5-5 (REFERENCES.md, checked 2026-11-01)
PRICE = {"claude-sonnet-5-5": (2.0, 10.0), "claude-haiku-5-5": (0.10, 0.50), "claude-opus-5-5": (4.0, 20.0)}

LABELS = ["real_role", "junior_only", "needs_phd", "contract_or_freelance", "equity_only", "vague",
          "recruiter_or_agency", "not_a_job"]

SYSTEM = """You read one Hacker News "Who is hiring?" post and judge it for a specific reader: a mid-career
person, 45 or older, twenty-plus years in tech, recently laid off, reading at 2 AM, deciding whether this
post is worth an hour. Be blunt and specific. Answer only with one JSON object, no prose, with exactly these keys:

label: one of real_role (a real, specific job a qualified adult could apply to), junior_only (new-grad or
  explicitly junior only), needs_phd (research role that requires a PhD or published papers), contract_or_freelance,
  equity_only (no cash salary, or "equity-heavy" with no number), vague ("we're hiring, check our site" with no
  concrete role), recruiter_or_agency (third-party recruiter or staffing agency), not_a_job (a request for work,
  a product plug, or off topic).
mid_career_ok: true if a strong 45+ candidate with deep experience is plausibly wanted here; false if the post
  signals otherwise (new-grad, "young and hungry", "recent graduate", intern, 0-2 years).
coding_required: true if the role needs you to write code day to day; false for sales, support, marketing,
  product, ops, design, recruiting, customer success, finance, writing, management-without-coding.
degree_required: true if a specific degree (BS/MS/PhD in CS or similar) is stated as required.
seniority: one of junior, mid, senior, lead, any.
pay_stated: true if a concrete salary number or range appears anywhere in the post.
note: one sentence, under 140 characters, telling the reader what this is and the one thing that decides
  whether it is for them. No fluff, no "great opportunity"."""


def call(model: str, text: str, key: str) -> tuple[dict, dict]:
    body = {
        "model": model,
        "max_tokens": 900,
        "thinking": {"type": "between_tools"},
        "system": SYSTEM,
        "messages": [{"role": "user", "content": text[:6000]}],
    }
    req = urllib.request.Request(API, data=json.dumps(body).encode(), headers={
        "x-api-key": key, "anthropic-version": VERSION, "content-type": "application/json"})
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=90) as resp:
                data = json.load(resp)
            break
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 529) and attempt < 4:
                time.sleep(2 ** attempt + 1)
                continue
            raise RuntimeError(f"HTTP {e.code}: {e.read()[:300]!r}")
    if data.get("stop_reason") == "refusal":
        raise RuntimeError("refusal")
    out = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
    rec = parse_json(out)
    if rec is None or rec.get("label") not in LABELS:
        raise RuntimeError(f"bad JSON/label (stop={data.get('stop_reason')}): {out[:200]!r}")
    return rec, data.get("usage", {})


def parse_json(out: str) -> dict | None:
    """The model sometimes ends with `,"}` or stops mid-string; repair what can be repaired."""
    s = out.strip()
    i = s.find("{")
    if i < 0:
        return None
    s = s[i:]
    j = s.rfind("}")
    bounded = s[: j + 1] if j > 0 else s  # drops a trailing ``` fence or prose
    for cand in (bounded, s, re.sub(r',\s*"?\s*}\s*$', "}", bounded), s.rstrip() + '"}', s.rstrip() + "}"):
        try:
            rec = json.loads(cand)
            if isinstance(rec, dict):
                return rec
        except json.JSONDecodeError:
            continue
    return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--month")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--model", default="claude-sonnet-5-5")
    args = ap.parse_args()
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        sys.exit("ANTHROPIC_API_KEY not set")

    jobs = [json.loads(l) for l in JOBS.open()]
    month = args.month or max(j["month"] for j in jobs)
    todo = [j for j in jobs if j["month"] == month]
    # full text from the raw tree (jobs.jsonl keeps only the first line)
    texts = {}
    for path in RAW.glob("*.json"):
        data = json.loads(path.read_text())
        if data["created_at"][:7] != month:
            continue
        from parse import clean
        for c in data.get("children") or []:
            if c.get("text"):
                texts[c["id"]] = clean(c["text"])
    SCORES.mkdir(exist_ok=True)
    out_path = SCORES / f"{month}.jsonl"
    done = set()
    if out_path.exists():
        done = {json.loads(l)["id"] for l in out_path.open()}
    todo = [j for j in todo if j["id"] not in done and j["id"] in texts]
    if args.limit:
        todo = todo[:args.limit]
    print(f"{month}: {len(done)} already scored, {len(todo)} to go, model {args.model}")
    lock = threading.Lock()
    pin, pout = PRICE[args.model]
    spent = 0.0
    n_ok = n_err = 0

    def work(j):
        try:
            rec, usage = call(args.model, texts[j["id"]], key)
        except RuntimeError:
            rec, usage = call(args.model, texts[j["id"]], key)  # one retry; the output is nondeterministic
        return j, rec, usage

    with ThreadPoolExecutor(max_workers=args.workers) as ex, out_path.open("a") as out, SPEND.open("a") as sp:
        futs = [ex.submit(work, j) for j in todo]
        for f in as_completed(futs):
            try:
                j, rec, usage = f.result()
            except Exception as exc:  # noqa: BLE001
                n_err += 1
                print(f"  err: {exc}", file=sys.stderr)
                continue
            cost = (usage.get("input_tokens", 0) * pin + usage.get("output_tokens", 0) * pout) / 1e6
            with lock:
                spent += cost
                n_ok += 1
                rec = {"id": j["id"], "month": month, **{k: rec.get(k) for k in
                       ("label", "mid_career_ok", "coding_required", "degree_required", "seniority", "pay_stated", "note")}}
                out.write(json.dumps(rec) + "\n")
                out.flush()
                sp.write(json.dumps({"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "month": month, "id": j["id"],
                                     "model": args.model, "in": usage.get("input_tokens"), "out": usage.get("output_tokens"),
                                     "usd": round(cost, 6)}) + "\n")
                if n_ok % 25 == 0:
                    print(f"  {n_ok}/{len(todo)} scored, ${spent:.4f} so far")
    print(f"done: {n_ok} scored, {n_err} errors, ${spent:.4f} this run → {out_path}")


if __name__ == "__main__":
    main()
