#!/usr/bin/env python3
"""
DontBetSports Newsroom, stage 1.

What one run does:
  1. Reads every official team and league news page in newsroom/sources.json
  2. Skips anything it has already seen
  3. Scores new items with a fast, cheap model and keeps only real news
  4. For each keeper: pulls the original page, writes a draft, then runs a
     separate fact-check pass against the source
  5. Opens a GitHub pull request for each draft that passes.
     Merge it on your phone = publish. Close it = reject.

Runs automatically from .github/workflows/newsroom.yml.
Outside GitHub it does a dry run and saves drafts to newsroom/out/ instead.
"""
import base64, json, os, re, sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urljoin, urlparse
from zoneinfo import ZoneInfo

import anthropic, feedparser, requests
from bs4 import BeautifulSoup

# ======================= SETTINGS =======================
SCORER_MODEL       = "claude-haiku-5-5"    # cheap model for sorting the pile
WRITER_MODEL       = "claude-sonnet-5-5"   # stronger model for writing and fact-checking
MIN_SCORE          = 7                     # 1-10. Raise it to publish less.
MAX_DRAFTS_PER_RUN = 3
MAX_DRAFTS_PER_DAY = 15                    # protects your review time and your budget
MAX_ITEM_AGE_HOURS = 24                    # ignore older feed items
KEEP_TYPES = ["trade", "signing", "release", "injury", "coaching change",
              "front office", "schedule", "suspension", "award", "retirement", "draft pick"]
# ========================================================

ROOT   = Path(__file__).resolve().parent.parent
NR     = ROOT / "newsroom"
POSTS  = ROOT / "posts"
SEEN   = NR / "seen.json"
TZ     = ZoneInfo("America/New_York")
UA     = {"User-Agent": "DontBetSportsNewsroom/1.0 (+https://dontbetsports.com/about/)"}

# Anything matching this is rejected outright, even after fact-checking.
BANNED = re.compile(
    r"\b(bets?|betting|bettors?|odds|point spreads?|against the spread|cover(?:s|ed)? the spread|"
    r"sportsbooks?|parlays?|wagers?|wagering|moneylines?|over/under|prop bets?|gambl\w*|"
    r"draftkings|fanduel|betmgm|bet365|caesars sportsbook|espn ?bet|fanatics sportsbook|"
    r"betrivers|hard rock bet|kalshi|polymarket|prediction markets?)\b", re.I)

client = anthropic.Anthropic()   # reads ANTHROPIC_API_KEY
STYLE  = (NR / "style.md").read_text(encoding="utf-8")


# ---------------- helpers ----------------
def log(msg): print(msg, flush=True)

def ask(model, system, prompt, max_tokens=2000):
    r = client.messages.create(model=model, max_tokens=max_tokens, system=system,
                               messages=[{"role": "user", "content": prompt}])
    return "".join(b.text for b in r.content if b.type == "text")

def as_json(text):
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    start = min([i for i in (text.find("{"), text.find("[")) if i != -1], default=0)
    return json.loads(text[start:])

def slugify(s): return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:80]

def plain(html_text): return " ".join(BeautifulSoup(html_text or "", "html.parser").get_text(" ").split())

def load_seen():
    if SEEN.exists(): return json.loads(SEEN.read_text())
    return {"links": [], "days": {}}

STATS = NR / "stats.json"

def load_stats():
    base = {"since": datetime.now(TZ).date().isoformat(), "runs": 0, "headlines_reviewed": 0,
            "drafts_sent": 0, "rejected_by_fact_check": 0, "blocked_for_betting_terms": 0, "claims_removed": 0}
    if STATS.exists(): base.update(json.loads(STATS.read_text()))
    return base

def save_stats(stats): STATS.write_text(json.dumps(stats, indent=1))

def save_seen(seen):
    seen["links"] = seen["links"][-20000:]
    keep = sorted(seen["days"])[-14:]
    seen["days"] = {d: seen["days"][d] for d in keep}
    SEEN.write_text(json.dumps(seen, indent=1))


# ---------------- 1. scan ----------------
def from_rss(s):
    feed = feedparser.parse(s["url"], agent=UA["User-Agent"])
    if feed.bozo and not feed.entries:
        raise RuntimeError("feed didn't load")
    out = []
    for e in feed.entries[:40]:
        t = e.get("published_parsed") or e.get("updated_parsed")
        when = datetime(*t[:6], tzinfo=timezone.utc) if t else None
        out.append((e.get("link"), plain(e.get("title")), plain(e.get("summary"))[:600], when))
    return out

