# Velai — setup

Three files, about fifteen minutes, no cost.

```
velai/
├── index.html                    ← the site (rename velai-job-board.html to this)
├── scrape.py                     ← the collector
├── jobs.json                     ← written by the collector each morning
└── .github/workflows/daily.yml   ← runs the collector on a schedule
```

## 1. Put it online

1. Create a GitHub account, then a **public** repo called `velai`.
2. Upload `index.html`, `scrape.py`, and `daily.yml` (put that one inside a folder path `.github/workflows/`).
3. Repo **Settings → Pages → Source: Deploy from a branch → main / root → Save**.
4. Wait about a minute. Your site is now live at:

```
https://YOUR-USERNAME.github.io/velai/
```

That is the link. Bookmark it on your phone — "Add to Home Screen" makes it behave like an app.

## 2. Connect the feed

Your `jobs.json` will live at:

```
https://YOUR-USERNAME.github.io/velai/jobs.json
```

Open your site, click **Feed URL**, paste that in. From then on the board pulls fresh
listings every time you open it.

## 3. Tune the collector

Open `scrape.py` and edit the CONFIG block at the top. Two things matter most:

**KEYWORDS** — be generous. A listing only survives if one of these words appears in
its title. Put in role names, your stack, synonyms, and every title you'd accept.
`"backend"` alone will miss a job called "Java Developer".

**GREENHOUSE_BOARDS / LEVER_BOARDS / ASHBY_BOARDS** — this is where the good IT jobs
come from. To add a company, open its careers page and read the URL:

| Careers page URL | Add to |
|---|---|
| `boards.greenhouse.io/postman` | `GREENHOUSE_BOARDS = ["postman"]` |
| `jobs.lever.co/swiggy` | `LEVER_BOARDS = ["swiggy"]` |
| `jobs.ashbyhq.com/zepto` | `ASHBY_BOARDS = ["zepto"]` |

Build this list up over a few weeks. Thirty companies you'd actually work for beats
ten thousand listings you'll never read.

Test your changes before pushing:

```bash
pip install requests beautifulsoup4
python scrape.py
```

## 4. Optional paid sources

Both are off unless you add a key. Repo **Settings → Secrets and variables → Actions**:

- `ADZUNA_APP_ID` + `ADZUNA_APP_KEY` — free tier, wide India coverage.
  Register at developer.adzuna.com.
- `SERPAPI_KEY` — the only way to read Google Jobs. Paid beyond a small monthly
  allowance. Google closed its own Jobs API in 2021 and never replaced it.

## What to expect

**Government listings need checking.** Notification pages rarely put the last date in
the link text. When the collector can't find one, it assumes 30 days and marks the job
**confirm last date** on the card. Open the PDF and fix it. Don't trust that countdown.

**Private listings have no real deadline.** Companies don't publish one, so every ATS
job also shows 30 days — that's "roughly how long this stays open", not a cliff.

**Government sites break scrapers.** They redesign without warning and some block
datacentre IPs. If one source goes quiet, the run continues without it and logs which
one failed — check the Actions tab.

**Scraping Naukri, LinkedIn or Indeed is not in here on purpose.** Their terms forbid
it and their anti-bot systems will block you within a day. The ATS feeds give you the
same companies, direct from the employer.
