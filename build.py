#!/usr/bin/env python3
"""
DontBetSports site builder.

Write posts as .md files in /posts, then run:   python3 build.py
The finished site lands in /public. Netlify runs this automatically
on every deploy (see netlify.toml), so you never touch /public yourself.
"""
import html, json, re, shutil
from datetime import date, datetime
from email.utils import format_datetime
from pathlib import Path

# ======================= SITE SETTINGS =======================
SITE_URL   = "https://dontbetsports.com"   # no trailing slash
SITE_NAME  = "DontBetSports"
TAGLINE    = "Sports news and takes with no sportsbooks, no betting lines and no odds."
X_HANDLE   = "@DontBetSports"
CONTACT_EMAIL = "partners@dontbetsports.com"   # shown on the privacy page; form messages go to your Netlify email
# Paste the tracking snippet Plausible gives you between the triple quotes. Leave empty to turn off.
ANALYTICS_SNIPPET = """<!-- Google Tag Manager -->
<script>(function(w,d,s,l,i){w[l]=w[l]||[];w[l].push({'gtm.start':
new Date().getTime(),event:'gtm.js'});var f=d.getElementsByTagName(s)[0],
j=d.createElement(s),dl=l!='dataLayer'?'&l='+l:'';j.async=true;j.src=
'https://www.googletagmanager.com/gtm.js?id='+i+dl;f.parentNode.insertBefore(j,f);
})(window,document,'script','dataLayer','GTM-T5DGTQ4T');</script>
<!-- End Google Tag Manager -->"""
GTM_ID = "GTM-T5DGTQ4T"
CATEGORIES = ["News", "Takes", "Worth Watching"]
LEAGUES    = ["NFL", "NBA", "MLB", "NHL"]
# =============================================================

ROOT = Path(__file__).parent
POSTS_DIR, STATIC, OUT = ROOT / "posts", ROOT / "static", ROOT / "public"

def slugify(s): return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
def esc(s): return html.escape(str(s), quote=True)
def nice_date(d): return d.strftime("%b %-d, %Y")

# ---------- tiny markdown ----------
def inline(t):
    t = esc(t)
    t = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", r'<a href="\2">\1</a>', t)
    t = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", t)
    t = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<em>\1</em>", t)
    return t

def markdown(src):
    out = []
    for block in re.split(r"\n\s*\n", src.strip()):
        lines = block.strip().split("\n")
        first = lines[0]
        if first.startswith("<"):                       # raw HTML, e.g. an embedded X post
            out.append(block)
        elif first.startswith("### "):
            out.append(f"<h3>{inline(first[4:])}</h3>")
        elif first.startswith("## "):
            out.append(f'<h2 id="{slugify(first[3:])}">{inline(first[3:])}</h2>')
        elif all(l.startswith("> ") for l in lines):
            out.append("<blockquote>" + " ".join(inline(l[2:]) for l in lines) + "</blockquote>")
        elif all(l.startswith("- ") for l in lines):
            out.append("<ul>" + "".join(f"<li>{inline(l[2:])}</li>" for l in lines) + "</ul>")
        elif all(re.match(r"\d+\. ", l) for l in lines):
            out.append("<ol>" + "".join(f"<li>{inline(l.split('. ',1)[1])}</li>" for l in lines) + "</ol>")
        else:
            out.append("<p>" + inline(" ".join(lines)) + "</p>")
    return "\n".join(out)

# ---------- load posts ----------
def parse_front(block):
    """Reads the --- header of a post, including headers written by the site editor at /admin/."""
    meta, lines, i = {}, block.split("\n"), 0
    while i < len(lines):
        line = lines[i]; i += 1
        if not line.strip() or line.startswith((" ", "\t")) or ":" not in line:
            continue
        k, v = line.split(":", 1); k, v = k.strip().lower(), v.strip()
        if v in (">", ">-", ">+", "|", "|-", "|+"):            # multi-line value
            parts = []
            while i < len(lines) and (lines[i].startswith((" ", "\t")) or not lines[i].strip()):
                parts.append(lines[i].strip()); i += 1
            v = (" " if v.startswith(">") else "\n").join(p for p in parts if p)
        elif len(v) > 1 and v[0] == v[-1] and v[0] in "\"'":
            v = v[1:-1].replace("''", "'") if v[0] == "'" else v[1:-1].replace('\\"', '"')
        meta[k] = v
    return meta

