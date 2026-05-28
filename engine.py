"""
OBSIDIAN — engine.

The same proven logic from the CLI edition, repackaged as importable functions
so the web backend (app.py) can call it. Collection, topic sorting, priority
scoring, storage, querying, stats. AI summaries stay optional (Ollama if present).
"""
import hashlib
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import feedparser
import requests

BASE = Path(__file__).resolve().parent
VAULT = BASE / "vault"
INTEL_DIR = VAULT / "Intelligence"
DB_PATH = BASE / "obsidian.db"
FEEDS_FILE = BASE / "feeds.txt"

OLLAMA_HOST = "http://localhost:11434"
OLLAMA_MODEL = "llama3.1:8b"
MAX_PER_FEED = 20

DEFAULT_FEEDS = [
    "https://www.thehindu.com/news/national/feeder/default.rss",
    "https://rss.dw.com/rdf/rss-en-all",
    "http://feeds.bbci.co.uk/news/world/rss.xml",
    "https://www.aljazeera.com/xml/rss/all.xml",
    "https://www.theguardian.com/world/rss",
]

DOMAIN_KEYWORDS = {
    "India": ["india", "indian", "modi", "delhi", "mumbai", "bengaluru", "kolkata",
              "chennai", "rupee", "aadhaar", "uidai", "lok sabha", "rajya sabha",
              "kashmir", "jammu", "gujarat", "punjab", "sensex", "nifty", "rbi"],
    "China": ["china", "chinese", "beijing", "shanghai", "xi jinping", "taiwan",
              "taipei", "hong kong", "yuan", "renminbi", "huawei", "alibaba"],
    "Russia": ["russia", "russian", "putin", "moscow", "kremlin", "ukraine",
               "ukrainian", "kyiv", "kiev", "zelensky", "donbas", "crimea", "wagner"],
    "MiddleEast": ["israel", "israeli", "gaza", "palestin", "hamas", "hezbollah",
                   "iran", "iranian", "tehran", "saudi", "riyadh", "syria", "syrian",
                   "lebanon", "beirut", "yemen", "houthi", "iraq", "qatar", "uae",
                   "dubai", "egypt", "cairo", "netanyahu", "idf", "west bank"],
    "UK": ["britain", "british", "united kingdom", "london", "downing street",
           "westminster", "starmer", "scotland", "wales", "sterling"],
    "US": ["united states", "u.s.", "us forces", "us military", "washington",
           "white house", "pentagon", "biden", "trump", "rubio", "congress",
           "senate", "wall street", "federal reserve", "american"],
    "Europe": ["europe", "european", "brussels", "germany", "german", "berlin",
               "france", "french", "paris", "poland", "polish", "warsaw", "italy",
               "rome", "spain", "madrid", "netherlands", "nato", "macron", "scholz",
               "von der leyen", "greece", "sweden", "finland"],
    "AsiaPacific": ["japan", "japanese", "tokyo", "korea", "korean", "seoul",
                    "pyongyang", "north korea", "south korea", "australia",
                    "canberra", "indonesia", "philippines", "vietnam", "thailand",
                    "singapore", "malaysia", "pakistan", "islamabad", "bangladesh",
                    "sri lanka", "nepal", "myanmar", "asean"],
    "Americas": ["brazil", "mexico", "mexican", "argentina", "venezuela", "caracas",
                 "colombia", "chile", "peru", "canada", "canadian", "ottawa", "cuba",
                 "latin america"],
    "Africa": ["africa", "african", "nigeria", "kenya", "ethiopia", "south africa",
               "sudan", "congo", "sahel", "mali", "somalia", "libya"],
    "AI_Tech": ["artificial intelligence", " ai ", "a.i.", "openai", "chatgpt",
                "machine learning", "semiconductor", "microchip", "nvidia", "tsmc",
                "google", "microsoft", "quantum", "data center", "algorithm"],
    "Cyber": ["cyberattack", "cyber", "hacking", "hacker", "ransomware", "malware",
              "data breach", "phishing", "espionage", "surveillance"],
    "Defense": ["military", "defence", "defense", "army", "navy", "air force",
                "missile", "warship", "fighter jet", "drone", "weapon", "arms",
                "troops", "soldier", "warhead"],
    "Energy": ["oil", "crude", "petroleum", "natural gas", "opec", "pipeline",
               "nuclear power", "renewable", "solar power", "wind power", "lng",
               "power grid", "coal"],
    "Economy": ["economy", "economic", "inflation", "recession", "gdp",
                "interest rate", "central bank", "stock market", "trade war",
                "tariff", "imf", "world bank", "unemployment"],
    "Climate": ["climate", "global warming", "emission", "carbon", "greenhouse",
                "drought", "flood", "wildfire", "heatwave", "glacier"],
    "Migration": ["migrant", "migration", "refugee", "asylum", "immigration",
                  "deportation", "displaced"],
}