def from_page(s):
    """Reads a team's news page and collects links to individual stories."""
    r = requests.get(s["url"], headers=UA, timeout=20)
    r.raise_for_status()
    soup, base = BeautifulSoup(r.text, "html.parser"), urlparse(s["url"])
    out, seen_here = [], set()
    for a in soup.find_all("a", href=True):
        link = urljoin(s["url"], a["href"]).split("#")[0].split("?")[0]
        u = urlparse(link)
        title = " ".join(a.get_text(" ").split())
        if (u.netloc != base.netloc or "/news/" not in u.path or u.path.rstrip("/") == base.path.rstrip("/")
                or len(u.path.split("/news/")[-1]) < 12 or len(title) < 25
                or any(x in u.path for x in ("/video", "/podcast", "/photos", "/gallery"))
                or link in seen_here):
            continue
        seen_here.add(link)
        out.append((link, title[:200], "", None))
    if not out:
        raise RuntimeError("no story links found (the page may load with JavaScript; try an RSS feed instead)")
    return out[:60]

def fetch(s):
    try:
        return s, (from_rss(s) if s.get("type") == "rss" else from_page(s)), None
    except Exception as ex:
        return s, [], str(ex)

def scan(sources, seen):
    cutoff = datetime.now(timezone.utc) - timedelta(hours=MAX_ITEM_AGE_HOURS)
    seen_links, items = set(seen["links"]), []
    baselined = set(seen.setdefault("baselined", []))
    active = [s for s in sources if s.get("url") and not s["url"].startswith("PASTE")]
    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(fetch, active))
    failed = 0
    for s, entries, err in results:
        if err:
            failed += 1; log(f"  ! {s['name']}: {err}"); continue
        first_time = s["url"] not in baselined
        new = 0
        for link, title, summary, when in entries:
            if not link or link in seen_links: continue
            seen_links.add(link)
            if first_time or (when and when < cutoff):
                seen["links"].append(link); continue      # old news: remember it, don't write it
            items.append({"id": len(items), "source": s["name"], "league": s.get("league", ""),
                          "team": s.get("team", ""), "title": title, "summary": summary, "link": link})
            new += 1
        if first_time:
            seen["baselined"].append(s["url"])
            log(f"  {s['name']}: first look, {len(entries)} existing stories saved as already seen")
        elif new:
            log(f"  {s['name']}: {new} new")
    log(f"Checked {len(active)} sources, {failed} failed")
    return items


# ---------------- 2. score ----------------
def recent_posts():
    out = []
    for f in POSTS.glob("*.md"):
        m = re.search(r"^title:\s*(.+)$", f.read_text(encoding="utf-8"), re.M)
        if m: out.append({"slug": f.stem, "title": m.group(1).strip().strip('"')})
    return out[-60:]

SCORE_SYSTEM = f"""You are the assignment editor for DontBetSports, a sports news site.
Decide which feed items are real, publishable news. Keep only these story types: {", ".join(KEEP_TYPES)}.
Reject: promotions, giveaways, ticket or merch sales, community events, sponsor announcements,
game previews and recaps with no news, podcasts, videos, opinion, and anything about betting.
We cover all of the NFL, NBA, MLB and NHL nationally. Score 1-10 for how much fans across that
league will care right now. 9-10 is a star traded or signed, a star ruled out long term, or a head
coach or GM change. 7-8 is a notable starter move or injury. 5 or lower is depth moves and routine roster shuffles.
Also check each item against the list of stories already on the site and against the other items:
- duplicate_of: the slug of an existing post that covers the same story, otherwise null
- same_story_as: the id of another item in this batch about the same story, otherwise null
Reply with only a JSON array, one object per item:
[{{"id":0,"keep":true,"score":8,"type":"signing","duplicate_of":null,"same_story_as":null,"reason":"short"}}]"""

def score(items):
    existing = json.dumps(recent_posts())
    results = {}
    for i in range(0, len(items), 25):
        batch = items[i:i+25]
        listing = json.dumps([{k: it[k] for k in ("id", "source", "title", "summary")} for it in batch])
        prompt = f"Stories already on the site:\n{existing}\n\nNew feed items:\n{listing}"
        try:
            for r in as_json(ask(SCORER_MODEL, SCORE_SYSTEM, prompt, 3000)):
                try:
                    r["id"] = int(r["id"]); r["score"] = int(r.get("score") or 0)
                except (KeyError, TypeError, ValueError):
                    continue
                results[r["id"]] = r
        except Exception as ex:
            log(f"  ! scoring failed for a batch: {ex}")
    return results


