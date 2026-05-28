# 🖥️ OBSIDIAN Command Center — Full-Stack Edition

This is the **web dashboard** version of your system. Same brain as before
(collect → sort → prioritise), but now you view everything in a dark tactical
interface in your browser instead of reading Notepad files.

It's a real **full stack**:
- **Frontend** — the dashboard you see (a single web page)
- **Backend** — a small Flask server that feeds it data (`app.py`)
- **Engine** — the collection + sorting + scoring logic (`engine.py`)
- **Database** — your stories, stored in `obsidian.db`

Still **no Docker, no Node, no build step.** Just Python + one extra install.

---

## ▶️ How to run it

> **Windows:**
1. Double-click **`setup.bat`** — installs the web framework (one time only).
2. Double-click **`start_dashboard.bat`** — starts the server. Your browser
   opens to the dashboard automatically.
3. In the dashboard, click **⟳ COLLECT NOW** (top-right) to pull the news.

> **Mac/Linux:** `bash setup.sh` once, then `bash start_dashboard.sh`.

⚠️ **Keep the black server window open** while you use the dashboard. Closing
it stops the server (that's how you shut it down when you're done).

The dashboard lives at **http://127.0.0.1:5000** — bookmark it if you like.
`127.0.0.1` just means "this computer" — nothing is exposed to the internet.

---

## 🎛️ What you can do in the dashboard

- **⟳ COLLECT NOW** — pull fresh news from your feeds (top-right button)
- **Topics sidebar** — click any topic (India, China, Middle East…) to filter
- **Priority buttons** — ALL / HIGH / MED / LOW
- **Search box** — type a word to filter instantly
- **Story cards** — colour-coded left edge (red = HIGH, amber = MEDIUM).
  Click any headline to open the full article in a new tab.
- **Stat ribbon** — today's count, HIGH-priority count, active topics, archive total

---

## 🔁 Keep your old history (optional)

If you want the stories you already collected in the CLI version to appear
here, copy your old **`obsidian.db`** file into this folder (replace the empty
one). Everything will show up immediately. If you skip this, just hit
COLLECT NOW and it builds fresh.

---

## 🤖 AI summaries (optional, same as before)

The status pill at the top shows **AI: OFF** or **AI: ON**. If you install
Ollama (ollama.com) and `ollama pull llama3.1:8b`, the badge flips to ON and
new collections get AI-written summaries automatically — no code change.

---

## 🆘 Quick fixes

| Problem | Fix |
|---|---|
| `'python' is not recognized` | Reinstall Python, tick "Add Python to PATH". |
| Browser didn't open | Go to **http://127.0.0.1:5000** manually. |
| "ModuleNotFoundError: flask" | Run `setup.bat` first. |
| Page won't load | Make sure the black server window is still open. |
| Port 5000 busy | Close other apps using it, or edit the port at the bottom of `app.py`. |

---

## 🗂️ File map

```
obsidian-fullstack/
├── start_dashboard.bat   <- double-click to run
├── setup.bat             <- one-time install
├── app.py                <- backend server + API
├── engine.py             <- collection / sorting / scoring / database
├── feeds.txt             <- your news sources
├── requirements.txt
└── web/
    └── index.html        <- the command-center dashboard
```

Your CLI tools still work too — this is an addition, not a replacement. Run
whichever you prefer.