PRIORITY_KEYWORDS = {
    3: ["war", "attack", "strike", "killed", "missile", "invasion", "nuclear",
        "coup", "terror", "airstrike", "escalat", "cyberattack", "breach"],
    2: ["military", "border", "defence", "defense", "tension", "dispute", "conflict",
        "deploy", "tariff", "sanction", "protest", "threat", "crisis", "weapon", "clash"],
    1: ["summit", "talks", "election", "diplomat", "agreement", "deal", "trade",
        "meeting", "policy", "treaty"],
}


# --- helpers ---------------------------------------------------------------
def url_id(url):
    return hashlib.sha256(url.encode()).hexdigest()[:32]


def clean(text):
    return " ".join(re.sub("<[^<]+?>", "", text or "").split())


def classify(text):
    low = " " + (text or "").lower() + " "
    best, best_hits = "World", 0
    for domain, words in DOMAIN_KEYWORDS.items():
        hits = sum(low.count(w) for w in words)
        if hits > best_hits:
            best, best_hits = domain, hits
    return best


def score_priority(text):
    low = (text or "").lower()
    score = sum(weight for weight, words in PRIORITY_KEYWORDS.items()
                for w in words if w in low)
    if score >= 5:
        return "HIGH", score
    if score >= 2:
        return "MEDIUM", score
    return "LOW", score


def ollama_up():
    try:
        requests.get(f"{OLLAMA_HOST}/api/tags", timeout=2)
        return True
    except Exception:
        return False


def quick_summary(text):
    text = clean(text)
    if not text:
        return "(no description provided by the source)"
    parts = re.split(r"(?<=[.!?])\s+", text)
    return " ".join(parts[:2]).strip()[:400]


def ai_summary(title, text):
    try:
        prompt = ("Summarise this news item in 2 short, factual sentences. "
                  "No opinions.\n\n" f"TITLE: {title}\n\nTEXT: {clean(text)[:2500]}")
        r = requests.post(
            f"{OLLAMA_HOST}/api/generate",
            json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False,
                  "options": {"temperature": 0.2}},
            timeout=120,
        )
        r.raise_for_status()
        return r.json().get("response", "").strip() or quick_summary(text)
    except Exception:
        return quick_summary(text)


# --- storage ---------------------------------------------------------------
def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE IF NOT EXISTS seen "
        "(id TEXT PRIMARY KEY, title TEXT, domain TEXT, summary TEXT, "
        " url TEXT, source TEXT, added TEXT, priority TEXT DEFAULT 'LOW', "
        " score INTEGER DEFAULT 0)"
    )
    cols = [r[1] for r in conn.execute("PRAGMA table_info(seen)").fetchall()]
    for col, ddl in (("priority", "TEXT DEFAULT 'LOW'"), ("score", "INTEGER DEFAULT 0"),
                     ("source", "TEXT DEFAULT ''")):
        if col not in cols:
            conn.execute(f"ALTER TABLE seen ADD COLUMN {col} {ddl}")
    conn.commit()
    return conn


def ensure_setup():
    INTEL_DIR.mkdir(parents=True, exist_ok=True)
    if not FEEDS_FILE.exists():
        FEEDS_FILE.write_text(
            "# OBSIDIAN feeds — one web address per line.\n\n"
            + "\n".join(DEFAULT_FEEDS) + "\n", encoding="utf-8")


def load_feeds():
    if not FEEDS_FILE.exists():
        ensure_setup()
    lines = FEEDS_FILE.read_text(encoding="utf-8").splitlines()
    return [ln.strip() for ln in lines if ln.strip() and not ln.strip().startswith("#")]


def write_note(rec):
    safe = re.sub(r"[^\w\- ]", "", rec["title"])[:70].strip().replace(" ", "_") or "untitled"
    fname = f"{rec['added'][:10]}_{rec['domain']}_{safe}.md"
    note = (f"---\ntitle: \"{rec['title']}\"\ntopic: {rec['domain']}\n"
            f"priority: {rec['priority']}\ndate: {rec['added']}\nurl: {rec['url']}\n"
            f"tags: [intel, {rec['domain']}, {rec['priority']}]\n---\n\n"
            f"# {rec['title']}\n\n**Priority:** {rec['priority']}\n\n"
            f"{rec['summary']}\n\n[Read the full story]({rec['url']})\n")
    (INTEL_DIR / fname).write_text(note, encoding="utf-8")