def load_posts():
    posts = []
    for f in sorted(POSTS_DIR.glob("*.md")):
        raw = f.read_text(encoding="utf-8").replace("\r\n", "\n")
        m = re.match(r"---\n(.*?)\n---\n?(.*)", raw, re.S)
        if not m:
            print(f"  skipped {f.name}: missing the --- header block"); continue
        meta = parse_front(m.group(1))
        if meta.get("draft", "").lower() == "true":
            print(f"  draft, not published: {f.name}"); continue
        missing = [k for k in ("title", "description", "date", "author", "category") if not meta.get(k)]
        if missing:
            print(f"  skipped {f.name}: add {', '.join(missing)}"); continue
        if meta["category"] not in CATEGORIES:
            print(f"  skipped {f.name}: category must be one of {CATEGORIES}"); continue
        p = dict(meta)
        p["slug"] = meta.get("slug") or slugify(f.stem)
        p["date"] = date.fromisoformat(meta["date"][:10])
        p["updated"] = date.fromisoformat(meta["updated"][:10]) if meta.get("updated") else p["date"]
        p["league"] = meta.get("league", "")
        p["featured"] = meta.get("featured", "").lower() == "true"
        p["html"] = markdown(m.group(2))
        p["url"] = f"/{p['slug']}/"
        posts.append(p)
    posts.sort(key=lambda p: p["date"], reverse=True)
    return posts

# ---------- page shell ----------
NAV = [("Home", "/"), ("News", "/news/"), ("Takes", "/takes/")]

def page(title, description, path, body, active="", extra_head=""):
    canonical = SITE_URL + path
    cur = ' aria-current="page"'
    nav = "".join(f'<a href="{u}"{cur if n == active else ""}>{n}</a>' for n, u in NAV)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<meta name="description" content="{esc(description)}">
<link rel="canonical" href="{canonical}">
<meta property="og:site_name" content="{SITE_NAME}">
<meta property="og:title" content="{esc(title)}">
<meta property="og:description" content="{esc(description)}">
<meta property="og:url" content="{canonical}">
<meta property="og:image" content="{SITE_URL}/static/logo.png">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:site" content="{X_HANDLE}">
<link rel="icon" href="/static/logo.png">
<link rel="alternate" type="application/rss+xml" title="{SITE_NAME}" href="/feed.xml">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Big+Shoulders+Display:wght@900&family=Source+Serif+4:opsz,wght@8..60,400;8..60,600&family=Inter:wght@500;600;700&display=swap" rel="stylesheet">
<link rel="stylesheet" href="/static/style.css">
{extra_head}
{ANALYTICS_SNIPPET}
</head>
<body>
<noscript><iframe src="https://www.googletagmanager.com/ns.html?id={GTM_ID}" height="0" width="0" style="display:none;visibility:hidden"></iframe></noscript>
<div class="promise">No sportsbooks. No betting lines. No odds. Ever.</div>
<header><div class="wrap">
  <a class="brand" href="/" aria-label="{SITE_NAME} home"><img src="/static/logo.png" alt="Dont" width="114" height="62"><span>Bet Sports</span></a>
  <nav>{nav}</nav>
</div></header>
<main>{body}</main>
<footer><div class="wrap">
  <div class="big">Just Sports… <em>never the line.</em></div>
  <p>{SITE_NAME} covers sports news and takes the way fans talk about them.</p>
  <div class="links"><a href="/about/">About</a><a href="/in-public/">In Public</a><a href="/contact/">Partner with us</a><a href="/privacy/">Privacy &amp; disclosures</a><a href="/feed.xml">RSS</a><a href="https://x.com/{X_HANDLE.lstrip('@')}">X</a></div>
  <p>&copy; {date.today().year} {SITE_NAME}</p>
