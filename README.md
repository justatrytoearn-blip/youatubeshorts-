# Automated YouTube Shorts Pipeline

One video every day, fully automated: free neural TTS narration + Pexels stock footage + FFmpeg render + YouTube upload. Niche: Dark History & Psychological Facts (highest retention, stock-friendly).

**New here? Read [`GUIDE.md`](GUIDE.md)** — it takes you from zero to automated daily uploads with exact click-by-click instructions.

## 60-second start

```bash
bash start_here.sh        # installs everything, asks for keys, runs doctor
```

Then:

```bash
python3 modules/webapp.py   # WEB CONSOLE -> open http://localhost:5000
```

The console is the main control panel: build & upload any video with one tap, watch progress live, preview videos in the browser (no more file-copying to your gallery), edit scripts with validation, and toggle the daily auto-pilot schedule.

CLI commands (also work):

```bash
DRY_RUN=true python3 modules/daily.py day1_monday   # test render, no upload
python3 modules/upload.py output/videos/day1_monday_final.mp4 day1_monday  # go live
```

## Daily automation (pick one)

```bash
# A. cron (recommended, Linux/VPS/macOS):
crontab -e    # add:  0 17 * * * /root/shorts-pipeline/scripts/run_daily.sh >> /root/shorts-pipeline/logs/cron.log 2>&1

# B. always-on loop (Windows/Android/Termux):
nohup python3 modules/scheduler.py > logs/scheduler.log 2>&1 &
```

## Commands

| Command | What it does |
|---|---|
| `bash start_here.sh` | one-time interactive bootstrap |
| `python3 modules/doctor.py` | check environment, names exact fixes |
| `DRY_RUN=true python3 modules/daily.py <day>` | build video, skip upload |
| `python3 modules/daily.py <day>` | build + upload now |
| `bash scripts/one_click_week.sh` | render all 7 videos locally |
| `python3 modules/webapp.py` | **web console: build / upload / schedule / edit / watch** |
| `python3 modules/upload.py <mp4> <day>` | upload an existing render |

## Money reality (read this)

- YouTube pays Shorts only after **1,000 subs + 10M Shorts views in 90 days** (Partner Program).
- Shorts RPM: $0.05–$0.30 / 1k views. Volume + hook quality + daily consistency is the whole game.
- Extra streams: affiliate links in descriptions, selling content packs.

## Secrets stay private

`config/.env`, `config/token.json`, `output/`, `logs/` are gitignored — safe to push to GitHub.

## Troubleshooting

Full error table in [`GUIDE.md` §10](GUIDE.md#10-troubleshooting). Quick fix for most things:

```bash
python3 modules/doctor.py
```