# --- core operations the API calls -----------------------------------------
def collect():
    """Fetch all feeds, store new items, write notes. Returns a summary dict."""
    ensure_setup()
    feeds = load_feeds()
    use_ai = ollama_up()
    conn = db()
    new_count = 0
    for url in feeds:
        try:
            parsed = feedparser.parse(url)
            source = parsed.feed.get("title", url)
            for entry in parsed.entries[:MAX_PER_FEED]:
                link = entry.get("link")
                if not link:
                    continue
                the_id = url_id(link)
                if conn.execute("SELECT 1 FROM seen WHERE id=?", (the_id,)).fetchone():
                    continue
                title = clean(entry.get("title", "")) or "(untitled)"
                raw = entry.get("summary", "")
                blob = title + " " + raw
                priority, score = score_priority(blob)
                rec = {
                    "id": the_id, "title": title, "domain": classify(blob),
                    "summary": ai_summary(title, raw) if use_ai else quick_summary(raw),
                    "url": link, "source": source,
                    "added": datetime.now(timezone.utc).isoformat(),
                    "priority": priority, "score": score,
                }
                conn.execute(
                    "INSERT OR IGNORE INTO seen "
                    "(id,title,domain,summary,url,source,added,priority,score) "
                    "VALUES (?,?,?,?,?,?,?,?,?)",
                    (rec["id"], rec["title"], rec["domain"], rec["summary"], rec["url"],
                     rec["source"], rec["added"], rec["priority"], rec["score"]),
                )
                write_note(rec)
                new_count += 1
            conn.commit()
        except Exception:
            continue
    conn.close()
    return {"new": new_count, "ai": use_ai}


def query_stories(topic=None, priority=None, q=None, limit=200):
    conn = db()
    sql = "SELECT title,domain,summary,url,source,added,priority,score FROM seen WHERE 1=1"
    params = []
    if topic and topic != "ALL":
        sql += " AND domain=?"
        params.append(topic)
    if priority and priority != "ALL":
        sql += " AND priority=?"
        params.append(priority)
    if q:
        sql += " AND (lower(title) LIKE ? OR lower(summary) LIKE ?)"
        params += [f"%{q.lower()}%", f"%{q.lower()}%"]
    sql += " ORDER BY added DESC, score DESC LIMIT ?"
    params.append(limit)
    rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
    conn.close()
    return rows


def stats():
    conn = db()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    total = conn.execute("SELECT COUNT(*) FROM seen").fetchone()[0]
    today_count = conn.execute("SELECT COUNT(*) FROM seen WHERE added LIKE ?",
                               (today + "%",)).fetchone()[0]
    high = conn.execute("SELECT COUNT(*) FROM seen WHERE priority='HIGH'").fetchone()[0]
    topics = [{"topic": r["domain"], "count": r["c"]} for r in conn.execute(
        "SELECT domain, COUNT(*) c FROM seen GROUP BY domain ORDER BY c DESC")]
    conn.close()
    return {"total": total, "today": today_count, "high": high,
            "topics": topics, "ai": ollama_up()}


def weekly():
    conn = db()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    rows = conn.execute(
        "SELECT title,domain,priority,url,added FROM seen WHERE added>=? "
        "ORDER BY added DESC", (cutoff,)).fetchall()
    conn.close()
    by_topic, by_day = {}, {}
    highs = []
    for r in rows:
        by_topic[r["domain"]] = by_topic.get(r["domain"], 0) + 1
        by_day[r["added"][:10]] = by_day.get(r["added"][:10], 0) + 1
        if r["priority"] == "HIGH":
            highs.append({"title": r["title"], "domain": r["domain"],
                          "date": r["added"][:10], "url": r["url"]})
    return {"total": len(rows),
            "topics": sorted(by_topic.items(), key=lambda x: -x[1]),
            "busiest": max(by_day, key=by_day.get) if by_day else None,
            "highs": highs}


# ===========================================================================
# Rich dashboard data — powers the holographic command-center panels.
# Everything below is computed from YOUR real collected stories.
# ===========================================================================

# approximate world-map positions (x%, y%) for the global intel map
REGION_XY = {
    "India": (69, 56), "China": (78, 46), "Russia": (66, 30),
    "MiddleEast": (60, 52), "Europe": (51, 36), "UK": (47, 31),
    "US": (22, 43), "AsiaPacific": (85, 58), "Americas": (28, 66),
    "Africa": (53, 64), "World": (50, 50),
}

_POS_WORDS = ["peace", "deal", "agreement", "growth", "win", "recovery", "aid",
              "cooperation", "breakthrough", "ceasefire", "rescue", "support",
              "progress", "boost", "gains", "stable", "talks", "summit"]