</div></footer>
</body>
</html>"""

SWOOSH = '<svg viewBox="0 0 600 44" preserveAspectRatio="none" aria-hidden="true"><path d="M4 40 Q300 -12 596 40" fill="none" stroke="#E3101A" stroke-width="7" stroke-linecap="round"/></svg>'

def tag_for(p):
    t = p["league"] or p["category"]
    return f'<span class="tag">{esc(t)}</span>'

def feed_item(p):
    label = " · ".join(x for x in (p["league"], p["category"]) if x)
    return f"""<article>
  <div class="meta">{esc(label)}<br><time datetime="{p['date']}">{nice_date(p['date'])}</time></div>
  <div><h3><a href="{p['url']}">{esc(p['title'])}</a></h3><p>{esc(p['description'])}</p><div class="by" style="margin-top:6px">{esc(p['author'])}</div></div>
</article>"""

def feed(lst):
    return "".join(feed_item(p) for p in lst) if lst else '<p class="empty">No posts here yet.</p>'

def sidebar(posts, exclude=None, latest=True):
    recent = [p for p in posts if p is not exclude][:5]
    links = "".join(f'<li><a href="{p["url"]}">{esc(p["title"])}</a></li>' for p in recent)
    box = f'<div class="box"><h3>Latest</h3><ul>{links}</ul></div>' if latest else ""
    return f"""<div class="box">
  <h3>The weekly</h3>
  <p>The biggest stories and the games worth watching, every Thursday. No odds, ever.</p>
  <form action="#" method="post"><input type="email" required placeholder="you@email.com" aria-label="Email address">
  <button class="btn" type="submit">Subscribe</button></form>
</div>
{box}"""

# ---------- pages ----------
def home(posts):
    lead = next((p for p in posts if p["featured"]), posts[0])
    rest = [p for p in posts if p is not lead]
    side = "".join(f'<a href="{p["url"]}">{tag_for(p)}<h2>{esc(p["title"])}</h2><div class="by">{esc(p["author"])}</div></a>' for p in rest[:3])
    blocks = ""
    for l in LEAGUES[:4]:
        lp = [p for p in posts if p["league"] == l][:4]
        items = "".join(f'<li><a href="{p["url"]}">{esc(p["title"])}</a></li>' for p in lp) or '<li class="none">Coverage coming soon</li>'
        blocks += f'<div class="league"><h3><a href="/{slugify(l)}/">{l}</a></h3><ul>{items}</ul></div>'
    body = f"""<div class="wrap">
  <div class="lead">
    <a class="hero" href="{lead['url']}">{tag_for(lead)}
      <h2>{esc(lead['title'])}</h2>{SWOOSH}<p>{esc(lead['description'])}</p>
      <div class="by">{esc(lead['author'])}, {nice_date(lead['date'])}</div></a>
    <div class="side">{side}</div>
  </div>
  <section class="cols">
    <div><div class="head"><h2>Latest</h2><p>Everything, newest first</p></div><div class="feed">{feed(posts[:20])}</div></div>
    <aside>{sidebar(posts, latest=False)}</aside>
  </section>
</div>"""
    ld = {"@context":"https://schema.org","@type":"WebSite","name":SITE_NAME,"url":SITE_URL+"/"}
    return page(f"{SITE_NAME}: sports news and takes, no odds", TAGLINE, "/", body, "Home",
                f'<script type="application/ld+json">{json.dumps(ld)}</script>')

def listing(name, lst, posts, blurb):
    path = f"/{slugify(name)}/"
    body = f"""<div class="wrap"><section class="cols">
  <div><div class="head"><h1>{esc(name)}</h1><p>{blurb}</p></div><div class="feed">{feed(lst)}</div></div>
  <aside>{sidebar(posts)}</aside></section></div>"""
    return path, page(f"{name} news and takes | {SITE_NAME}", f"{name} coverage from {SITE_NAME}. {TAGLINE}", path, body, name)

def article(p, posts):
    related = [x for x in posts if x is not p and ((p["league"] and x["league"] == p["league"]) or x["category"] == p["category"])][:3]
    crumbs = f'<a href="/">Home</a> / <a href="/{slugify(p["category"])}/">{esc(p["category"])}</a>'
    if p["league"]: crumbs += f' / <a href="/{slugify(p["league"])}/">{esc(p["league"])}</a>'
    upd = f' · Updated <time datetime="{p["updated"]}">{nice_date(p["updated"])}</time>' if p["updated"] != p["date"] else ""
    rel = f'<section class="related"><div class="head"><h2>Keep reading</h2></div><div class="feed">{feed(related)}</div></section>' if related else ""
    body = f"""<div class="wrap"><div class="article">
  <div class="crumbs">{crumbs}</div>
  <h1>{esc(p['title'])}</h1>
  <p class="dek">{esc(p['description'])}</p>
  <div class="by">By {esc(p['author'])} · <time datetime="{p['date']}">{nice_date(p['date'])}</time>{upd}</div>
  <div class="body">{p['html']}</div>
  {rel}
