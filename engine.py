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
    # One-time self-healing: if older runs stored single-letter domains
    # (a bug in an early GDELT path), re-classify them properly so the
    # topic sidebar shows correct names.
    try:
        conn = db()
        rows = conn.execute(
            "SELECT id, title FROM seen WHERE LENGTH(domain)=1"
        ).fetchall()
        fixed = 0
        for r in rows:
            new_topic = classify(r["title"]) or "World"
            conn.execute("UPDATE seen SET domain=? WHERE id=?",
                         (new_topic, r["id"]))
            fixed += 1
        if fixed:
            conn.commit()
        conn.close()
    except Exception:
        pass


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
    # GDELT augmentation — pull hotspot-targeted articles from 100k+ global sources.
    # Defined later in this file; safe if missing.
    gdelt_new = 0
    gdelt_outlets = 0
    try:
        g = collect_gdelt()
        if isinstance(g, dict):
            gdelt_new = g.get("new", 0)
            gdelt_outlets = g.get("outlets", 0)
    except Exception:
        pass
    return {"new": new_count + gdelt_new, "rss": new_count,
            "gdelt": gdelt_new, "gdelt_outlets": gdelt_outlets, "ai": use_ai}


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


# ===========================================================================
# MARITIME & SUPPLY-CHAIN INTELLIGENCE (H1 vertical slice)
# The "so what does it mean for me" layer: detect chokepoint events,
# map them to commodities -> sectors, and surface impact chains.
# ===========================================================================

CHOKEPOINTS = {
    "Strait of Hormuz": {
        "keywords": ["hormuz", "persian gulf"],
        "commodities": ["Crude oil", "LNG", "Petroleum"],
        "sectors": ["Energy", "Automotive", "Aviation", "Manufacturing"],
        "region": "MiddleEast", "lat": 26.6, "lon": 56.5,
        "chain": ["Tanker traffic disrupted", "Oil & LNG freight delayed",
                  "Energy prices spike", "Transport & manufacturing costs rise"],
    },
    "Red Sea / Bab el-Mandeb": {
        "keywords": ["red sea", "bab el-mandeb", "bab-el-mandeb", "houthi"],
        "commodities": ["Container freight", "Oil"],
        "sectors": ["Retail", "Electronics", "Automotive", "Energy"],
        "region": "MiddleEast", "lat": 12.6, "lon": 43.3,
        "chain": ["Carriers reroute via Cape of Good Hope", "+10-14 day transit",
                  "Freight & insurance costs rise", "Retail & electronics delays"],
    },
    "Suez Canal": {
        "keywords": ["suez"],
        "commodities": ["Container freight", "Oil"],
        "sectors": ["Retail", "Manufacturing", "Energy"],
        "region": "MiddleEast", "lat": 30.0, "lon": 32.5,
        "chain": ["Canal transit blocked", "Europe-Asia trade rerouted",
                  "Delivery delays", "Manufacturing input shortages"],
    },
    "Taiwan Strait": {
        "keywords": ["taiwan strait", "taiwan"],
        "commodities": ["Semiconductors", "Electronics"],
        "sectors": ["Semiconductor", "Electronics", "Automotive", "Defense"],
        "region": "China", "lat": 24.5, "lon": 119.5,
        "chain": ["Naval tension rises", "Chip exports threatened",
                  "Semiconductor supply risk", "Electronics & auto production hit"],
    },
    "South China Sea": {
        "keywords": ["south china sea", "spratly", "scarborough"],
        "commodities": ["Container freight", "LNG"],
        "sectors": ["Manufacturing", "Electronics", "Energy"],
        "region": "China", "lat": 13.0, "lon": 114.0,
        "chain": ["Naval friction", "Trade-route risk", "Rerouting & insurance up",
                  "Asia manufacturing exposure"],
    },
    "Panama Canal": {
        "keywords": ["panama canal"],
        "commodities": ["Container freight", "Grain", "LNG"],
        "sectors": ["Agriculture", "Retail", "Energy"],
        "region": "Americas", "lat": 9.1, "lon": -79.7,
        "chain": ["Transit slots limited", "US-Asia/Atlantic delays",
                  "Shipping costs rise", "Grain & retail supply pressure"],
    },
    "Black Sea": {
        "keywords": ["black sea", "odesa", "odessa", "bosphorus"],
        "commodities": ["Grain", "Fertilizer", "Oil"],
        "sectors": ["Agriculture", "Food", "Energy"],
        "region": "Russia", "lat": 43.0, "lon": 34.0,
        "chain": ["Export corridor disrupted", "Grain & fertilizer flow cut",
                  "Global food prices rise", "Food & agri sector pressure"],
    },
    "Strait of Malacca": {
        "keywords": ["malacca"],
        "commodities": ["Oil", "Container freight"],
        "sectors": ["Energy", "Manufacturing", "Electronics"],
        "region": "AsiaPacific", "lat": 2.5, "lon": 101.0,
        "chain": ["Chokepoint disruption", "Asia oil & trade flow hit",
                  "Rerouting costs", "Energy & manufacturing exposure"],
    },
}