# ---------------- 3. source text ----------------
def source_text(item):
    text = ""
    try:
        r = requests.get(item["link"], headers=UA, timeout=20)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header", "aside", "form", "noscript"]):
            tag.decompose()
        node = soup.find("article") or soup.find("main") or soup.body
        text = " ".join(node.get_text(" ").split()) if node else ""
    except Exception as ex:
        log(f"  ! couldn't open source page: {ex}")
    if len(text) < len(item["summary"]): text = item["summary"]
    # Drop sponsor or betting sentences before the writer ever sees them
    sentences = re.split(r"(?<=[.!?])\s+", text)
    return " ".join(s for s in sentences if not BANNED.search(s))[:15000]


# ---------------- 4. write ----------------
WRITE_SYSTEM = f"""You write news for DontBetSports. Follow this style guide exactly:

{STYLE}

Reply with only JSON:
{{"title":"...","description":"one or two sentences for Google results","slug":"short-url-words",
"league":"NFL, NBA, MLB or NHL","body":"the article in markdown"}}"""

def write(item, src):
    note = ("This link was picked by the editor and may be a news outlet rather than the team. "
            "Attribute every fact to the source by name, e.g. 'according to ESPN'.\n") if item.get("manual") else ""
    if item.get("x_post"):
        note = (f"This source is a post on X by {item['source']}, not an official announcement. Write it as a report: "
                f"attribute it in the first sentence (e.g. 'according to ESPN's Adam Schefter'), never state it as "
                f"confirmed, and say the team has not confirmed it unless the post says otherwise. Keep it short, "
                f"80 to 200 words. The original post will be embedded below your article, so don't repeat it word for word.\n")
    prompt = (f"Write a news post using ONLY this source.\n{note}"
              f"Source name: {item['source']}\nSource URL: {item['link']}\n"
              f"League: {item['league']}\nTeam: {item['team']}\n\nSOURCE TEXT:\n{src}")
    return as_json(ask(WRITER_MODEL, WRITE_SYSTEM, prompt, 2500))


# ---------------- 5. fact-check ----------------
CHECK_SYSTEM = """You are the fact-checker for DontBetSports. You did not write this draft.
Compare every factual claim in the draft to the source text: names, numbers, dates, contract terms,
injury details, quotes, and who said what.
- A claim not directly supported by the source is unsupported, even if you believe it is true.
- A quote must appear word for word in the source.
- Any mention of betting, odds, spreads, sportsbooks or gambling is a failure.
Then decide:
- "pass": everything is supported
- "fix": small problems; return a corrected body with unsupported claims removed (do not add anything new)
- "reject": the story is wrong, too thin to stand on its own, or not really news
Reply with only JSON:
{"verdict":"pass|fix|reject","unsupported":["claim", "..."],"notes":"one or two sentences","body":"corrected body, or empty if pass/reject"}"""

def fact_check(src, draft):
    prompt = f"SOURCE TEXT:\n{src}\n\nDRAFT TITLE: {draft['title']}\n\nDRAFT BODY:\n{draft['body']}"
    return as_json(ask(WRITER_MODEL, CHECK_SYSTEM, prompt, 3000))


# ---------------- 6. package ----------------
def to_markdown(item, draft):
    q = lambda s: '"' + s.replace('"', "'") + '"'
    front = ["---", f"title: {q(draft['title'])}", f"description: {q(draft['description'])}",
             f"date: {datetime.now(TZ).date().isoformat()}", "author: DBS", "category: News"]
    league = item["league"] or (draft.get("league") if draft.get("league") in ("NFL", "NBA", "MLB", "NHL") else "")
    if league: front.append(f"league: {league}")
    front.append("---")
    credit = f"*Source: [{item['source']}]({item['link']})*"
    embed = ""
    if item.get("x_post"):
        link = item["link"].replace("://x.com/", "://twitter.com/")
        embed = (f'\n\n<blockquote class="twitter-tweet"><a href="{link}">View the post on X</a></blockquote>'
                 f'<script async src="https://platform.twitter.com/widgets.js"></script>')
    return "\n".join(front) + "\n" + draft["body"].strip() + embed + "\n\n" + credit + "\n"

def unique_slug(s):
    s = slugify(s) or "news"
    if not (POSTS / f"{s}.md").exists(): return s
    return f"{s}-{datetime.now(TZ).strftime('%Y%m%d%H%M')}"

