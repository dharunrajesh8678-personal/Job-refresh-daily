#!/usr/bin/env python3
"""
Velai collector — builds jobs.json for the Velai job board.

Run it locally:      python scrape.py
Run it on schedule:  GitHub Actions does it daily (see .github/workflows/daily.yml)

Everything you need to change is in the CONFIG block below.
Nothing here needs an API key unless you switch on the optional sources.
"""

import json
import os
import re
import sys
import time
from datetime import date, timedelta

import requests
from bs4 import BeautifulSoup

# ============================================================
# CONFIG — edit this part, ignore the rest
# ============================================================

# Words that decide whether a private-sector job is kept.
# Tuned for a mixed search at 1-3 years experience: IT and non-IT, junior level.
# Government notifications come through separately and ignore this list.
KEYWORDS = [
    # --- IT / software ---
    "software engineer", "software developer", "developer", "engineer",
    "java", "python", "javascript", "react", "angular", "node", "spring",
    ".net", "php", "sql", "backend", "frontend", "front end", "full stack",
    "qa", "test engineer", "automation", "selenium", "manual testing",
    "devops", "cloud", "aws", "azure", "linux",
    "data analyst", "data engineer", "power bi", "excel",
    "support engineer", "technical support", "application support",
    "associate engineer", "system engineer", "network engineer",

    # --- private, non-IT ---
    "sales", "business development", "inside sales", "telecaller",
    "customer support", "customer service", "voice process", "bpo",
    "operations", "back office", "data entry", "coordinator",
    "accounts", "accountant", "finance", "audit", "tally",
    "hr ", "human resources", "recruiter", "talent acquisition",
    "marketing", "digital marketing", "seo", "content",
    "logistics", "supply chain", "procurement", "store keeper",
    "production", "quality", "maintenance", "supervisor",
    "relationship manager", "branch", "field officer", "collection",

    # --- titles that show up on both sides ---
    "assistant", "junior assistant", "clerk", "typist", "technician",
    "trainee", "apprentice", "executive", "officer", "analyst",
]

# Cities you'd actually take. "remote" and "india" are useful catch-alls.
LOCATIONS = ["chennai", "coimbatore", "madurai", "trichy", "tiruchirappalli",
             "salem", "erode", "hosur", "bangalore", "bengaluru", "hyderabad",
             "tamil nadu", "india"]
# Note: bare "remote" is deliberately absent. It matched "Remote, Denmark".
# "Remote, India" still gets through on the "india" token.

# Companies whose careers pages run on a public ATS. This is where the
# good IT listings come from — straight from the employer, no middleman.
#
# VERIFY EACH SLUG BEFORE TRUSTING IT. Open the company's careers page and
# read the URL: boards.greenhouse.io/SLUG, jobs.lever.co/SLUG,
# jobs.ashbyhq.com/SLUG. A wrong slug fails silently and logs a skip.
# These are starting guesses, not confirmed working boards.
GREENHOUSE_BOARDS = ["postman", "razorpay", "cred", "gojek"]
LEVER_BOARDS      = ["swiggy", "meesho"]
ASHBY_BOARDS      = ["zepto"]

# Government notification pages. These are plain HTML and scrape cleanly.
GOVT_SOURCES = [
    ("TNPSC",                     "tn",      "https://tnpsc.gov.in/"),
    ("TNUSRB",                    "tn",      "https://tnusrb.tn.gov.in/"),
    ("TN Medical Services Board", "tn",      "https://mrb.tn.gov.in/"),
    ("Teachers Recruitment Board","tn",      "https://trb.tn.gov.in/"),
    ("TANGEDCO",                  "tn",      "https://tangedco.gov.in/"),
    ("TN Velaivaaippu",           "tn",      "https://tnvelaivaaippu.gov.in/"),
    ("Staff Selection Commission","central", "https://ssc.gov.in/"),
    ("UPSC",                      "central", "https://upsc.gov.in/"),
    ("IBPS",                      "central", "https://ibps.in/"),
    ("India Post GDS",            "central", "https://indiapostgdsonline.gov.in/"),
]