_NEG_WORDS = ["war", "attack", "killed", "crisis", "strike", "threat", "conflict",
              "dead", "collapse", "sanction", "protest", "fear", "recession",
              "disaster", "tension", "clash", "missile", "violence", "kill"]


def _day_counts(conn, days=7):
    out = []
    for d in range(days - 1, -1, -1):
        day = (datetime.now(timezone.utc) - timedelta(days=d)).strftime("%Y-%m-%d")
        c = conn.execute("SELECT COUNT(*) FROM seen WHERE added LIKE ?",
                         (day + "%",)).fetchone()[0]
        out.append({"day": day[5:], "count": c})
    return out


def dashboard():
    conn = db()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    yday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")

    total = conn.execute("SELECT COUNT(*) FROM seen").fetchone()[0]
    today_n = conn.execute("SELECT COUNT(*) FROM seen WHERE added LIKE ?", (today + "%",)).fetchone()[0]
    yday_n = conn.execute("SELECT COUNT(*) FROM seen WHERE added LIKE ?", (yday + "%",)).fetchone()[0]
    high = conn.execute("SELECT COUNT(*) FROM seen WHERE priority='HIGH'").fetchone()[0]
    high_today = conn.execute("SELECT COUNT(*) FROM seen WHERE priority='HIGH' AND added LIKE ?", (today + "%",)).fetchone()[0]

    topics = [{"topic": r["domain"], "count": r["c"]} for r in conn.execute(
        "SELECT domain, COUNT(*) c FROM seen GROUP BY domain ORDER BY c DESC")]

    # source distribution (top 6)
    src_rows = conn.execute(
        "SELECT source, COUNT(*) c FROM seen GROUP BY source ORDER BY c DESC LIMIT 6").fetchall()
    s_total = sum(r["c"] for r in src_rows) or 1
    sources = [{"source": (r["source"] or "Unknown")[:22], "count": r["c"],
                "pct": round(r["c"] * 100 / s_total)} for r in src_rows]

    activity = _day_counts(conn, 7)

    # priority by region (top 6 sectors)
    regions = []
    for r in conn.execute("SELECT domain, COUNT(*) c FROM seen GROUP BY domain ORDER BY c DESC LIMIT 6"):
        dom = r["domain"]
        h = conn.execute("SELECT COUNT(*) FROM seen WHERE domain=? AND priority='HIGH'", (dom,)).fetchone()[0]
        level = "HIGH" if h >= 2 else ("MEDIUM" if (h >= 1 or r["c"] >= 10) else "LOW")
        regions.append({"region": dom, "level": level, "high": h, "total": r["c"]})

    # map points
    mappts = []
    for t in topics:
        xy = REGION_XY.get(t["topic"])
        if not xy:
            continue
        hot = any(rg["region"] == t["topic"] and rg["level"] == "HIGH" for rg in regions)
        mappts.append({"region": t["topic"], "x": xy[0], "y": xy[1],
                       "count": t["count"], "hot": hot})

    # sentiment from recent 120 titles
    titles = [r["title"] for r in conn.execute(
        "SELECT title FROM seen ORDER BY added DESC LIMIT 120")]
    pos = neg = 0
    for t in titles:
        low = (t or "").lower()
        pos += sum(1 for w in _POS_WORDS if w in low)
        neg += sum(1 for w in _NEG_WORDS if w in low)
    denom = pos + neg
    score = int(round((pos - neg) * 100 / denom)) if denom else 0
    label = "Positive" if score > 12 else ("Negative" if score < -12 else "Neutral")

    # data-driven AI insights
    insights = []
    hot_regions = [rg for rg in regions if rg["level"] == "HIGH"]
    if hot_regions:
        top = hot_regions[0]
        insights.append(f"Elevated activity in {top['region']} — {top['high']} high-priority reports flagged.")
    if len(activity) >= 2 and activity[-1]["count"] > activity[-2]["count"]:
        insights.append(f"Intel volume rising: {activity[-1]['count']} today vs {activity[-2]['count']} prior day.")
    if sources:
        insights.append(f"Primary source: {sources[0]['source']} ({sources[0]['pct']}% of feed).")
    if score < -12:
        insights.append("Overall signal tone is tense — monitor escalation indicators.")
    elif score > 12:
        insights.append("Overall signal tone is constructive across tracked sectors.")
    if not insights:
        insights.append("System nominal. Run an uplink to refresh intelligence.")

    conn.close()
    return {
        "stats": {"total": total, "today": today_n, "high": high,
                  "topics": len(topics), "high_today": high_today,
                  "today_delta": today_n - yday_n},
        "topics": topics, "sources": sources, "activity": activity,
        "regions": regions, "map": mappts,
        "sentiment": {"score": score, "label": label},
        "insights": insights[:4], "ai": ollama_up(),
    }