def pr_body(item, sc, check):
    lines = []
    if item.get("x_post"):
        lines.append("**⚠️ REPORT:** based on an X post, not an official announcement. "
                     "Check it's the real reporter's account before merging.")
    lines += [f"**Source:** [{item['source']}]({item['link']})",
             f"**Type:** {sc.get('type')} · **Score:** {sc.get('score')}/10",
             f"**Fact-check:** {check['verdict']}. {check.get('notes', '')}"]
    if check.get("unsupported"):
        lines.append("**Removed or flagged claims:**\n" + "\n".join(f"- {c}" for c in check["unsupported"]))
    lines += ["", "Merge to publish. Close to reject. Check the Netlify deploy preview to see it live."]
    return "\n".join(lines)


# ---------------- 7. deliver ----------------
def open_pr(path, content, title, body):
    repo, token = os.environ.get("GITHUB_REPOSITORY"), os.environ.get("GITHUB_TOKEN")
    if not (repo and token):
        out = NR / "out"; out.mkdir(exist_ok=True)
        (out / Path(path).name).write_text(content + "\n\n<!--\n" + body + "\n-->\n")
        log(f"  dry run: saved newsroom/out/{Path(path).name}"); return
    api, h = f"https://api.github.com/repos/{repo}", {"Authorization": f"Bearer {token}",
                                                       "Accept": "application/vnd.github+json"}
    base = requests.get(api, headers=h).json()["default_branch"]
    sha = requests.get(f"{api}/git/ref/heads/{base}", headers=h).json()["object"]["sha"]
    branch = f"draft/{Path(path).stem}"
    requests.post(f"{api}/git/refs", headers=h, json={"ref": f"refs/heads/{branch}", "sha": sha}).raise_for_status()
    requests.put(f"{api}/contents/{path}", headers=h, json={
        "message": f"Draft: {title}", "branch": branch,
        "content": base64.b64encode(content.encode()).decode()}).raise_for_status()
    r = requests.post(f"{api}/pulls", headers=h, json={"title": title, "head": branch, "base": base, "body": body})
    r.raise_for_status()
    log(f"  ✓ pull request opened: {r.json()['html_url']}")


# ---------------- manual mode ----------------
def manual_draft(url, sources, seen, stats):
    """Drafts one story from a link you paste into the Run workflow box. Skips scoring."""
    u = urlparse(url)
    first = lambda p: p.strip("/").split("/")[0] if p.strip("/") else ""
    match = None
    for s in sources:
        su = urlparse(s.get("url", ""))
        if su.netloc == u.netloc and (not s.get("team") or su.netloc.count(".") and
                                      (first(su.path) == first(u.path) or first(su.path) == "news")):
            match = s
            if s.get("team"): break
    host = u.netloc.replace("www.", "")
    league = (match or {}).get("league") or next((l for l in ("NFL", "NBA", "MLB", "NHL") if l.lower() in host), "")
    item = {"id": 0, "source": (match or {}).get("name") or host, "league": league,
            "team": (match or {}).get("team", ""), "title": "", "summary": "", "link": url, "manual": True}
    pasted = os.environ.get("MANUAL_TEXT", "").strip()
    if host in ("x.com", "twitter.com", "mobile.twitter.com"):
        item["x_post"] = True
        author, text = "", ""
        try:
            r = requests.get("https://publish.twitter.com/oembed",
                             params={"url": url.replace("://x.com/", "://twitter.com/"), "omit_script": "true"},
                             headers=UA, timeout=20)
            r.raise_for_status()
            data = r.json()
            author = data.get("author_name", "")
            p = BeautifulSoup(data.get("html", ""), "html.parser").find("p")
            text = " ".join(p.get_text(" ").split()) if p else ""
        except Exception as ex:
            log(f"  ! couldn't read the X post automatically ({ex})")
        if not author:
            author = "@" + first(u.path) if first(u.path) else "a post on X"
        item["source"] = f"{author} on X"
        text = (text + " " + pasted).strip()
        if len(text) < 20:
            log("  ! no post text found. Run it again and paste the post's text into the second box."); return
        log(f"Manual draft from an X post by {author}: {url}")
        src = f"Post on X by {author}: {text}"
        draft = write(item, src)
        check = fact_check(src, draft)
        return finish_manual(item, draft, check, url, seen, stats)
    log(f"Manual draft from {item['source']}: {url}")
    src = source_text(item)
    if pasted: src = (src + " " + pasted).strip()
    if len(src) < 250:
        log("  ! couldn't read enough text from that page. Try the team's official announcement link instead."); return
    draft = write(item, src)
    check = fact_check(src, draft)
    finish_manual(item, draft, check, url, seen, stats)