# Optional. Leave blank and the source is skipped.
# Adzuna:  free developer tier, covers India broadly.  https://developer.adzuna.com
ADZUNA_APP_ID  = os.environ.get("ADZUNA_APP_ID", "")
ADZUNA_APP_KEY = os.environ.get("ADZUNA_APP_KEY", "")
# SerpApi: paid, this is the only way to read Google Jobs.  https://serpapi.com
SERPAPI_KEY    = os.environ.get("SERPAPI_KEY", "")

OUTPUT = "jobs.json"
DEFAULT_WINDOW_DAYS = 30      # assumed apply window when a source gives no closing date

# ============================================================
# Below here you shouldn't need to touch anything
# ============================================================

UA = {"User-Agent": "Mozilla/5.0 (compatible; VelaiJobBoard/1.0)"}
TODAY = date.today()

QUAL_HINTS = [
    (7, ["post graduate", "postgraduate", "m.e", "m.tech", "mba", "m.sc", "masters"]),
    (6, ["degree", "graduate", "bachelor", "b.e", "b.tech", "b.sc", "b.com", "any degree"]),
    (5, ["diploma"]),
    (4, ["iti", "trade certificate"]),
    (3, ["12th", "higher secondary", "hsc", "+2"]),
    (2, ["10th", "sslc", "matriculation"]),
]


def log(msg):
    print(f"  {msg}", file=sys.stderr)


def get(url, **kw):
    """One fetch, politely, and never crash the whole run over a dead site."""
    try:
        r = requests.get(url, headers=UA, timeout=25, **kw)
        r.raise_for_status()
        return r
    except Exception as e:
        log(f"skipped {url} — {e}")
        return None


def wanted(text):
    """Does this listing match anything you said you're looking for?"""
    t = text.lower()
    return any(k in t for k in KEYWORDS)


# Titles above your level. At 1-3 years these are noise.
TOO_SENIOR = [
    "senior", "sr.", "staff ", "principal", "lead ", " lead", "director",
    "head of", "vp ", "vice president", "chief", "architect", "manager",
    "iii", " iv", "expert", "specialist ii",
]


def right_level(title):
    t = title.lower()
    return not any(s in t for s in TOO_SENIOR)


def in_range(text):
    """Strict. A listing with no location, or a location we don't recognise,
    is rejected — that's what let Nordics and Italy through last time."""
    t = (text or "").lower().strip()
    if not t:
        return False
    return any(l in t for l in LOCATIONS)


# Words that mean the role is not a technical one, even at a tech company.
NON_TECH = [
    "account executive", "sales", "business development", "marketing",
    "recruit", "talent", "people ", "human resources", "hr ",
    "finance", "accounting", "legal", "customer success", "support specialist",
    "operations", "administrative", "office ", "procurement",
]


def classify(title, fallback="it"):
    t = title.lower()
    if any(n in t for n in NON_TECH):
        return "nonit"
    return fallback


def guess_qual(text):
    t = text.lower()
    for level, hints in QUAL_HINTS:
        if any(h in t for h in hints):
            return level
    return 0


DATE_PATTERNS = [
    (re.compile(r"(\d{1,2})[./-](\d{1,2})[./-](\d{4})"), "dmy"),
    (re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})"), "ymd"),
]


def find_close_date(text):
    """Pull a last date out of notification text. Returns (iso_date, confirmed)."""
    hint = re.search(r"(last date|closing date|apply.{0,12}before|upto|up to)(.{0,60})",
                     text, re.I)
    scope = hint.group(2) if hint else text
    for rx, order in DATE_PATTERNS:
        m = rx.search(scope)
        if not m:
            continue
        try:
            if order == "dmy":
                d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
            else:
                y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
            found = date(y, mo, d)
            if TODAY <= found <= TODAY + timedelta(days=400):
                return found.isoformat(), True
        except ValueError:
            pass
    return (TODAY + timedelta(days=DEFAULT_WINDOW_DAYS)).isoformat(), False


def row(title, org, cat, close, url, loc="", qual=0, tags="", verify=False, posts="—"):
    return {"title": title.strip()[:140], "org": org, "cat": cat, "close": close,
            "loc": loc, "posts": posts, "qual": qual, "tags": tags,
            "url": url, "verify": verify}