</div></div>"""
    ld = {"@context":"https://schema.org","@type":"NewsArticle","headline":p["title"],"description":p["description"],
          "datePublished":p["date"].isoformat(),"dateModified":p["updated"].isoformat(),
          "author":{"@type":"Person","name":p["author"]},
          "publisher":{"@type":"Organization","name":SITE_NAME,"logo":{"@type":"ImageObject","url":SITE_URL+"/static/logo.png"}},
          "image":[SITE_URL+"/static/logo.png"],"mainEntityOfPage":SITE_URL+p["url"]}
    head = (f'<meta property="og:type" content="article"><meta property="article:published_time" content="{p["date"]}">'
            f'<script type="application/ld+json">{json.dumps(ld)}</script>')
    return page(f"{p['title']} | {SITE_NAME}", p["description"], p["url"], body, p["category"], head)

def about():
    body = f"""<div class="wrap"><section><div class="head"><h1>About {SITE_NAME}</h1></div><div class="prose">
<p>{SITE_NAME} is a sports news site for fans who are tired of betting lines in everything they watch and read.</p>
<p>We cover the NFL, NBA, MLB and NHL with news, takes and our weekly Worth Watching rankings. What you won't find here are odds, spreads, parlays or sportsbook promotions.</p>
<p>Our news reports are drafted with AI tools working only from official sources like team and league announcements. Every story is fact-checked against its source and reviewed by a human editor before it publishes, and each one links to the source it came from.</p>
<p>We support the site with regular advertising. We do not accept money from sportsbooks, betting apps or gambling companies, and we never will.</p>
<p>We publish our real readership and newsroom numbers on our <a href="/in-public/">In Public</a> page.</p>
<p>Have a tip or a correction? Reach us on X at {X_HANDLE}. For partnerships, use our <a href="/contact/">contact form</a>.</p>
</div></section></div>"""
    return page(f"About | {SITE_NAME}", f"What {SITE_NAME} is and why we never run gambling ads.", "/about/", body)

def not_found(posts):
    body = f"""<div class="wrap"><section class="cols"><div><div class="head"><h1>That page isn't here</h1></div>
