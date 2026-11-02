#!/usr/bin/env python3
"""Pull every Hacker News "Who is hiring?" thread (2011 to now) through the Algolia HN API.

No key, no login. Threads are listed by the account `whoishiring`; each thread's full comment tree
comes from /api/v1/items/{id}. Raw JSON lands in data/raw/<thread_id>.json; the thread index in
data/threads.json. Re-running skips threads already on disk (pass --refresh to refetch the latest 3).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RAW = ROOT / "data" / "raw"
INDEX = ROOT / "data" / "threads.json"
API = "https://hn.algolia.com/api/v1"
UA = "whoshiring-bet1/0.1 (Joe Wilson Builds; contact joe@aibuildersclub.ai)"


def get(url: str, tries: int = 4) -> dict:
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.load(resp)
        except Exception as exc:  # noqa: BLE001
            wait = 2 ** attempt
            print(f"  retry {attempt + 1}/{tries} after {wait}s: {exc}", file=sys.stderr)
            time.sleep(wait)
    raise SystemExit(f"gave up on {url}")


def list_threads() -> list[dict]:
    """Every story by `whoishiring` whose title is a 'Who is hiring?' thread, oldest first."""
    hits: list[dict] = []
    page = 0
    while True:
        q = urllib.parse.urlencode({
            "tags": "story,author_whoishiring",
            "query": '"Who is hiring"',
            "hitsPerPage": 1000,
            "page": page,
        })
        data = get(f"{API}/search_by_date?{q}")
        hits.extend(data["hits"])
        if page >= data.get("nbPages", 1) - 1:
            break
        page += 1
    threads = [
        {
            "id": h["objectID"],
            "title": h["title"],
            "created_at": h["created_at"],
            "num_comments": h.get("num_comments"),
        }
        for h in hits
        if h.get("title", "").lower().startswith("ask hn: who is hiring?")
    ]
    threads.sort(key=lambda t: t["created_at"])
    return threads


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true", help="refetch the newest 3 threads too")
    args = ap.parse_args()

    RAW.mkdir(parents=True, exist_ok=True)
    threads = list_threads()
    INDEX.write_text(json.dumps(threads, indent=1))
    print(f"{len(threads)} threads, {threads[0]['created_at'][:7]} to {threads[-1]['created_at'][:7]}")

    todo = []
    for i, t in enumerate(threads):
        path = RAW / f"{t['id']}.json"
        if path.exists() and not (args.refresh and i >= len(threads) - 3):
            continue
        todo.append(t)
    print(f"fetching {len(todo)} thread trees")

    for n, t in enumerate(todo, 1):
        data = get(f"{API}/items/{t['id']}")
        (RAW / f"{t['id']}.json").write_text(json.dumps(data))
        kids = len(data.get("children") or [])
        print(f"[{n}/{len(todo)}] {t['created_at'][:7]} {t['title']} — {kids} top-level posts")
        time.sleep(0.4)  # polite; Algolia allows far more
    print("done")


if __name__ == "__main__":
    main()