# ---------- source: public ATS feeds (no key, best quality) ----------

def from_greenhouse(slug):
    r = get(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs")
    if not r:
        return []
    out = []
    for j in r.json().get("jobs", []):
        title, loc = j.get("title", ""), (j.get("location") or {}).get("name", "")
        if not wanted(title) or not in_range(loc) or not right_level(title):
            continue
        out.append(row(title, slug.title(), classify(title),
                       (TODAY + timedelta(days=DEFAULT_WINDOW_DAYS)).isoformat(),
                       j.get("absolute_url", ""), loc, 6, title.lower(), verify=True))
    return out


def from_lever(slug):
    r = get(f"https://api.lever.co/v0/postings/{slug}?mode=json")
    if not r:
        return []
    out = []
    for j in r.json():
        title = j.get("text", "")
        loc = (j.get("categories") or {}).get("location", "") or ""
        if not wanted(title) or not in_range(loc) or not right_level(title):
            continue
        out.append(row(title, slug.title(), classify(title),
                       (TODAY + timedelta(days=DEFAULT_WINDOW_DAYS)).isoformat(),
                       j.get("hostedUrl", ""), loc, 6, title.lower(), verify=True))
    return out


def from_ashby(slug):
    r = get(f"https://api.ashbyhq.com/posting-api/job-board/{slug}")
    if not r:
        return []
    out = []
    for j in r.json().get("jobs", []):
        title, loc = j.get("title", ""), j.get("location", "") or ""
        if not wanted(title) or not in_range(loc) or not right_level(title):
            continue
        out.append(row(title, slug.title(), classify(title),
                       (TODAY + timedelta(days=DEFAULT_WINDOW_DAYS)).isoformat(),
                       j.get("jobUrl", ""), loc, 6, title.lower(), verify=True))
    return out


# ---------- source: government notification pages ----------

NOTIFY_WORDS = ["recruitment", "notification", "vacanc", "advertisement",
                "apply online", "direct recruitment", "appointment", "recruit",
                "announcement", "career", "opening", "post", "exam"]

# Links on a homepage that probably lead to the page we actually want.
GATEWAY_WORDS = ["notification", "recruitment", "advertisement", "career",
                 "announcement", "what's new", "whats new", "vacanc"]


def absolute(base, href):
    if href.startswith("http"):
        return href
    root = "/".join(base.split("/")[:3])
    return root + href if href.startswith("/") else base.rstrip("/") + "/" + href


def harvest(page_url, html, org, cat):
    """Pull notification-looking links out of one page."""
    soup = BeautifulSoup(html, "html.parser")
    seen, out = set(), []
    for a in soup.find_all("a", href=True):
        text = " ".join(a.get_text(" ", strip=True).split())
        if not (10 <= len(text) <= 180):
            continue
        if not any(w in text.lower() for w in NOTIFY_WORDS):
            continue
        if text.lower() in seen:
            continue
        seen.add(text.lower())

        context = text + " " + " ".join(
            p.get_text(" ", strip=True)[:200] for p in a.find_parents(limit=2))
        close, confirmed = find_close_date(context)

        out.append(row(text, org, cat, close, absolute(page_url, a["href"]),
                       "Tamil Nadu" if cat == "tn" else "All India",
                       guess_qual(context), text.lower(), verify=not confirmed))
    return out


def from_govt(org, cat, url):
    """Read the landing page, then follow up to 3 notification links one level
    deeper. Homepages rarely list the notices themselves — that was the bug
    that produced zero government results."""
    r = get(url)
    if not r:
        return []

    out = harvest(url, r.text, org, cat)

    # find inner pages worth following
    soup = BeautifulSoup(r.text, "html.parser")
    gateways, seen_urls = [], {url}
    for a in soup.find_all("a", href=True):
        blob = (a.get_text(" ", strip=True) + " " + a["href"]).lower()
        if not any(w in blob for w in GATEWAY_WORDS):
            continue
        target = absolute(url, a["href"])
        if target in seen_urls or target.lower().endswith(".pdf"):
            continue
        seen_urls.add(target)
        gateways.append(target)
        if len(gateways) >= 3:
            break

    for g in gateways:
        log(f"  following {g}")
        rr = get(g)
        if rr:
            out += harvest(g, rr.text, org, cat)
        time.sleep(1)

    # de-duplicate within this source
    uniq, final = set(), []
    for j in out:
        if j["title"].lower() in uniq:
            continue
        uniq.add(j["title"].lower())
        final.append(j)
    return final[:30]


# ---------- source: Adzuna (optional key, broad India coverage) ----------

def from_adzuna():
    if not (ADZUNA_APP_ID and ADZUNA_APP_KEY):
        return []
    out = []
    for kw in KEYWORDS[:6]:
        r = get("https://api.adzuna.com/v1/api/jobs/in/search/1", params={
            "app_id": ADZUNA_APP_ID, "app_key": ADZUNA_APP_KEY,
            "results_per_page": 30, "what": kw,
            "where": LOCATIONS[0], "content-type": "application/json",
        })
        if not r:
            continue
        for j in r.json().get("results", []):
            title = j.get("title", "")
            loc = (j.get("location") or {}).get("display_name", "")
            cat = "it" if wanted(title) else "nonit"
            out.append(row(title, (j.get("company") or {}).get("display_name", "—"),
                           cat, (TODAY + timedelta(days=DEFAULT_WINDOW_DAYS)).isoformat(),
                           j.get("redirect_url", ""), loc, 6, title.lower(), verify=True))
        time.sleep(1)
    return out


# ---------- source: Google Jobs, via SerpApi (paid, no free route exists) ----------

def from_google_jobs():
    if not SERPAPI_KEY:
        return []
    out = []
    for kw in KEYWORDS[:4]:
        r = get("https://serpapi.com/search", params={
            "engine": "google_jobs", "q": f"{kw} jobs",
            "location": LOCATIONS[0], "hl": "en", "gl": "in",
            "api_key": SERPAPI_KEY,
        })
        if not r:
            continue
        for j in r.json().get("jobs_results", []):
            title = j.get("title", "")
            link = (j.get("apply_options") or [{}])[0].get("link", "") or j.get("share_link", "")
            out.append(row(title, j.get("company_name", "—"),
                           "it" if wanted(title) else "nonit",
                           (TODAY + timedelta(days=DEFAULT_WINDOW_DAYS)).isoformat(),
                           link, j.get("location", ""), 6, title.lower(), verify=True))
        time.sleep(1)
    return out


# ---------- assemble ----------

def main():
    jobs = []

    print("Private IT — public ATS feeds", file=sys.stderr)
    for s in GREENHOUSE_BOARDS:
        jobs += from_greenhouse(s)
    for s in LEVER_BOARDS:
        jobs += from_lever(s)
    for s in ASHBY_BOARDS:
        jobs += from_ashby(s)

    print("Government notification pages", file=sys.stderr)
    empty = []
    for org, cat, url in GOVT_SOURCES:
        got = from_govt(org, cat, url)
        log(f"{org}: {len(got)}")
        if not got:
            empty.append(org)
        jobs += got
        time.sleep(1)
    if empty:
        log("NO RESULTS FROM: " + ", ".join(empty))

    print("Optional keyed sources", file=sys.stderr)
    jobs += from_adzuna()
    jobs += from_google_jobs()

    # drop duplicates and anything already expired
    seen, clean = set(), []
    for j in jobs:
        if not j["title"] or not j["url"]:
            continue
        key = (j["title"].lower(), j["org"].lower())
        if key in seen:
            continue
        seen.add(key)
        clean.append(j)

    clean.sort(key=lambda j: j["close"])

    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(clean, f, indent=1, ensure_ascii=False)

    by_cat = {}
    for j in clean:
        by_cat[j["cat"]] = by_cat.get(j["cat"], 0) + 1
    print(f"\nWrote {len(clean)} jobs to {OUTPUT}  {by_cat}", file=sys.stderr)


if __name__ == "__main__":
    main()