<p class="empty">It may have moved or been taken down. Here's what's new instead.</p><div class="feed">{feed(posts[:5])}</div></div>
<aside>{sidebar(posts)}</aside></section></div>"""
    return page(f"Page not found | {SITE_NAME}", TAGLINE, "/404.html", body)


def fmt(n):
    n = int(n or 0)
    return f"{n/1_000_000:.1f}M" if n >= 1_000_000 else f"{n/1000:.1f}K" if n >= 10_000 else f"{n:,}"

def in_public(posts):
    nr = ROOT / "newsroom"
    stats = json.loads((nr / "stats.json").read_text()) if (nr / "stats.json").exists() else {}
    reads = json.loads((nr / "readership.json").read_text()) if (nr / "readership.json").exists() else {}
    by_path = {p["url"]: p for p in posts}

    promise = "".join(f'<div class="zero"><strong>0</strong><span>{label}</span></div>' for label in
                      ("Sportsbook ads served", "Odds published", "Betting partners"))

    if reads.get("readers_30d"):
        headline = (f'<p class="claim">{fmt(reads["readers_30d"])} fans read DontBetSports in the last 30 days, '
                    f'without a single betting ad.</p>')
        nums = (f'<div class="stats">'
                f'<div><strong>{fmt(reads["readers_30d"])}</strong><span>Readers, last 30 days</span></div>'
                f'<div><strong>{fmt(reads["reads_30d"])}</strong><span>Reads, last 30 days</span></div>'
                f'<div><strong>{fmt(reads["reads_all"])}</strong><span>Reads since launch</span></div></div>')
        months = reads.get("months", [])
        peak = max([m["reads"] for m in months] or [1]) or 1
        bars = "".join(f'<div class="bar"><span style="height:{max(3, round(m["reads"]/peak*100))}%"></span>'
                       f'<em>{fmt(m["reads"])}</em><b>{datetime.strptime(m["month"], "%Y-%m").strftime("%b")}</b></div>'
                       for m in months)
        trend = f'<div class="bars" role="img" aria-label="Monthly reads">{bars}</div>' if months else ""
        tops = []
        for t in reads.get("top_pages", []):
            p = by_path.get(t["path"])
            if p: tops.append(f'<li><a href="{p["url"]}">{esc(p["title"])}</a><span>{fmt(t["reads"])} reads</span></li>')
        top_html = (f'<h2 class="sub">What fans read most</h2><p class="note">Shown on a one-week delay '
                    f'({reads.get("top_window","")}).</p><ol class="top">{"".join(tops)}</ol>') if tops else ""
        readership = headline + nums + '<h2 class="sub">How we\'re growing</h2>' + trend + top_html
        updated = f'Readership updated {reads.get("updated","")}.'
    else:
        readership = '<p class="note">Live readership numbers appear here once our analytics has a full day of data.</p>'
        updated = ""

    try:
        n_sources = len(json.loads((nr / "sources.json").read_text())["sources"])
    except Exception:
        n_sources = 0
    published = sum(1 for p in posts if p.get("author") == "DBS" and p["category"] == "News")
    reviewed = stats.get("headlines_reviewed", 0)
    share = published / reviewed * 100 if reviewed else None
    cut = "—" if share is None else f"{share:.2f}%" if share < 1 else f"{share:.1f}%"
    newsroom = (f'<div class="stats">'
                f'<div><strong>{n_sources}</strong><span>Official team and league sources watched</span></div>'
                f'<div><strong>{fmt(reviewed)}</strong><span>Headlines reviewed</span></div>'
                f'<div><strong>{fmt(published)}</strong><span>News stories published</span></div>'
                f'<div><strong>{cut}</strong><span>Share that made the cut</span></div>'
                f'<div><strong>{fmt(stats.get("claims_removed", 0))}</strong><span>Claims removed by fact-checking</span></div>'
                f'<div><strong>{fmt(stats.get("rejected_by_fact_check", 0) + stats.get("blocked_for_betting_terms", 0))}</strong><span>Drafts killed before publishing</span></div>'
                f'</div>')
    since = f' Newsroom numbers count from {stats["since"]}.' if stats.get("since") else ""

    body = f"""<div class="wrap"><section class="inpub">
  <p class="kicker">DontBetSports in public</p>
  <h1>Building a sports newsroom in the open.</h1>
  <p class="lede">Most sports media runs on betting money. We don't. This page shows our real readership,
  how our newsroom works, and the promise we keep, updated automatically.</p>

  <h2 class="sub">The promise</h2>
  <div class="zeros">{promise}</div>

  <h2 class="sub">Our readers</h2>
  {readership}

  <h2 class="sub">The newsroom at work</h2>
  <p class="note">Our AI newsroom watches every NFL, NBA, MLB and NHL team. It drafts stories only from
  official sources, fact-checks every claim against the source, and a human editor approves every story
  before it publishes.</p>
  {newsroom}

  <h2 class="sub">How we count</h2>
  <div class="prose"><p>Readership comes from our site analytics, which filters out known bots.
  A "reader" is a unique visitor and a "read" is a single page view. Newsroom numbers come from our
  newsroom's own logs. If a number here ever looks wrong, tell us through our <a href="/contact/">contact form</a>.
  {updated}{since}</p></div>

  <div class="partner"><div><strong>Reach fans who chose sports without betting.</strong>
  <span>Sponsorships, newsletter placements and brand partnerships. No gambling brands, ever.</span></div>
  <a class="btn" href="/contact/">Partner with us</a></div>
