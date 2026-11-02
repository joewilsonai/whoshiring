# Who's Hiring, 15 Years — the brief

**The Bet (Joe Wilson Builds, Bet #1):** CLAIM: Claude builds a working 15-year hiring atlas from Hacker
News's monthly "Who is hiring?" threads in one sitting. CLOCK: 48 hours from 2026-11-01 21:12 CST (first page live on the droplet 2026-11-01 21:25 CST). COST:
the API bill, kept to the cent (Algolia HN API is free; the box is Joe's existing NYC droplet; the domain
is the one purchase). VERDICT: a URL that is strictly more useful to a laid-off 48-year-old at 2 AM than a
job board.

**The shape (Karpathy's HackerTube recipe, ours):** one public pile of human signal (187 threads,
2011–2026, hundreds of thousands of posts), Claude does the sifting, Joe does three clicks (domain, box,
the yes). No logins; state in the browser.

**What the page answers:** which companies have hired every year (the durable ones), what they pay and
how that moved, how remote rose and fell, which roles appeared and which died, where the jobs are, and a
search that works. One page, fast, no feed.

**Pipeline:** `fetch.py` (Algolia → data/raw) → `parse.py` (top-level posts → jobs.jsonl: month, company,
role, location, remote/onsite/hybrid, pay range, url, text) → `build.py` (aggregates → site/data.json) →
`site/` (static, one HTML + JS, served by nginx on the droplet).

**Rules:** no scraping beyond the public API; no personal data beyond what posters published to a public
thread; link every post back to HN; the raw data zip is downloadable so anyone can point their Claude at it.
