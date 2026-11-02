#!/usr/bin/env python3
"""Monthly refresh: pull the new thread, judge its posts, rebuild, ship the page.

Any failed step stops the run before anything ships, so the live page stays as it was. Shipping also
stops if the new build would shrink the page or if under 90% of the newest month got judged.

Usage: refresh.py [--no-ship] [--rebuild-only] [--limit N]
  --no-ship       everything but the rsync
  --rebuild-only  skip the fetch and the model calls; re-parse, rebuild, ship
  --limit N       most posts to judge this run (default 500, about $1.65)
Env: ANTHROPIC_API_KEY for score.py, WHOSHIRING_SSH=user@host to ship, WHOSHIRING_URL for the live page.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SITE = ROOT / "site"
SPEND = ROOT / "data" / "spend.jsonl"
LIVE = os.environ.get("WHOSHIRING_URL", "https://whoshiring.app").rstrip("/")
UA = "whoshiring-refresh/0.1 (Joe Wilson Builds; contact joe@aibuildersclub.ai)"
MIN_JUDGED = 0.9


def run(*cmd: str) -> None:
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, cwd=ROOT, check=True)


def spent() -> float:
    if not SPEND.exists():
        return 0.0
    return sum(json.loads(line).get("usd") or 0 for line in SPEND.open())


def live_data() -> dict:
    req = urllib.request.Request(f"{LIVE}/data.json", headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def live_matches_build() -> bool:
    for name in ("index.html", "data.json"):
        req = urllib.request.Request(f"{LIVE}/{name}", headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=30) as resp:
            if hashlib.sha256(resp.read()).digest() != hashlib.sha256((SITE / name).read_bytes()).digest():
                return False
    return True


def problems(new: dict, live: dict) -> list[str]:
    out = []
    for key in ("threads", "posts"):
        if new.get(key, 0) < live.get(key, 0):
            out.append(f"{key} would shrink: {live.get(key)} live, {new.get(key)} built")
    if new.get("latest_month", "") < live.get("latest_month", ""):
        out.append(f"newest month would go back: {live.get('latest_month')} live, {new.get('latest_month')} built")
    judged = new.get("judgment") or {}
    scored, total = judged.get("scored", 0), judged.get("of", 0)
    if not total or scored / total < MIN_JUDGED:
        out.append(f"only {scored} of {total} posts judged in {new.get('latest_month')}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-ship", action="store_true")
    ap.add_argument("--rebuild-only", action="store_true")
    ap.add_argument("--limit", type=int, default=500)
    args = ap.parse_args()

    target = os.environ.get("WHOSHIRING_SSH")
    if not args.no_ship and not target:
        print("STOPPED: WHOSHIRING_SSH is not set, so there is nowhere to ship", file=sys.stderr)
        return 1
    if not args.rebuild_only and not os.environ.get("ANTHROPIC_API_KEY"):
        print("STOPPED: ANTHROPIC_API_KEY is not set", file=sys.stderr)
        return 1

    python = sys.executable
    before = spent()
    try:
        if not args.rebuild_only:
            run(python, "fetch.py", "--refresh")
        run(python, "parse.py")
        if not args.rebuild_only:
            run(python, "score.py", "--limit", str(args.limit))
        run(python, "build.py")
        live = live_data()
    except (subprocess.CalledProcessError, OSError, ValueError) as exc:
        print(f"STOPPED, nothing shipped: {exc}", file=sys.stderr)
        return 1

    new = json.loads((SITE / "data.json").read_text())
    judged = new.get("judgment") or {}
    print(f"built: {new.get('threads')} threads, {new.get('posts')} posts, newest {new.get('latest_month')}, "
          f"{judged.get('scored')} of {judged.get('of')} judged, ${spent() - before:.2f} this run")

    found = problems(new, live)
    if found:
        print("STOPPED, nothing shipped: " + "; ".join(found), file=sys.stderr)
        return 1
    if args.no_ship:
        print("not shipped: --no-ship")
        return 0

    try:
        # --delay-updates swaps the files in together at the end, so a dropped transfer changes nothing.
        run("rsync", "-az", "--delay-updates", "site/", f"{target}:/var/www/whoshiring/")
        matches = live_matches_build()
    except (subprocess.CalledProcessError, OSError, ValueError) as exc:
        print(f"FAILED while shipping: {exc}", file=sys.stderr)
        return 1
    if not matches:
        print("FAILED: the live page doesn't match the build after shipping", file=sys.stderr)
        return 1
    print(f"shipped: {LIVE} now shows {new.get('posts')} posts through {new.get('latest_month')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