</section></div>"""
    return page(f"In Public: our real numbers | {SITE_NAME}",
                "DontBetSports' real readership and newsroom numbers, updated automatically. Zero sportsbook ads, ever.",
                "/in-public/", body)


def contact():
    body = """<div class="wrap"><section><div class="head"><h1>Partner with us</h1></div>
<div class="prose"><p>Sponsorships, newsletter placements, brand partnerships, news tips and corrections all come here.
We work with brands of every kind except sportsbooks, betting apps and gambling companies.</p>
<p>Want to see our audience first? Our <a href="/in-public/">In Public</a> page shows our real readership.</p></div>
<form class="form" name="contact" method="POST" action="/contact/thanks/" data-netlify="true" netlify-honeypot="bot-field">
  <input type="hidden" name="form-name" value="contact">
  <p class="hp"><label>Leave this empty <input name="bot-field"></label></p>
  <label>Your name<input name="name" required autocomplete="name"></label>
  <label>Email<input type="email" name="email" required autocomplete="email"></label>
  <label>Company or brand <span>(optional)</span><input name="company" autocomplete="organization"></label>
  <label>What's this about?
    <select name="reason" required>
      <option value="">Choose one</option>
      <option>Sponsorship or advertising</option>
      <option>Newsletter placement</option>
      <option>Brand partnership</option>
      <option>News tip</option>
      <option>Correction</option>
      <option>Something else</option>
    </select></label>
  <label>Message<textarea name="message" rows="6" required></textarea></label>
  <button class="btn" type="submit">Send</button>
</form></section></div>"""
    return page(f"Partner with us | {SITE_NAME}", f"Advertise, sponsor or partner with {SITE_NAME}. No gambling brands, ever.", "/contact/", body)

def contact_thanks():
    body = """<div class="wrap"><section><div class="head"><h1>Got it. Thanks!</h1></div>
<div class="prose"><p>Your message is in. We'll get back to you soon.</p><p><a href="/">Back to the latest news</a></p></div></section></div>"""
    return page(f"Thanks | {SITE_NAME}", "Message sent.", "/contact/thanks/", body)

def privacy():
    upd = "November 7, 2026"
    body = f"""<div class="wrap"><section><div class="head"><h1>Privacy &amp; disclosures</h1></div><div class="prose">
<p><em>Last updated {upd}</em></p>
<p>This page explains what information {SITE_NAME} collects, how we use it, and how we make money.
{SITE_NAME} is operated by Normie Labs LLC.</p>

<h2>Affiliate disclosure</h2>
<p>Some links on {SITE_NAME} may be affiliate links. If you click one and buy something, we may earn a commission
at no extra cost to you. Affiliate relationships never decide what we cover or how we cover it.
We never use affiliate links, ads or partnerships from sportsbooks, betting apps or gambling companies.</p>

<h2>Advertising and sponsors</h2>
<p>We may show ads or run sponsored placements to support the site. Sponsored content is always labeled.
We do not accept advertising from gambling companies of any kind.</p>

<h2>How our news is made</h2>
<p>Our news reports are drafted with AI tools from official sources, fact-checked against those sources, and
approved by a human editor before publishing. Every report links to its source.</p>

<h2>What we collect</h2>
<p><strong>Visit statistics.</strong> We use Google Analytics, loaded through Google Tag Manager, to understand
how many people visit and which stories they read. It uses cookies and collects information such as pages viewed,
how you arrived at the site, your device and browser, and your approximate location. Google processes this data
under its own privacy policy. You can opt out with Google's Analytics opt-out browser add-on or by blocking cookies
in your browser.</p>
<p><strong>Messages you send us.</strong> If you use our contact form, we receive the name, email and message you
enter. We use it only to reply to you, and we don't sell it or share it with anyone else.</p>
<p><strong>Newsletter.</strong> If you subscribe, we keep your email address to send the newsletter. Every email
has an unsubscribe link.</p>

<h2>Cookies and embedded content</h2>
<p>We use cookies for analytics, as described above. We do not use cookies for gambling or betting promotions, and we
do not sell your information. Some stories include embedded posts from X or other platforms, which may set their own
cookies under their own privacy policies when the embed loads.</p>

<h2>Services we use</h2>
<p>Our site is hosted by Netlify, which processes basic technical data such as IP addresses to deliver pages
and block abuse. Contact form messages are stored by Netlify. Analytics are provided by Google.</p>

<h2>Children</h2>
<p>{SITE_NAME} is not directed at children under 13, and we do not knowingly collect information from them.</p>

<h2>Your choices</h2>
<p>You can ask us to delete any message you've sent us, or ask what information we hold about you, through our
<a href="/contact/">contact form</a> or at {CONTACT_EMAIL}.</p>

<h2>Changes</h2>
<p>If we change this policy, we'll update the date at the top of this page.</p>
</div></section></div>"""
    return page(f"Privacy & disclosures | {SITE_NAME}", f"How {SITE_NAME} handles your information, plus our affiliate and advertising disclosures.", "/privacy/", body)