_LVL = {"LOW": 0, "ELEVATED": 1, "HIGH": 2, "CRITICAL": 3}
_LVL_NAME = ["LOW", "ELEVATED", "HIGH", "CRITICAL"]


def supply_chain():
    """Detect chokepoint events, score risk, map to sector exposure + impact chains."""
    conn = db()
    rows = conn.execute(
        "SELECT title, summary, url, priority, added FROM seen "
        "ORDER BY added DESC LIMIT 600"
    ).fetchall()
    conn.close()

    chokepoints, sector_acc = [], {}
    for name, cfg in CHOKEPOINTS.items():
        matched = []
        for r in rows:
            text = (r["title"] + " " + (r["summary"] or "")).lower()
            if any(k in text for k in cfg["keywords"]):
                matched.append(r)
        cnt = len(matched)
        high = sum(1 for m in matched if m["priority"] == "HIGH")
        if high >= 2 or cnt >= 5:
            risk = "CRITICAL"
        elif high >= 1 or cnt >= 3:
            risk = "HIGH"
        elif cnt >= 1:
            risk = "ELEVATED"
        else:
            risk = "LOW"
        events = [{"title": m["title"], "url": m["url"], "priority": m["priority"],
                   "date": (m["added"] or "")[:10]} for m in matched[:5]]
        chokepoints.append({
            "name": name, "region": cfg["region"], "lat": cfg["lat"], "lon": cfg["lon"],
            "risk": risk, "event_count": cnt, "commodities": cfg["commodities"],
            "sectors": cfg["sectors"], "chain": cfg["chain"], "events": events,
        })
        if risk != "LOW":
            for s in cfg["sectors"]:
                cur = sector_acc.get(s, {"level": 0, "drivers": set()})
                cur["level"] = max(cur["level"], _LVL[risk])
                cur["drivers"].add(name)
                sector_acc[s] = cur

    chokepoints.sort(key=lambda x: (_LVL[x["risk"]], x["event_count"]), reverse=True)
    # also score conflict zones (post-hoc, simple loop)
    conflict_zones = []
    for name, cfg in CONFLICT_ZONES.items():
        matched = []
        for r in rows:
            text = (r["title"] + " " + (r["summary"] or "")).lower()
            if any(k in text for k in cfg["keywords"]):
                matched.append(r)
        cnt = len(matched)
        high = sum(1 for m in matched if m["priority"] == "HIGH")
        if high >= 2 or cnt >= 5:
            risk = "CRITICAL"
        elif high >= 1 or cnt >= 3:
            risk = "HIGH"
        elif cnt >= 1:
            risk = "ELEVATED"
        else:
            risk = "LOW"
        conflict_zones.append({
            "name": name, "region": cfg["region"], "lat": cfg["lat"], "lon": cfg["lon"],
            "risk": risk, "event_count": cnt, "sectors": cfg["sectors"],
        })
        if risk != "LOW":
            for s in cfg["sectors"]:
                cur = sector_acc.get(s, {"level": 0, "drivers": set()})
                cur["level"] = max(cur["level"], _LVL[risk])
                cur["drivers"].add(name)
                sector_acc[s] = cur
    conflict_zones.sort(key=lambda x: (_LVL[x["risk"]], x["event_count"]), reverse=True)
    sectors = [{"sector": s, "exposure": _LVL_NAME[v["level"]],
                "drivers": sorted(v["drivers"])}
               for s, v in sorted(sector_acc.items(), key=lambda kv: -kv[1]["level"])]
    active = sum(1 for c in chokepoints if c["risk"] != "LOW")
    return {"chokepoints": chokepoints, "conflict_zones": conflict_zones,
            "sectors": sectors, "active": active}


