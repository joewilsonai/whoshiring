# Who's Hiring, 15 Years

<p align="center"><img src="docs/hero.png" width="760" alt="The page: fifteen years of Hacker News hiring threads on one screen"></p>

<p align="center">
<b>184 threads · 93,193 job posts · April 2011 to October 2026 · one static page · $0.85 of model calls</b><br>
<a href="https://whoshiring.app">Open the page</a> · built in one sitting on November 1, 2026 as <b>Bet №1</b> of <a href="https://aibuildersclub.ai">Joe Wilson Builds</a>
</p>

| | |
|---|---|
| **CLAIM** | In one sitting, Claude turns fifteen years of HN hiring threads into a page a laid-off 45-year-old can actually use. |
| **CLOCK** | 9:12 PM start → page live 9:25 → every October post judged by 10:15. |
| **COST** | $0.85 in model calls, logged per call. Plus a $10.19 domain. |
| **VERDICT** | Confirmed on the six goals below. Whether it beats a job board at 2 AM is yours. |

Every monthly **"Ask HN: Who is hiring?"** thread since April 2011, sifted into one page: which companies
keep hiring, what they say they pay, how remote rose and slipped, which roles rose and fell, and this
month's posts read one by one for a specific reader: mid-career, laid off, deciding at 2 AM whether a post
is worth an hour.

Live: **https://whoshiring.app**. No feed, no login, no recommendations. Every number
links back to its Hacker News post, so when something looks wrong the source is one click away.

This is **Bet №1** on [Joe Wilson Builds](https://aibuildersclub.ai). The claim: in one sitting, Claude
turns fifteen years of HN hiring threads into a page a laid-off 45-year-old can actually use. Six goals,
miss one and it's busted:

1. Every thread since 2011, every post, no sampling.
2. The trends: posts, remote, pay, roles.
3. The companies that hire every single year.
4. Every post this month, read and judged for that reader.
5. Every number one click from its source.
6. Under $5 in AI, finished before bed.

Started 9:12 PM on November 1, 2026. Page live at 9:25. The month judged by 10:15. Model spend for the
whole thing: **$0.85**, logged per call in `data/spend.jsonl`. Verdict: confirmed on the goals; whether it
beats a job board at 2 AM is the viewer's call.

## What the page shows (184 threads, 93,193 posts, Apr 2011 to Oct 2026)

<img src="docs/months.png" width="760" alt="Posts per month, 2011 to 2026: a climb to the 2018 peak, a 2021 echo, then a cliff">

<img src="docs/roles.png" width="760" alt="Role families over time: AI/ML rises from 5% to 20% while frontend falls">

<img src="docs/durable.png" width="760" alt="The durable companies: Datadog, Apple, Sourcegraph, Scribd, MongoDB, DuckDuckGo">

- **Posts per month.** The peak was May 2018 (971). 2021 came close. 2026 is the weakest year since 2012;
  the last four months are the lowest run since 2013.
- **Remote by year.** From a quarter of posts in 2016 to 92% in 2022, slipping every year since to 76%.
- **Stated pay by year.** The posted median midpoint kept climbing while post counts fell: $150k in 2023,
  $175k in 2026. Fewer jobs, more senior, and they pay for it.
- **Roles over time.** AI/ML went from about 5% of role mentions in 2022 to nearly 20% in 2025 while
  frontend fell from 15% to under 5% and mobile from 10% to 2%.
- **The durable ones.** 600 companies that posted in three or more different years (Datadog 14 years,
  Apple, Sourcegraph, Scribd, MongoDB, DuckDuckGo at the top), each with its latest post.
<img src="docs/post1.png" width="760" alt="A judged post: label, 45+ ok, pay, and a one-line note for the reader">

- **This month, judged.** Every post in the newest thread labeled by a model: real role, junior only,
  needs PhD, contract, equity only, vague, recruiter, not a job; plus whether a 45+ candidate is plausibly
  wanted, whether coding is required, whether a degree is stated, seniority, pay stated, and a one-line
  note. The page hides the noise by default and offers toggles for "45+ welcome", "no coding required",
  "pay stated", "no degree required". October 2026: 206 real roles, 204 of them open to experience, 15
  needing no code.
- **Search all fifteen years** (loaded only when you type) and **where the jobs were**, by year.

Caveat on the whole thing: these are companies that chose to post on HN, so it skews to startups and
remote-friendly engineering. It is a thermometer for that world, not for all of tech.

## How it's built

```
fetch.py   Algolia HN API → data/raw/<thread>.json (184 threads; --refresh refetches the newest 3)
parse.py   top-level posts → data/jobs.jsonl  (Company | Role | Location | REMOTE | pay convention;
           a classifier for location/role/noise; a freeform fallback flagged conf=guess and kept out of
           the durable list)
score.py   the judgment layer: claude-sonnet-5-5 reads each post in the newest month, returns a label,
           flags and a note; resumable per post; spend logged to data/spend.jsonl
build.py   aggregates → site/data.json (413 KB) + site/index.json (the search index, 7 MB, lazy)
site/      one static page, no framework; nginx config in deploy/nginx.conf
```

```bash
python3 fetch.py && python3 parse.py
ANTHROPIC_API_KEY=... python3 score.py          # newest month; ~$0.003 a post
python3 build.py
rsync -az site/ user@host:/var/www/whoshiring/
```

Monthly: `WHOSHIRING_SSH=user@host ANTHROPIC_API_KEY=... python3 refresh.py` pulls the new thread, judges its
posts, rebuilds and ships. It stops before shipping if the page would shrink or under 90% of the newest
month got judged, so a bad run leaves the live page alone.

Parsing is heuristic on purpose. The first line of a post is read by the convention HN posters follow;
anything the parser only guessed at is flagged and excluded from the company list. Labels on this month's
posts are a model's opinion and the page says so. The data is a public API; no scraping beyond it, no
personal data beyond what posters published to a public thread.

## Credits

Data: the Hacker News API via Algolia, threads posted by [whoishiring](https://news.ycombinator.com/user?id=whoishiring).
The shape of the project owes a debt to Andrej Karpathy's HackerTube: one public pile of human signal,
a model does the sifting, a person does three clicks. Built by Joe Wilson with Claude, November 1, 2026.
