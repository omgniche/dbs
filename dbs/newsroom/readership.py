#!/usr/bin/env python3
"""
Pulls real readership numbers from Plausible Analytics once a day and saves
them to newsroom/readership.json. The In Public page is built from that file.

Runs automatically from .github/workflows/in-public.yml.
Needs two GitHub secrets: PLAUSIBLE_API_KEY and PLAUSIBLE_SITE (e.g. dontbetsports.com).
If anything fails, the old numbers are kept so the page never shows wrong data.
"""
import json, os, sys
from datetime import date, timedelta
from pathlib import Path
import requests

OUT = Path(__file__).resolve().parent / "readership.json"
API = "https://plausible.io/api/v2/query"
TOP_STORIES_DELAY_DAYS = 7      # top stories are shown on a delay so the page isn't a live tip sheet

def query(key, site, body):
    r = requests.post(API, headers={"Authorization": f"Bearer {key}"},
                      json={"site_id": site, **body}, timeout=30)
    r.raise_for_status()
    return r.json().get("results", [])

def main():
    key, site = os.environ.get("PLAUSIBLE_API_KEY"), os.environ.get("PLAUSIBLE_SITE")
    if not (key and site):
        print("No Plausible secrets set yet. Skipping."); return
    today = date.today()
    try:
        last30 = query(key, site, {"metrics": ["visitors", "pageviews"], "date_range": "30d"})
        alltime = query(key, site, {"metrics": ["visitors", "pageviews"], "date_range": "all"})
        months = query(key, site, {"metrics": ["visitors", "pageviews"], "date_range": "all",
                                   "dimensions": ["time:month"]})
        end = today - timedelta(days=TOP_STORIES_DELAY_DAYS)
        start = end - timedelta(days=30)
        top = query(key, site, {"metrics": ["pageviews"], "date_range": [start.isoformat(), end.isoformat()],
                                "dimensions": ["event:page"], "order_by": [["pageviews", "desc"]],
                                "pagination": {"limit": 20}})
    except Exception as ex:
        print(f"Plausible request failed, keeping old numbers: {ex}"); return

    m = lambda rows, i: rows[0]["metrics"][i] if rows else 0
    skip = {"/", "/news/", "/takes/", "/about/", "/in-public/", "/404.html"}
    data = {
        "updated": today.isoformat(),
        "readers_30d": m(last30, 0), "reads_30d": m(last30, 1),
        "readers_all": m(alltime, 0), "reads_all": m(alltime, 1),
        "months": [{"month": r["dimensions"][0][:7], "readers": r["metrics"][0], "reads": r["metrics"][1]}
                   for r in months][-12:],
        "top_pages": [{"path": r["dimensions"][0], "reads": r["metrics"][0]}
                      for r in top if r["dimensions"][0] not in skip][:8],
        "top_window": f"{start.isoformat()} to {end.isoformat()}",
    }
    OUT.write_text(json.dumps(data, indent=1))
    print(f"Saved: {data['readers_30d']} readers in the last 30 days")

if __name__ == "__main__":
    sys.exit(main())