def finish_manual(item, draft, check, url, seen, stats):
    if check["verdict"] == "reject":
        log(f"  rejected by fact-check: {check.get('notes')}"); stats["rejected_by_fact_check"] += 1; return
    if check["verdict"] == "fix" and check.get("body"):
        draft["body"] = check["body"]
    full = " ".join([draft["title"], draft["description"], draft["body"]])
    if BANNED.search(full):
        log(f"  rejected: banned term '{BANNED.search(full).group(0)}'"); stats["blocked_for_betting_terms"] += 1; return
    slug = unique_slug(draft.get("slug") or draft["title"])
    open_pr(f"posts/{slug}.md", to_markdown(item, draft), draft["title"],
            pr_body(item, {"type": "manual request", "score": "—"}, check))
    seen["links"].append(url)
    stats["drafts_sent"] += 1
    stats["claims_removed"] += len(check.get("unsupported") or [])


# ---------------- main ----------------
def main():
    sources = json.loads((NR / "sources.json").read_text())["sources"]
    seen = load_seen()
    stats = load_stats(); stats["runs"] += 1
    manual = os.environ.get("MANUAL_URL", "").strip()
    if manual:
        manual_draft(manual, sources, seen, stats)
        save_seen(seen); save_stats(stats); return
    today = datetime.now(TZ).date().isoformat()
    left_today = MAX_DRAFTS_PER_DAY - seen["days"].get(today, 0)

    log("Scanning feeds...")
    items = scan(sources, seen)
    log(f"{len(items)} new items")
    stats["headlines_reviewed"] += len(items)
    if not items:
        save_seen(seen); save_stats(stats); return

    log("Scoring...")
    scores = score(items)
    for it in items: seen["links"].append(it["link"])     # never rescore the same item

    # Show every headline's score so you can see why things were kept or skipped
    log(f"Scored {len(scores)} of {len(items)} items:")
    for it in sorted(items, key=lambda i: scores.get(i["id"], {}).get("score", 0), reverse=True):
        sc = scores.get(it["id"])
        if not sc:
            log(f"  [?] not scored: {it['title'][:90]}"); continue
        mark = "KEEP" if sc.get("keep") and sc["score"] >= MIN_SCORE else "skip"
        log(f"  [{sc['score']:>2}] {mark} {sc.get('type','')}: {it['title'][:80]} ({sc.get('reason','')[:60]})")

    keepers = []
    for it in items:
        sc = scores.get(it["id"], {})
        if not sc.get("keep") or sc.get("score", 0) < MIN_SCORE: continue
        if sc.get("duplicate_of"):
            log(f"  already covered ({sc['duplicate_of']}): {it['title']}"); continue
        twin = sc.get("same_story_as")
        if twin is not None and twin != it["id"]:
            ts = scores.get(twin, {}).get("score", 0)
            if ts > sc["score"] or (ts == sc["score"] and twin < it["id"]):
                continue      # the other version of this story wins
        keepers.append((sc["score"], it, sc))
    keepers.sort(key=lambda k: k[0], reverse=True)
    log(f"{len(keepers)} worth drafting, room for {min(MAX_DRAFTS_PER_RUN, left_today)} this run")

    made = 0
    for _, it, sc in keepers:
        if made >= min(MAX_DRAFTS_PER_RUN, left_today): break
        log(f"Drafting: {it['title']}")
        try:
            src = source_text(it)
            if len(src) < 250:
                log("  skipped: source too thin to write from"); continue
            draft = write(it, src)
            check = fact_check(src, draft)
            if check["verdict"] == "reject":
                stats["rejected_by_fact_check"] += 1
                log(f"  rejected by fact-check: {check.get('notes')}"); continue
            if check["verdict"] == "fix" and check.get("body"):
                draft["body"] = check["body"]
            full = " ".join([draft["title"], draft["description"], draft["body"]])
            if BANNED.search(full):
                stats["blocked_for_betting_terms"] += 1
                log(f"  rejected: banned term '{BANNED.search(full).group(0)}'"); continue
            slug = unique_slug(draft.get("slug") or draft["title"])
            open_pr(f"posts/{slug}.md", to_markdown(it, draft), draft["title"], pr_body(it, sc, check))
            made += 1
            stats["claims_removed"] += len(check.get("unsupported") or [])
        except Exception as ex:
            log(f"  ! failed: {ex}")

    seen["days"][today] = seen["days"].get(today, 0) + made
    stats["drafts_sent"] += made
    save_seen(seen); save_stats(stats)
    log(f"Done. {made} draft(s) sent for review.")

if __name__ == "__main__":
    sys.exit(main())
