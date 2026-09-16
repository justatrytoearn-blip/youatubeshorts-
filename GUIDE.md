# The Complete Guide — Automated YouTube Shorts Money Pipeline

This guide takes you from **zero** (nothing installed, no accounts) to **fully automated daily uploads**. Every step has exact commands and exactly where to click. No prior knowledge assumed.

---

## Table of Contents

1. [What this pipeline does (30-second overview)](#1-what-this-pipeline-does)
2. [What you need before starting](#2-what-you-need-before-starting)
3. [Installation (one command)](#3-installation)
4. [Get your free API keys (10 minutes, with pictures-in-words)](#4-get-your-free-api-keys)
5. [Make your first video (10 minutes)](#5-make-your-first-video)
6. [Turn on daily automatic uploads](#6-turn-on-daily-automatic-uploads)
7. [Write your own video scripts (content anatomy)](#7-write-your-own-video-scripts)
8. [YouTube channel setup for Shorts monetization](#8-youtube-channel-setup)
9. [The money part — realistic expectations](#9-the-money-part)
10. [Troubleshooting (every known error)](#10-troubleshooting)
11. [Command cheat sheet + file map](#11-command-cheat-sheet--file-map)

---

## 1. What this pipeline does

Every day, automatically:

```
 content/dayX_*.json        (your 7 pre-written viral scripts)
        │
        ▼
 [1] tts_engine.py          free neural voice reads the narration (edge-tts)
        │
        ▼
 [2] pexels_assets.py       fetches a unique vertical stock clip per scene (Pexels)
        │                   + optional background music (Pixabay)
        ▼
 [3] render.py              FFmpeg stitches everything: 1080x1920 video,
        │                   timed to narration, burned captions, music bed
        ▼
 [4] upload.py              uploads to YouTube as a public Short (Data API v3)
        │
        ▼
 output/videos/dayX_final.mp4   + your channel gets a new Short
```

You write nothing daily, edit nothing daily. You review videos whenever you want (optional) and the machine posts on schedule.

---

## 2. What you need before starting

| Need | Cost | Where |
|---|---|---|
| A computer/phone that stays on at upload time | $0 | Linux, macOS, Windows (WSL), or Android (Termux) all work |
| Python 3.10+ | $0 | preinstalled on most systems |
| FFmpeg | $0 | installed by setup script |
| Pexels API key | $0 free | pexels.com/api |
| Google Cloud project (YouTube upload) | $0 free | console.cloud.google.com |
| A YouTube channel | $0 free | youtube.com |

Total monthly cost: **$0**. Everything runs on free tiers.

---

## 3. Installation

### The easy way (one command)

```bash
bash start_here.sh
```

That single command: installs Python packages + FFmpeg, asks you for your API keys interactively (paste them, no file editing), runs the doctor (environment check), and offers to build a test video immediately.

### The manual way (if you prefer control)

```bash
# 1. install system deps (pick your OS)
sudo apt-get install -y python3 python3-pip ffmpeg    # Ubuntu/Debian
brew install python ffmpeg                             # macOS
pkg install python ffmpeg                              # Android/Termux

# 2. install python packages
python3 -m pip install -r requirements.txt

# 3. create your config
cp config/env.example config/.env
nano config/.env          # fill in keys (next section)

# 4. verify everything
python3 modules/doctor.py
```

### Platform notes

- **Windows**: use WSL2 (`wsl --install` in PowerShell, then follow Ubuntu steps). Native Windows works too if Python + FFmpeg are on PATH, but WSL is smoother.
- **Android (Termux)**: `pkg install python ffmpeg git` then everything else works the same. Run `termux-wake-lock` so uploads aren't killed in background.
- **Cheap VPS ($4/mo, always-on, best reliability)**: any Ubuntu box. Run cron there (section 6).

---

## 4. Get your free API keys

### 4a. Pexels key (30 seconds, needed for stock clips)

1. Go to **https://www.pexels.com/api/**
2. Click **"Get Started"** → create/login to a free account
3. You land on a page that already shows your **API key** — copy it
4. Put it in `config/.env`:
   ```
   Pexels-API-Key="paste_it_here"
   ```
Free limit: 200 requests/hour, 20,000/month — this pipeline uses ~10/day.

### 4b. YouTube OAuth (5 minutes, needed for auto-upload)

1. Go to **https://console.cloud.google.com/** → sign in with the Google account that owns your YouTube channel
2. Top bar → project dropdown → **"New Project"** → name it `shorts-pipeline` → **Create**
3. Left menu → **"APIs & Services" → "Library"** → search **"YouTube Data API v3"** → click it → **"Enable"**
4. Left menu → **"APIs & Services" → "OAuth consent screen"**:
   - User type: **External** → Create
   - App name: anything (`shorts pipeline`) → user support email: yours → Developer email: yours → Save
   - Scopes: skip (Add or Remove Scopes → nothing needed) → Save
   - Test users: **+ Add Users** → add your own Gmail → Save
5. Left menu → **"APIs & Services" → "Credentials"** → **"+ Create Credentials" → "OAuth client ID"**:
   - Application type: **Desktop app** → Create
6. A popup shows **Client ID** and **Client Secret** — copy both into `config/.env`:
   ```
   YT_CLIENT_ID="xxxxx.apps.googleusercontent.com"
   YT_CLIENT_SECRET="GOCSPX-xxxxx"
   ```
7. In `config/.env` also set your schedule:
   ```
   UPLOAD_HHMM="17:00"
   TIMEZONE="Asia/Kolkata"
   ```

> **Why "Desktop app" if it runs on a server?** The first upload is a one-time browser login that issues a refresh token; after that, uploads need no browser (section 6 explains the first-run flow).

> **Keep secrets private.** `config/.env` and `config/token.json` are already in `.gitignore` — never commit or share them.

## 5. Make your first video

### 5a. Build without uploading (totally safe test)

```bash
DRY_RUN=true python3 modules/daily.py day1_monday
```

What you'll see: narration files appear in `output/assets/day1_monday/audio/`, stock clips in `output/assets/day1_monday/video/`, and after a few minutes:

```
output/videos/day1_monday_final.mp4
```

Open it. It is a 1080×1920 vertical Short with:
- AI narration in the script's voice style
- a different stock clip per scene, auto-timed to the narration
- the big caption text burned in
- quiet music bed under the voice

### 5b. Or build the entire week at once

```bash
bash scripts/one_click_week.sh
```

7 videos land in `output/videos/`. Watch all of them. This is your quality gate.

### 5c. Upload your first Short manually

```bash
python3 modules/upload.py output/videos/day1_monday_final.mp4 day1_monday
```

**First-time only:** the terminal prints a Google URL → open it in any browser (phone browser works) → sign in with your channel's Google account → click **Allow** → Google shows a code/redirect → paste it back in the terminal. This creates `config/token.json`, and **every later upload is fully silent and automatic**.

When it finishes it prints:

```
UPLOADED day1_monday_final.mp4 -> https://youtube.com/shorts/<VIDEO_ID>
```

Check your channel — the Short is live with the viral title, SEO description, and tags from the JSON.

### 5d. Do the whole day automatically (TTS + assets + render + upload)

```bash
python3 modules/daily.py day2_tuesday
```

---

## 6. Turn on daily automatic uploads

Pick **one** of these three options.

### Option A — cron (Linux/VPS/macOS — recommended, most reliable)

```bash
crontab -e
```

Add this line (runs 17:00 server time daily; the script handles timezone itself):

```
0 17 * * * /root/shorts-pipeline/scripts/run_daily.sh >> /root/shorts-pipeline/logs/cron.log 2>&1
```

That's it. From now on, each day at 17:00 the machine renders and posts that day's video.

> If your server is UTC but you want Indian evening uploads, set `TIMEZONE="Asia/Kolkata"` in `config/.env` — `run_daily.sh` uses it to pick the correct weekday content.

### Option B — always-on Python loop (Windows/Android/anywhere)

```bash
nohup python3 modules/scheduler.py > logs/scheduler.log 2>&1 &
```

It sleeps until `UPLOAD_HHMM`, runs the daily pipeline, then sleeps until the next day. Survives reboots only if you add it to startup (cron `@reboot` or Termux `~/.bashrc`).

### Option C — GitHub Actions (free cloud computer, no machine of yours running)

1. Push this repo to GitHub (section 11 has the exact commands)
2. Repo → **Settings** → **Secrets and variables** → **Actions** → **New repository secret** — add: `PEXELS_API_KEY`, `YT_CLIENT_ID`, `YT_CLIENT_SECRET`, plus a `YTA_OAUTH_JSON` secret containing the full contents of `config/token.json` after your first manual upload
3. `.github/workflows/daily.yml` is included — enable it under the repo's **Actions** tab

> GitHub Actions quota note: YouTube's default API quota allows ~6 uploads/day, fine here; and Actions minutes are free for public repos.

### What the first automated day looks like

```
logs/2026-09-17_run.log
=== day4_thursday | niche=Dark History & Psychological Facts ... ===
STEP: tts_engine day4_thursday
scene 1 voice=en-US-GuyNeural dur=3.8s
...
STEP: pexels_assets day4_thursday
scene 1 <- pexels 8392012 (abstract neurons firing...)
...
STEP: render day4_thursday
RENDER OK day4_thursday -> output/videos/day4_thursday_final.mp4 (41.2s)
upload 33%  upload 66%  upload 100%
UPLOADED -> https://youtube.com/shorts/AbC123xYz
DONE day4_thursday
```

---

## 7. Write your own video scripts

Each `content/dayX_*.json` is a complete production order. The validator (`common.py`) enforces: scene durations 3.5–6.0s, total 40–62s, 100–135 narration words. Broken payloads fail fast **before** spending API calls.

### The JSON fields

```json
{
  "selected_niche": "...",
  "metadata": {
    "title": "<60 chars, curiosity gap, #Shorts",
    "description": "2 lines + question CTA + exactly 3 hashtags",
    "tags": ["5-7 search keywords"]
  },
  "audio_profile": {
    "recommended_voice_style": "authoritative|documentary|conversational|whisper",
    "pace_multiplier": 1.1,
    "bg_music_vibe": "dark cinematic tension strings"
  },
  "video_pipeline": [
    {
      "scene_id": 1,
      "narration_audio_text": "punchy hook line under 15 words",
      "visual_generation_prompt": "generic stock keywords for Pexels",
      "duration_seconds": 5.0,
      "on_screen_text_overlay": "BIG CAPTION TEXT"
    }
  ]
}
```

### Rules that make these viral (from the retained niche)

- **Scene 1 = hook**: contradiction or open loop. Never a greeting, never a summary.
- **Fragments, not sentences.** "Your brain decides before you know. Free will arrives late."
- **Numbered facts** — viewers comment the number that hit hardest; comments feed the algorithm.
- **Last scene = CTA** — comment + follow. Never "thanks for watching."
- **Visual prompts must be generic** ("dark moody portrait half lit cinematic") — no brand names, no fictional characters, nothing the stock API can't match.
- **Batch 7 payloads per week** — write all 7 on Sunday, the machine does the rest.

### Swap niches any time

The pipeline doesn't care what the niche is — it only cares the JSON validates. Want a second channel of AI-money facts or history conspiracies? Copy the `content/` structure with new payloads, point `daily.py` at different file names, done.

---

## 8. YouTube channel setup

1. **Create/brand the channel** — niche-consistent name and banner (e.g., "Mind Vault Facts", "Shadow Psychology").
2. **Upload identity**: your channel must not be set as "Made for Kids" — the pipeline already sends `selfDeclaredMadeForKids: false`.
3. **Video language**: set your channel default language; the TTS voices are English.
4. **Consistency beats everything**: same time daily, same format, same niche for at least 90 days before judging results.
5. **Monetization thresholds** (YouTube Partner Program):
   - 1,000 subscribers **and** 10 million public Shorts views in 90 days (Shorts path), or 4,000 watch-hours path for long-form
   - Then apply in YouTube Studio → Earn

---

## 9. The money part

Being brutally honest so you don't get disillusioned:

| Fact | Reality |
|---|---|
| Shorts RPM | $0.05–$0.30 per 1,000 views (lower than long-form) |
| When you first earn | only after YPP acceptance (1k subs + 10M Shorts views/90d) |
| Realistic path | post daily 60–90 days, double down on formats that hit, kill formats that flop |
| Extra income streams | affiliate links in description, selling the content packs, sponsoring later |
| What actually compounds | hook quality + posting consistency + niche consistency |

This pipeline removes 100% of the manual editing labor so you can spend your energy on the only lever that matters: **writing better hooks**.

---

## 10. Troubleshooting

| Symptom | Fix |
|---|---|
| `Set Pexels-API-Key` | edit `config/.env`, remove the word REPLACE |
| `401/403` from Pexels | wrong key, or hourly 200-request limit hit (wait) |
| `quotaExceeded` on upload | YouTube default quota = ~6 uploads/day; wait for reset (midnight PT) |
| `invalid_grant` / token expired | delete `config/token.json`, rerun upload, re-consent once |
| `redirect_uri_mismatch` | your OAuth client must be type "Desktop app" exactly as section 4b |
| Render fails on one scene | delete `output/assets/<day>/video/scene_<id>.mp4` + `asset_map.json`, rerun; fresh clip is fetched |
| Video is silent | check `output/assets/<day>/audio/scene_1.mp3` exists; if not, rerun `tts_engine.py` |
| Captions show wrong text | JSON `on_screen_text_overlay` contains `:` or `'` — escape or reword it |
| Cron runs but nothing happens | check `logs/cron.log`; ensure absolute paths (crontab doesn't load your shell) |
| Termux kills the job | run `termux-wake-lock`, disable battery optimization for Termux |
| `edge_tts` fails | internet hiccup; rerun — it's a free cloud service, retries are free |
| Whole run fails at doctor | run `python3 modules/doctor.py` — it names the exact blocker |

Run the doctor any time you're confused:

```bash
python3 modules/doctor.py
```

---

## 11. Command cheat sheet + file map

### Daily driving

```bash
bash start_here.sh                                   # first-time bootstrap (interactive)
python3 modules/doctor.py                            # environment check
DRY_RUN=true python3 modules/daily.py day1_monday    # build video, no upload
python3 modules/daily.py day1_monday                 # build + upload now
bash scripts/one_click_week.sh                       # render all 7, no upload
python3 modules/upload.py <mp4> <day_key>            # upload existing render
nohup python3 modules/scheduler.py > logs/scheduler.log 2>&1 &   # always-on loop
```

### Push this project to your own GitHub

```bash
cd shorts-pipeline
git init
git add .
git commit -m "Automated YouTube Shorts pipeline: content, render, upload, schedule"
# create an EMPTY repo on github.com first (no README, no gitignore), then:
git remote add origin https://github.com/YOUR_USERNAME/shorts-pipeline.git
git branch -M main
git push -u origin main
```

Secrets stay private automatically: `config/.env`, `config/token.json`, `output/`, `logs/` are gitignored. Double-check with `git status` before pushing.

### File map

```
shorts-pipeline/
├── start_here.sh              one-command bootstrap
├── GUIDE.md                   this guide
├── README.md                  quick reference
├── requirements.txt           python deps
├── config/
│   ├── env.example            template (committed, safe)
│   └── .env                   your keys (NOT committed)
├── content/
│   └── day1..day7 *.json      7 pre-written viral scripts
├── modules/
│   ├── common.py              config, logging, validation
│   ├── tts_engine.py          narration (edge-tts, free)
│   ├── pexels_assets.py       stock video + music fetch
│   ├── render.py              FFmpeg assembly (1080x1920)
│   ├── upload.py              YouTube Data API v3 upload
│   ├── daily.py               one-day orchestrator
│   ├── scheduler.py           always-on daily loop
│   └── doctor.py              pre-flight checker
├── scripts/
│   ├── setup.sh               installs everything (multi-OS)
│   ├── run_daily.sh           cron entrypoint
│   └── one_click_week.sh      render whole week locally
└── output/  logs/             generated (gitignored)
```

---

*Built to be boring: every stage logs what it does, every failure names its fix, every secret stays local. Edit hooks, stay consistent, ship daily.*