# ===========================================================================
# CONFLICT ZONES + REGION INTELLIGENCE + GLOBAL ALERTS + OBS-60 ASSISTANT
# ===========================================================================

CONFLICT_ZONES = {
    "Russia-Ukraine": {
        "keywords": ["ukraine", "kyiv", "ukrainian", "russian forces",
                     "putin", "zelensky", "kharkiv", "donbas"],
        "commodities": ["Grain", "Fertilizer", "Energy"],
        "sectors": ["Defense", "Energy", "Agriculture", "Food"],
        "region": "Russia", "lat": 48.5, "lon": 35.0,
        "chain": ["Active conflict", "Grain & energy export risk",
                  "Sanctions pressure", "Global commodity volatility"],
    },
    "Israel-Iran": {
        "keywords": ["israel", "iran", "gaza", "hezbollah", "hamas",
                     "tehran", "netanyahu", "houthi"],
        "commodities": ["Crude oil", "LNG"],
        "sectors": ["Defense", "Energy", "Aviation"],
        "region": "MiddleEast", "lat": 31.5, "lon": 35.5,
        "chain": ["Direct & proxy escalation", "Regional spillover",
                  "Oil shock risk", "Aviation rerouting"],
    },
    "Arctic Routes": {
        "keywords": ["arctic", "northern sea route", "greenland", "svalbard"],
        "commodities": ["LNG", "Oil"],
        "sectors": ["Energy", "Shipping", "Defense"],
        "region": "World", "lat": 78.0, "lon": 25.0,
        "chain": ["Resource competition", "Strategic positioning",
                  "Emerging shipping corridor", "Defense posture"],
    },
    "Indo-Pacific": {
        "keywords": ["indo-pacific", "quad", "aukus", "first island chain",
                     "philippines naval"],
        "commodities": ["Semiconductors", "Container freight"],
        "sectors": ["Defense", "Semiconductor", "Manufacturing"],
        "region": "AsiaPacific", "lat": 15.0, "lon": 125.0,
        "chain": ["Naval competition", "Trade-route risk",
                  "Tech & chip exposure", "Alliance dynamics"],
    },
}


def color_for_signals(n):
    """Spec alert-color logic: 0=GREEN, 1-2=YELLOW, 3-5=ORANGE, 5+=RED."""
    if n == 0:
        return "GREEN"
    if n <= 2:
        return "YELLOW"
    if n <= 5:
        return "ORANGE"
    return "RED"


def _all_regions():
    return {**CHOKEPOINTS, **CONFLICT_ZONES}


def _match(cfg, rows):
    out = []
    for r in rows:
        text = (r["title"] + " " + (r["summary"] or "")).lower()
        if any(k in text for k in cfg["keywords"]):
            out.append(r)
    return out


def region_intel(name):
    """Deep intel pack for a chokepoint or conflict zone."""
    cfg = _all_regions().get(name)
    if not cfg:
        return {"error": "unknown_region", "name": name}
    conn = db()
    rows = conn.execute(
        "SELECT title,summary,url,priority,added,source FROM seen "
        "ORDER BY added DESC LIMIT 800"
    ).fetchall()
    conn.close()
    matched = _match(cfg, rows)
    cnt = len(matched)
    high = sum(1 for m in matched if m["priority"] == "HIGH")
    if high >= 2 or cnt >= 6:
        level = "CRITICAL"
    elif high >= 1 or cnt >= 3:
        level = "HIGH"
    elif cnt >= 1:
        level = "ELEVATED"
    else:
        level = "LOW"
    prob = min(92, 5 + cnt * 4 + high * 12)
    signals = [{"title": m["title"], "url": m["url"], "priority": m["priority"],
                "date": (m["added"] or "")[:10], "source": m["source"] or ""}
               for m in matched[:12]]
    return {
        "name": name,
        "type": "chokepoint" if name in CHOKEPOINTS else "conflict_zone",
        "signal_count": cnt, "high_count": high,
        "color": color_for_signals(cnt), "level": level,
        "escalation_probability": prob,
        "chain": cfg.get("chain", []),
        "commodities": cfg.get("commodities", []),
        "sectors": cfg.get("sectors", []),
        "region": cfg.get("region", ""),
        "lat": cfg.get("lat"), "lon": cfg.get("lon"),
        "signals": signals,
        "ai_summary": _compose_summary(name, cfg, cnt, high, matched),
    }