# ---------- feeds ----------
def sitemap(urls):
    rows = "".join(f"<url><loc>{SITE_URL}{u}</loc><lastmod>{d}</lastmod></url>" for u, d in urls)
    return f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{rows}</urlset>'

def rss(posts):
    items = "".join(f"""<item><title>{esc(p['title'])}</title><link>{SITE_URL}{p['url']}</link><guid>{SITE_URL}{p['url']}</guid>
<pubDate>{format_datetime(datetime.combine(p['date'], datetime.min.time()))}</pubDate><description>{esc(p['description'])}</description></item>""" for p in posts[:30])
    return f"""<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>{SITE_NAME}</title><link>{SITE_URL}/</link>
<description>{esc(TAGLINE)}</description>{items}</channel></rss>"""

# ---------- build ----------
def write(path, content):
    f = OUT / path.strip("/") / "index.html" if not path.endswith((".html", ".xml", ".txt")) else OUT / path.strip("/")
    f.parent.mkdir(parents=True, exist_ok=True); f.write_text(content, encoding="utf-8")

def main():
    print("Building DontBetSports...")
    posts = load_posts()
    if not posts: raise SystemExit("No published posts found in /posts.")
    if OUT.exists(): shutil.rmtree(OUT)
    OUT.mkdir(); shutil.copytree(STATIC, OUT / "static")
    today = date.today().isoformat()
    urls = [("/", posts[0]["updated"].isoformat()), ("/about/", today)]
    write("/", home(posts)); write("/about/", about()); write("/404.html", not_found(posts))
    write("/in-public/", in_public(posts)); urls.append(("/in-public/", today))
    write("/contact/", contact()); write("/contact/thanks/", contact_thanks()); write("/privacy/", privacy())
    urls += [("/contact/", today), ("/privacy/", today)]
    if (ROOT / "admin").exists(): shutil.copytree(ROOT / "admin", OUT / "admin")
    blurbs = {"News":"What happened and why it matters", "Takes":"Opinions from our writers", "Worth Watching":"The best games each week, ranked without a spread"}
    for c in CATEGORIES:
        path, html_ = listing(c, [p for p in posts if p["category"] == c], posts, blurbs.get(c, "")); write(path, html_); urls.append((path, today))
    for l in LEAGUES:
        path, html_ = listing(l, [p for p in posts if p["league"] == l], posts, f"All of our {l} coverage"); write(path, html_); urls.append((path, today))
    for p in posts:
        write(p["url"], article(p, posts)); urls.append((p["url"], p["updated"].isoformat()))
    write("/sitemap.xml", sitemap(urls)); write("/feed.xml", rss(posts))
    write("/robots.txt", f"User-agent: *\nAllow: /\nDisallow: /admin/\nSitemap: {SITE_URL}/sitemap.xml\n")
    print(f"Done: {len(posts)} posts, {len(urls)} pages in /public")

if __name__ == "__main__":
    main()