def _compose_summary(name, cfg, cnt, high, matched):
    """Data-driven tactical summary (rule-based; LLM-upgradeable later)."""
    if cnt == 0:
        return f"No current threat detected in {name}. Monitoring continues."
    blob = " ".join((m["title"] + " " + (m["summary"] or "")).lower()
                    for m in matched[:12])
    themes = []
    if any(k in blob for k in ["strike", "attack", "missile", "drone",
                               "naval", "military", "troops"]):
        themes.append("military activity")
    if any(k in blob for k in ["tanker", "shipping", "freight", "reroute",
                               "route", "insurance"]):
        themes.append("shipping disruption")
    if any(k in blob for k in ["oil", "crude", "lng", "gas", "energy",
                               "refinery"]):
        themes.append("energy market pressure")
    if any(k in blob for k in ["grain", "food", "fertilizer", "wheat"]):
        themes.append("food/agri impact")
    if not themes:
        themes = ["tension signals"]
    severity = "Critical" if high >= 2 else ("Elevated" if high >= 1 else "Moderate")
    sect = ", ".join(cfg.get("sectors", [])[:3]) or "regional exposure"
    return (f"{severity} {' & '.join(themes[:2])} detected in {name}. "
            f"Sectors at exposure: {sect}.")


def global_alerts():
    """Ribbon data: counts + highest-risk hotspot across chokepoints + conflict zones."""
    hotspots = []
    for nm in list(CHOKEPOINTS.keys()) + list(CONFLICT_ZONES.keys()):
        ri = region_intel(nm)
        hotspots.append({"name": nm, "level": ri["level"],
                         "count": ri["signal_count"]})
    crit = sum(1 for h in hotspots if h["level"] == "CRITICAL")
    high = sum(1 for h in hotspots if h["level"] == "HIGH")
    rank = {"CRITICAL": 3, "HIGH": 2, "ELEVATED": 1, "LOW": 0}
    hotspots.sort(key=lambda h: (rank[h["level"]], h["count"]), reverse=True)
    top = hotspots[0] if hotspots and hotspots[0]["level"] != "LOW" else None
    if top:
        ribbon = (f"{crit} CRITICAL · {high} HIGH · "
                  f"Highest: {top['name']} ({top['level']})")
    else:
        ribbon = "All monitored hotspots nominal"
    return {"critical": crit, "high": high,
            "highest": top["name"] if top else None,
            "highest_level": top["level"] if top else "LOW",
            "ribbon": ribbon}


# ===========================================================================
# OBS-60: rule-based tactical assistant (LLM-upgradeable; see comment below)
# ===========================================================================
#
# This responds using REAL data from the OBSIDIAN engine. To upgrade to a
# true LLM later, replace the body of obs60() with a call to your LLM of
# choice (Ollama local, or Anthropic Claude API), passing the live engine
# context (dashboard(), supply_chain(), region_intel()) as system context.
# The /api/obs60 endpoint signature does not change.

_ALIAS = {
    "hormuz": "Strait of Hormuz", "red sea": "Red Sea / Bab el-Mandeb",
    "bab": "Red Sea / Bab el-Mandeb", "suez": "Suez Canal",
    "taiwan": "Taiwan Strait", "panama": "Panama Canal",
    "malacca": "Strait of Malacca", "black sea": "Black Sea",
    "south china": "South China Sea", "ukraine": "Russia-Ukraine",
    "russia-ukraine": "Russia-Ukraine", "iran": "Israel-Iran",
    "israel": "Israel-Iran", "gaza": "Israel-Iran",
    "arctic": "Arctic Routes", "indo-pacific": "Indo-Pacific",
    "indopacific": "Indo-Pacific",
}


def obs60(query):
    """Founder-level tactical intelligence assistant. Addresses user as 'Eagle'."""
    from datetime import datetime
    q = (query or "").strip()
    ql = q.lower()
    if not q:
        return {"role": "OBS-60", "text": "Standing by, Eagle. Provide your query."}

    # greeting
    greetings = ["hi", "hello", "hey", "good morning", "good afternoon",
                 "good evening", "namaste", "salaam", "kya haal"]
    if any(ql == g or ql.startswith(g + " ") or ql.startswith(g + ",")
           or ql == g + "!" for g in greetings):
        sc = supply_chain()
        crit_n = sum(1 for c in sc["chokepoints"] if c["risk"] == "CRITICAL")
        high_n = sum(1 for c in sc["chokepoints"] if c["risk"] == "HIGH")
        top = sc["chokepoints"][0] if sc["chokepoints"] else None
        h = datetime.now().hour
        greet = ("Good morning" if h < 12 else
                 ("Good afternoon" if h < 17 else "Good evening"))
        if crit_n and top:
            return {"role": "OBS-60",
                    "text": f"{greet}, Eagle. {crit_n} critical chokepoint"
                            f"{'s' if crit_n > 1 else ''} active — highest: "
                            f"{top['name']}. Awaiting your query."}
        if high_n and top:
            return {"role": "OBS-60",
                    "text": f"{greet}, Eagle. {high_n} elevated chokepoint"
                            f"{'s' if high_n > 1 else ''} under watch — top "
                            f"concern: {top['name']}."}
        return {"role": "OBS-60",
                "text": f"{greet}, Eagle. All monitored chokepoints nominal. "
                        f"Awaiting your query."}

    # global brief / status
    if any(k in ql for k in ["global brief", "global status", "brief",
                             "situation report", "overview", "status",
                             "kya haal", "kya chal"]):
        # skip if a region was also mentioned (let region path handle)
        if not any(k in ql for k in _ALIAS):
            sc = supply_chain()
            d = dashboard()
            crit_n = sum(1 for c in sc["chokepoints"] if c["risk"] == "CRITICAL")
            high_n = sum(1 for c in sc["chokepoints"] if c["risk"] == "HIGH")
            top = sc["chokepoints"][0] if sc["chokepoints"] else None
            sect_crit = [s["sector"] for s in sc["sectors"]
                         if s["exposure"] == "CRITICAL"][:3]
            parts = [f"Eagle, global picture: {d['stats']['high']} high-priority "
                     f"signals across {d['stats']['topics']} sectors."]
            if crit_n and top:
                parts.append(f"{crit_n} chokepoint"
                             f"{'s' if crit_n > 1 else ''} at CRITICAL — "
                             f"top: {top['name']}.")
            elif high_n and top:
                parts.append(f"{high_n} chokepoint"
                             f"{'s' if high_n > 1 else ''} elevated — "
                             f"watch: {top['name']}.")
            if sect_crit:
                parts.append(f"Critical sector exposure: "
                             f"{', '.join(sect_crit)}.")
            return {"role": "OBS-60", "text": " ".join(parts)}

    # region detection
    hit = None
    for k, v in _ALIAS.items():
        if k in ql:
            hit = v
            break
    if not hit:
        for r in _all_regions().keys():
            if r.lower() in ql:
                hit = r
                break
    if hit:
        ri = region_intel(hit)
        if ri["signal_count"] == 0:
            return {"role": "OBS-60",
                    "text": f"Eagle, {hit} region nominal at present. No active "
                            f"signals detected. Monitoring continues."}
        parts = [f"Eagle, {hit}:"]
        parts.append(f"Risk level {ri['level']}, escalation probability "
                     f"{ri['escalation_probability']}%.")
        parts.append(f"{ri['signal_count']} signal"
                     f"{'s' if ri['signal_count'] > 1 else ''}, "
                     f"{ri['high_count']} high-priority.")
        if ri["sectors"]:
            parts.append(f"Sectors exposed: {', '.join(ri['sectors'][:3])}.")
        parts.append(ri["ai_summary"])
        return {"role": "OBS-60", "text": " ".join(parts)}

    # capabilities
    if any(k in ql for k in ["help", "what can you", "capabilities", "kya kar"]):
        return {"role": "OBS-60",
                "text": "Eagle, I monitor 12 hotspots — 8 maritime chokepoints "
                        "and 4 conflict zones. Ask about any region (Hormuz, "
                        "Red Sea, Taiwan, Ukraine, Iran, Arctic, Indo-Pacific), "
                        "request a 'global brief', or query sector exposure."}

    # co-founder mention
    if "rudra" in ql:
        return {"role": "OBS-60",
                "text": "RUDRA acknowledged. Co-founder access noted. "
                        "Awaiting tactical query."}

    return {"role": "OBS-60",
            "text": "Eagle, query not recognized. Try a region name "
                    "(e.g., 'Hormuz status'), 'global brief', or 'help'."}


# ===========================================================================
# GDELT — Global Database of Events, Language, and Tone (FREE, ~100k sources)
# This single integration moves OBSIDIAN from "5 RSS feeds" to "monitoring
# 100,000+ global news sources every 15 min." No API key required.
# Reference: https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/
# ===========================================================================

GDELT_DOC_URL = "https://api.gdeltproject.org/api/v2/doc/doc"


def _gdelt_query(name, cfg):
    """Build a GDELT DOC query from a hotspot config's keywords."""
    kws = cfg.get("keywords", [])[:3]
    if not kws:
        return None
    quoted = [f'"{k}"' if " " in k else k for k in kws]
    return "(" + " OR ".join(quoted) + ")"


def collect_gdelt(hotspots=None, max_per_hotspot=12):
    """
    Pull hotspot-targeted articles from GDELT's DOC 2.0 API.
    Each chokepoint and conflict zone gets a recent-articles query.
    Articles flow into the same `seen` table → automatically classified,
    scored, mapped to regions, and surfaced everywhere.
    Returns count of NEW articles ingested.
    """
    targets = hotspots if hotspots else (
        list(CHOKEPOINTS.items()) + list(CONFLICT_ZONES.items())
    )
    conn = db()
    new_count = 0
    sources_seen = set()

    for name, cfg in targets:
        q = _gdelt_query(name, cfg)
        if not q:
            continue
        params = {
            "query": q,
            "mode": "artlist",
            "format": "json",
            "maxrecords": str(max_per_hotspot),
            "sort": "datedesc",
            "timespan": "48h",
        }
        try:
            r = requests.get(GDELT_DOC_URL, params=params, timeout=15,
                             headers={"User-Agent": "OBSIDIAN/1.5"})
            if r.status_code != 200:
                continue
            try:
                data = r.json()
            except Exception:
                continue
        except Exception:
            continue

        for art in data.get("articles", []) or []:
            title = (art.get("title") or "").strip()
            url = (art.get("url") or "").strip()
            outlet = (art.get("domain") or "gdelt").strip()
            if not title or not url:
                continue
            rid = url_id(url)
            if conn.execute("SELECT 1 FROM seen WHERE id=?", (rid,)).fetchone():
                continue
            text = title
            topic = classify(text)            # classify() returns a STRING
            if not topic:
                topic = cfg.get("region", "World")
            priority, score = score_priority(text)
            added = datetime.now(timezone.utc).isoformat()
            try:
                conn.execute(
                    "INSERT INTO seen "
                    "(id,title,domain,summary,url,source,added,priority,score) "
                    "VALUES (?,?,?,?,?,?,?,?,?)",
                    (rid, title, topic, title, url, outlet, added,
                     priority, score)
                )
                new_count += 1
                sources_seen.add(outlet)
            except Exception:
                pass

    conn.commit()
    conn.close()
    return {"new": new_count, "outlets": len(sources_seen)}
