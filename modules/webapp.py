"""Web console for the Shorts pipeline: build, upload, schedule, edit, watch.

Run:
    python3 modules/webapp.py            # console at http://localhost:5000
    PORT=8080 python3 modules/webapp.py  # custom port

From the console you can:
  * Build any day's video (TTS -> stock -> render) and watch progress live
  * Upload to YouTube with one tap
  * Enable a daily auto build+upload schedule (runs inside this process)
  * Edit every script (title, narration, visuals) with live validation
  * Preview finished videos in the browser (works great on phones)
"""
import json
import os
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory
from flask import send_file

from common import (BASE_DIR, CONTENT_DIR, ENV_FILE, VIDEO_DIR, day_from_date,
                    load_env, load_payload, validate_payload)

load_env()

MOD_DIR = Path(__file__).resolve().parent
STATE_FILE = BASE_DIR / "output" / "web_state.json"
WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday",
            "saturday", "sunday"]
PORT = int(os.environ.get("PORT", "5000"))
LOG_LIMIT = 500          # lines kept per job
POLL_SAVE = True

app = Flask(__name__)
_lock = threading.RLock()


# ---------------------------------------------------------------- state ----
def default_state():
    return {"jobs": {}, "schedule": {"enabled": False, "time": "17:00",
                                     "last_run_date": "", "next_run": ""},
            "history": [],
            "ai_job": {"running": False, "topic": "", "progress": []}}


def load_state():
    st = default_state()
    if STATE_FILE.exists():
        try:
            st.update(json.loads(STATE_FILE.read_text()))
        except Exception:
            pass
    st.setdefault("ai_job", {"running": False, "topic": "", "progress": []})
    if st["ai_job"].get("running"):   # a dead process can't finish it
        st["ai_job"]["running"] = False
        for entry in st["ai_job"].get("progress", []):
            if entry.get("status") == "pending":
                entry["status"] = "error"
                entry["error"] = "server restarted"
    # jobs from a previous process can't be running anymore
    for job in st["jobs"].values():
        if job.get("status") in ("queued", "building"):
            job["status"] = "interrupted"
    return st


state = load_state()


def save_state():
    with _lock:
        # non-serializable runtime objects (Popen etc.) become null
        clean = json.loads(json.dumps(state, default=lambda o: None))
        for job in clean["jobs"].values():
            job.pop("_proc", None)
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps(clean, indent=1))


def set_env_key(key: str, value: str):
    """Create/update a key in config/.env (file format: KEY="value")."""
    import re
    line = f'{key}="{value}"'
    text = ENV_FILE.read_text() if ENV_FILE.exists() else ""
    if re.search(rf"(?m)^{re.escape(key)}=", text):
        text = re.sub(rf"(?m)^{re.escape(key)}=.*$", line, text)
    else:
        text = text.rstrip("\n") + ("\n" if text else "") + line + "\n"
    ENV_FILE.parent.mkdir(parents=True, exist_ok=True)
    ENV_FILE.write_text(text)
    os.environ[key] = value


def _fix_retired_gemini_model():
    """Old installs may have a retired Gemini model saved; auto-upgrade it."""
    if os.environ.get("AI_PROVIDER") == "gemini":
        m = os.environ.get("AI_MODEL", "")
        if m.startswith(("gemini-1.5", "gemini-2.0")):
            set_env_key("AI_MODEL", "gemini-2.5-flash")


_fix_retired_gemini_model()


@app.post("/api/settings")
def api_settings():
    body = request.get_json(force=True, silent=True) or {}
    key = str(body.get("key", "")).strip()
    value = str(body.get("value", "")).strip()
    if key == "AI_PROVIDER":
        if value not in ("openai", "gemini", "custom"):
            return jsonify({"error": "provider must be openai, gemini or custom"}), 400
        set_env_key("AI_PROVIDER", value)
        if value == "gemini":
            set_env_key("AI_MODEL", "gemini-2.5-flash")
            set_env_key("OPENAI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai/")
        elif value == "openai":
            set_env_key("AI_MODEL", "gpt-4o-mini")
            set_env_key("OPENAI_BASE_URL", "https://api.openai.com/v1")
        return jsonify({"ok": True, "provider": value})
    if key == "OPENAI_BASE_URL":
        if not value.startswith(("http://", "https://")):
            return jsonify({"error": "URL must start with http:// or https://"}), 400
        set_env_key(key, value)
        return jsonify({"ok": True})
    if key == "AI_MODEL":
        if not value:
            return jsonify({"error": "value required"}), 400
        set_env_key(key, value)
        return jsonify({"ok": True})
    if key in ("YT_CLIENT_ID", "YT_CLIENT_SECRET"):
        if not value:
            return jsonify({"error": "value required"}), 400
        set_env_key(key, value)
        return jsonify({"ok": True})
    if key not in ("OPENAI_API_KEY",):
        return jsonify({"error": "unknown setting"}), 400
    if not value:
        return jsonify({"error": "value required"}), 400
    set_env_key(key, value)
    return jsonify({"ok": True})


@app.get("/api/settings")
def api_settings_get():
    k = os.environ.get("OPENAI_API_KEY", "")
    has = bool(k.strip()) and "REPLACE" not in k
    provider = os.environ.get("AI_PROVIDER", "openai")
    default_base = ("https://generativelanguage.googleapis.com/v1beta/openai/"
                    if provider == "gemini" else "https://api.openai.com/v1")
    yid = (os.environ.get("YT_CLIENT_ID") or "").strip()
    ysec = (os.environ.get("YT_CLIENT_SECRET") or "").strip()
    return jsonify({"openai_configured": has,
                    "masked": (k[:7] + "…" + k[-4:]) if has else "",
                    "provider": provider,
                    "model": os.environ.get("AI_MODEL", "gpt-4o-mini"),
                    "base_url": os.environ.get("OPENAI_BASE_URL", default_base),
                    "yt_id_masked": (yid[:10] + "…") if yid else "",
                    "yt_secret_saved": bool(ysec)})


@app.get("/api/ai-models")
def api_ai_models():
    """List chat models available to the saved key, so the user can pick a
    working one instead of guessing (prevents 404 model errors)."""
    import re
    import requests

    key = (os.environ.get("OPENAI_API_KEY") or "").strip()
    base = os.environ.get("OPENAI_BASE_URL",
                          "https://api.openai.com/v1").rstrip("/")
    if not key or "REPLACE" in key:
        return jsonify({"error": "save your API key first"}), 200
    try:
        r = requests.get(base + "/models",
                         headers={"Authorization": "Bearer " + key},
                         timeout=30)
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": f"could not reach {base}: {exc}"}), 200
    if r.status_code != 200:
        return jsonify({"error": f"HTTP {r.status_code} from {base}/models "
                                 "— check key and URL"}), 200
    try:
        items = r.json().get("data") or r.json().get("models") or []
    except Exception:  # noqa: BLE001
        return jsonify({"error": "unexpected response from provider"}), 200
    ids = []
    for it in items:
        mid = str(it.get("id") or it.get("name") or "")
        mid = mid.split("models/")[-1]   # gemini native names: models/gemini-x
        if not mid or re.search(r"embedding|aqa|imagen|veo|tts|audio|image"
                                r"|live|whisper|moderation", mid, re.I):
            continue
        ids.append(mid)
    ids = sorted(set(ids), reverse=True)
    suggested = next((m for m in ids if "flash" in m and "thinking" not in m
                      and "lite" not in m), ids[0] if ids else "")
    return jsonify({"models": ids,
                    "current": os.environ.get("AI_MODEL", ""),
                    "suggested": suggested})


def day_keys():
    return sorted(p.stem for p in CONTENT_DIR.glob("*.json"))


def safe_key(day):
    import re
    if not re.fullmatch(r"[a-z0-9_]{1,40}", day or ""):
        return None
    return day


NEW_TEMPLATE = {
    "selected_niche": "Custom",
    "metadata": {
        "title": "New Short Title Here #Shorts",
        "description": "Describe the video and add a call to action. "
                       "#Shorts #PsychologyFacts #MindBlown",
        "tags": ["psychology facts", "shorts", "viral facts", "mind blowing",
                 "dark psychology"],
    },
    "audio_profile": {
        "recommended_voice_style": "deep male authoritative",
        "pace_multiplier": 1.15,
        "bg_music_vibe": "dark cinematic tension strings",
    },
    "video_pipeline": [],
}

_SENTENCES = [
    "Replace this sentence with your opening hook right now.",
    "Fact one goes here keep it short and punchy.",
    "Add the second fact here make it surprising.",
    "Write fact number three with strong emotion.",
    "Fact four continues the curiosity gap nicely.",
    "Fact five should escalate the tension further.",
    "Fact six delivers another mind blowing twist.",
    "Fact seven keeps viewers watching until end.",
    "Fact eight pushes toward the finale now.",
    "Fact nine sets up the final payoff moment.",
    "Close with a comment question and follow prompt.",
]


def build_new_payload():
    import copy
    payload = copy.deepcopy(NEW_TEMPLATE)
    payload["video_pipeline"] = [
        {"scene_id": i + 1,
         "narration_audio_text": s,
         "visual_generation_prompt": "dark moody cinematic stock footage slow",
         "duration_seconds": 4.5,
         "on_screen_text_overlay": f"SCENE {i + 1} TEXT"}
        for i, s in enumerate(_SENTENCES)
    ]
    return payload


def day_key_for(dt):
    return f"day{dt.weekday() + 1}_{WEEKDAYS[dt.weekday()]}"


def running_days():
    return [d for d, j in state["jobs"].items()
            if j.get("status") in ("queued", "building")]


# ------------------------------------------------------------ job runner ---
def _log(day, line):
    job = state["jobs"].get(day)
    if job is None:
        return
    job["log"].append(f"{datetime.now():%H:%M:%S} {line}")
    del job["log"][:-LOG_LIMIT]


def _run_step(day, name, cmd):
    job = state["jobs"][day]
    job["step"] = name
    _log(day, f"$ {' '.join(str(c) for c in cmd)}")
    save_state()
    proc = subprocess.Popen([str(c) for c in cmd], cwd=str(BASE_DIR),
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, start_new_session=True)
    job["_proc"] = proc
    for line in proc.stdout:
        _log(day, line.rstrip())
    rc = proc.wait()
    if rc != 0:
        raise RuntimeError(f"{name} step failed (exit {rc})")
    _log(day, f"{name} ok")


def _worker(day, upload):
    job = state["jobs"][day]
    job["status"] = "building"
    job["started"] = datetime.now().isoformat(timespec="seconds")
    _log(day, f"=== build {day} (upload={upload}) ===")
    save_state()
    steps = [
        ("tts", [sys.executable, MOD_DIR / "tts_engine.py", day]),
        ("assets", [sys.executable, MOD_DIR / "pexels_assets.py", day]),
        ("render", [sys.executable, MOD_DIR / "render.py", day]),
    ]
    if upload and os.environ.get("DRY_RUN", "false").lower() != "true":
        if not yt_client.creds_available():
            job["need_consent"] = True
            _log(day, "YouTube not connected yet - video built, upload "
                      "skipped.")
            _log(day, "Open the Stats tab, tap 'Connect YouTube', then run "
                      "Build+Upload again.")
        else:
            steps.append(("upload", [sys.executable, MOD_DIR / "upload.py",
                                     VIDEO_DIR / f"{day}_final.mp4", day]))
    else:
        _log(day, "upload skipped (DRY_RUN or build-only request)")
    try:
        for name, cmd in steps:
            _run_step(day, name, cmd)
        video = VIDEO_DIR / f"{day}_final.mp4"
        if video.exists():
            job["video"] = f"/videos/{video.name}"
        url = next((ln.split("->")[-1].strip() for ln in reversed(job["log"])
                    if "youtube.com/shorts/" in ln), None)
        if url:
            job["status"] = "uploaded"
            job["url"] = url
            state["history"].insert(0, {
                "day": day, "url": url,
                "when": datetime.now().isoformat(timespec="seconds"),
                "title": next((ln.split("title=", 1)[-1]
                               for ln in job["log"] if "title=" in ln), day),
            })
            del state["history"][24:]
            _log(day, f"DONE -> {url}")
        else:
            job["status"] = "done"
            _log(day, "DONE (local video ready)")
    except Exception as exc:  # noqa: BLE001
        job["status"] = "error"
        job["error"] = str(exc)
        _log(day, f"FAILED: {exc}")
    finally:
        job["step"] = None
        job.pop("_proc", None)
        job["ended"] = datetime.now().isoformat(timespec="seconds")
        save_state()


def start_job(day, upload):
    with _lock:
        if day in running_days():
            return False, "already running"
        if not (CONTENT_DIR / f"{day}.json").exists():
            return False, "no content file"
        state["jobs"][day] = {"status": "queued", "step": None,
                              "upload": bool(upload), "log": [],
                              "started": None, "ended": None, "error": None,
                              "video": None, "url": None}
        save_state()
    threading.Thread(target=_worker, args=(day, upload), daemon=True).start()
    return True, "started"


# ------------------------------------------------------------- scheduler ---
def scheduler_loop():
    while True:
        try:
            with _lock:
                sch = state["schedule"]
                if sch.get("enabled"):
                    hh, mm = (int(x) for x in str(sch.get("time", "17:00"))
                              .split(":")[:2])
                    now = datetime.now()
                    target = now.replace(hour=hh, minute=mm, second=0,
                                         microsecond=0)
                    if target > now:
                        sch["next_run"] = target.isoformat(timespec="seconds")
                    elif (sch.get("last_run_date") != now.date().isoformat()
                          and not running_days()):
                        day = day_key_for(now)
                        if (CONTENT_DIR / f"{day}.json").exists():
                            sch["last_run_date"] = now.date().isoformat()
                            ok, msg = start_job(day, upload=True)
                            print(f"[scheduler] firing {day}: {msg}")
                        else:
                            sch["last_run_date"] = now.date().isoformat()
                save_state()
        except Exception as exc:  # noqa: BLE001
            print(f"[scheduler] error: {exc}")
        time.sleep(20)


# ---------------------------------------------------------------- routes ---
@app.get("/")
def index():
    return send_file(MOD_DIR / "console.html")


def _day_info(key):
    try:
        payload = load_payload(key)
    except Exception as exc:  # noqa: BLE001
        return {"key": key, "error": str(exc)}
    scenes = payload.get("video_pipeline", [])
    job = state["jobs"].get(key, {})
    return {
        "key": key,
        "title": payload.get("metadata", {}).get("title", key),
        "niche": payload.get("selected_niche", ""),
        "scenes": len(scenes),
        "duration": round(sum(float(s["duration_seconds"]) for s in scenes), 1),
        "words": sum(len(s["narration_audio_text"].split()) for s in scenes),
        "status": job.get("status", "idle"),
        "step": job.get("step"),
        "error": job.get("error"),
        "video": f"/videos/{key}_final.mp4"
        if (VIDEO_DIR / f"{key}_final.mp4").exists() else None,
        "url": job.get("url"),
        "upload": job.get("upload"),
        "need_consent": job.get("need_consent"),
    }


@app.get("/api/state")
def api_state():
    with _lock:
        days = [_day_info(k) for k in day_keys()]
        return jsonify({"days": days, "schedule": state["schedule"],
                        "history": state["history"][:10],
                        "ai_job": state["ai_job"],
                        "jobs": {k: {kk: vv for kk, vv in j.items()
                                     if kk != "_proc"}
                                 for k, j in state["jobs"].items()},
                        "server_time": datetime.now().isoformat(timespec="seconds")})


@app.get("/api/day/<day>")
def api_get_day(day):
    day = safe_key(day)
    if not day:
        return jsonify({"error": "invalid day key"}), 400
    try:
        return jsonify(load_payload(day))
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": str(exc)}), 404


@app.post("/api/new")
def api_new():
    n = 1
    while (CONTENT_DIR / f"custom_{n}.json").exists():
        n += 1
    key = f"custom_{n}"
    (CONTENT_DIR / f"{key}.json").write_text(
        json.dumps(build_new_payload(), indent=1))
    return jsonify({"key": key, "payload": build_new_payload()})


@app.post("/api/day/<day>/delete")
def api_delete_day(day):
    day = safe_key(day)
    if not day or day in running_days():
        return jsonify({"error": "invalid key or job running"}), 400
    path = CONTENT_DIR / f"{day}.json"
    if path.exists():
        path.unlink()
    return jsonify({"ok": True})


# -------------------------------------------------------- YouTube extras ---
sys.path.insert(0, str(MOD_DIR))
import yt_client  # noqa: E402


def _yt_err(exc: Exception) -> str:
    msg = str(exc)
    if "YT_CLIENT" in msg or "keys missing" in msg:
        return "YouTube app keys missing. Add YT_CLIENT_ID and " \
               "YT_CLIENT_SECRET in the Settings tab."
    if "not connected yet" in msg:
        return "YouTube not connected yet. Tap Connect in the Stats tab " \
               "and approve the Google consent link."
    return msg[:200]


def _extract_vid(text: str) -> str:
    import re
    m = re.search(r"(?:shorts/|v=|be/|videos/|video_id=|^)([A-Za-z0-9_-]{6,20})",
                  (text or "").strip())
    return m.group(1) if m else ""


def _dur_secs(iso: str) -> int:
    import re
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso or "")
    if not m:
        return 0
    h, mi, s = (int(x) if x else 0 for x in m.groups())
    return h * 3600 + mi * 60 + s


def _track(vid: str, title: str):
    if not any(h.get("url", "").endswith(vid) for h in state["history"]):
        state["history"].insert(0, {
            "day": (title or vid)[:40],
            "url": "https://youtube.com/shorts/" + vid,
            "when": datetime.now().isoformat(timespec="seconds"),
            "title": title or vid})
        del state["history"][24:]
        save_state()


@app.get("/api/yt/connect-start")
def api_yt_connect_start():
    try:
        return jsonify({"ok": True, "url": yt_client.consent_url()})
    except Exception as exc:  # noqa: BLE001
        return jsonify({"ok": False, "error": _yt_err(exc)}), 200


@app.post("/api/yt/connect-finish")
def api_yt_connect_finish():
    body = request.get_json(force=True, silent=True) or {}
    url = str(body.get("url", ""))
    try:
        code = yt_client.parse_redirect(url)
        if not code:
            raise yt_client.YouTubeError(
                "no ?code= in that link. Copy the FULL address-bar URL "
                "from the page Google sent you to.")
        yt_client.finish_connect(url)
        return jsonify({"ok": True})
    except Exception as exc:  # noqa: BLE001
        return jsonify({"ok": False, "error": _yt_err(exc)}), 200


@app.get("/api/yt/status")
def api_yt_status():
    connected = False
    try:
        connected = yt_client.creds_available() and bool(
            yt_client.get_access_token())
    except Exception:
        pass
    keys = bool((os.environ.get("YT_CLIENT_ID") or "").strip()
                and "REPLACE" not in os.environ.get("YT_CLIENT_ID", ""))
    return jsonify({"connected": connected, "keys_saved": keys})


@app.get("/api/yt/analytics")
def api_yt_analytics():
    """Views/likes/comments for every tracked video (history + channel)."""
    try:
        ids, seen = [], set()
        for h in state.get("history", []):
            vid = h.get("url", "").rsplit("/", 1)[-1]
            if vid and vid not in seen:
                seen.add(vid)
                ids.append(vid)
        for it in yt_client.list_my_videos(25):
            vid = it.get("id", {}).get("videoId", "")
            if vid and vid not in seen:
                seen.add(vid)
                ids.append(vid)
        if not ids:
            return jsonify({"videos": [],
                            "totals": {"views": 0, "likes": 0,
                                       "comments": 0}}), 200
        videos, totals = [], {"views": 0, "likes": 0, "comments": 0}
        for it in yt_client.get_videos(ids[:50]):
            sn, st = it.get("snippet", {}), it.get("statistics", {})
            dur = it.get("contentDetails", {}).get("duration", "")
            views = int(st.get("viewCount", 0))
            likes = int(st.get("likeCount", 0))
            comments = int(st.get("commentCount", 0))
            totals["views"] += views
            totals["likes"] += likes
            totals["comments"] += comments
            top = yt_client.top_comments(it["id"], 3) if comments else []
            videos.append({"id": it["id"], "title": sn.get("title", ""),
                           "published": sn.get("publishedAt", "")[:16]
                           .replace("T", " "),
                           "is_short": _dur_secs(dur) <= 61,
                           "top_comments": top,
                           "stats": {"views": views, "likes": likes,
                                     "comments": comments}})
        return jsonify({"videos": videos, "totals": totals}), 200
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": "YouTube API error: " + _yt_err(exc)}), 200


@app.post("/api/yt/direct-upload")
def api_yt_direct_upload():
    """Track an already-uploaded video by its YouTube ID or link."""
    raw = str((request.get_json(force=True, silent=True) or {})
              .get("id", "")).strip()
    vid = _extract_vid(raw)
    if not vid:
        return jsonify({"error": "that does not look like a video ID"}), 400
    try:
        items = yt_client.get_video(vid)
        if not items:
            return jsonify({"error": "video not found (wrong ID?)"}), 200
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": "YouTube error: " + _yt_err(exc)}), 200
    sn = (items or {}).get("snippet", {})
    _track(vid, sn.get("title", ""))
    return jsonify({"ok": True, "id": vid})


@app.post("/api/yt/history-remove")
def api_yt_history_remove():
    vid = str((request.get_json(force=True, silent=True) or {})
              .get("id", "")).strip()
    state["history"] = [h for h in state.get("history", [])
                        if h.get("url", "").rsplit("/", 1)[-1] != vid]
    save_state()
    return jsonify({"ok": True})


def extract_json(text: str) -> dict:
    """Pull the first JSON object out of raw ChatGPT output (tolerant of
    markdown fences, chatter, multiple blocks)."""
    text = (text or "").strip()
    if "```" in text:  # prefer fenced block that contains an object
        for part in text.split("```"):
            if "{" in part:
                text = part
                break
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("no JSON object found in the pasted text")
    return json.loads(text[start:end + 1])


# ------------------------------------------------------- AI generation ---
def build_week_prompt(topic: str) -> str:
    return (
        "You are an autonomous AI content director for viral YouTube Shorts in "
        "the dark psychology / mind facts niche.\n\n"
        f"Create a complete video production script about: {topic}\n\n"
        "Return ONLY raw minified JSON (no markdown fences, no explanations) "
        "with EXACTLY this structure:\n"
        '{"selected_niche":"...","metadata":{"title":"under 100 chars, add '
        '#Shorts + 2 trending keywords","description":"1-2 sentences with a '
        'comment CTA and exactly 3 hashtags","tags":["5-7 search keywords"]},'
        '"audio_profile":{"recommended_voice_style":"deep male authoritative '
        'with urgent cinematic undertone","pace_multiplier":1.15,'
        '"bg_music_vibe":"dark cinematic tension strings over low synth '
        'drone"},"video_pipeline":[{"scene_id":1,"narration_audio_text":'
        '"un-skippable psychological hook, max 15 words",'
        '"visual_generation_prompt":"generic stock footage search phrase for '
        'Pexels, no brands, 6-10 words","duration_seconds":4.5,'
        '"on_screen_text_overlay":"CAPS text burned on screen"}, ... 8-10 '
        'scenes ...]}\n\n'
        "Hard rules:\n"
        "- scene 1 hook stops the scroll in under 3 seconds\n"
        "- each scene duration 3.5-6.0 seconds; total 40-62 seconds\n"
        "- total narration word count across ALL scenes: 100-135 words\n"
        "- narration: punchy fragments, no compound sentences\n"
        "- last scene asks for a comment + follow\n"
        "- visual_generation_prompt: generic aesthetic keywords only, no names "
        "or brands\n"
        "- title max 100 chars; exactly 3 hashtags in description; 5-7 tags"
    )


def _ai_error_detail(resp) -> str:
    try:
        return ((resp.json().get("error") or {}).get("message") or "").strip()
    except Exception:
        return ""


def _ai_generate_script(topic: str) -> dict:
    """Call an OpenAI-compatible chat API with plain requests (no SDK needed
    on Termux). Works with OpenAI, Google Gemini (free tier), and local LLM
    servers via OPENAI_BASE_URL."""
    import requests

    url = os.environ.get("OPENAI_BASE_URL",
                         "https://api.openai.com/v1").rstrip("/") + "/chat/completions"
    headers = {"Authorization":
               "Bearer " + os.environ.get("OPENAI_API_KEY", "").strip(),
               "Content-Type": "application/json"}
    body = {"model": os.environ.get("AI_MODEL", "gpt-4o-mini"),
            "temperature": 0.9,
            "messages": [{"role": "user",
                          "content": build_week_prompt(topic)}]}

    backoffs = [5, 15, 30, 60]
    last_err = "unknown error"
    for attempt in range(len(backoffs) + 1):
        resp = None
        try:
            resp = requests.post(url, headers=headers, json=body, timeout=180)
        except Exception as exc:  # noqa: BLE001
            last_err = f"network error: {exc}"
        if resp is not None and resp.status_code == 200:
            raw = (resp.json().get("choices") or [{}])[0] \
                .get("message", {}).get("content") or ""
            try:
                data = extract_json(raw)
                validate_payload(data, f"AI script ({topic})")
            except Exception as exc:  # noqa: BLE001
                raise ValueError(f"AI returned an invalid script: {exc}") from exc
            return data
        if resp is not None:
            detail = _ai_error_detail(resp)
            low = detail.lower()
            if resp.status_code in (401, 403):
                raise ValueError("API key rejected. Check the key in Settings.")
            if resp.status_code == 429 and ("quota" in low or "billing" in low):
                raise ValueError("AI account out of credit. Add credit on your "
                                 "provider's billing page, or switch to the FREE "
                                 "Google Gemini provider in Settings.")
            if resp.status_code == 429 or resp.status_code >= 500:
                last_err = f"HTTP {resp.status_code} {detail[:120]}"
                ra = resp.headers.get("Retry-After")
                delay = float(ra) if (ra or "").replace(".", "").isdigit() \
                    else backoffs[min(attempt, len(backoffs) - 1)]
                time.sleep(min(delay, 90))
                continue
            raise ValueError(f"AI API error {resp.status_code}: {detail[:180]}")
        time.sleep(backoffs[min(attempt, len(backoffs) - 1)])
    raise ValueError(f"AI service unreachable after retries ({last_err}). "
                     "If this keeps happening, switch provider in Settings.")


def _ai_worker(topic: str, days: list):
    try:
        for i, day in enumerate(days, 1):
            ai = state["ai_job"]
            ai["current"] = f"{i}/{len(days)}: {day}"
            entry = next((e for e in ai["progress"] if e["day"] == day), None)
            try:
                variant = topic if len(days) == 1 else f"{topic} (part {i})"
                data = _ai_generate_script(variant)
                (CONTENT_DIR / f"{day}.json").write_text(json.dumps(data, indent=1))
                if entry:
                    entry["status"] = "done"
                    entry["title"] = data.get("metadata", {}).get("title", "")
            except Exception as exc:  # noqa: BLE001
                if entry:
                    entry["status"] = "error"
                    entry["error"] = str(exc)[:200]
        ai["running"] = False
        ai["current"] = ""
    finally:
        save_state()


def start_ai_job(topic: str, days: list):
    with _lock:
        if state["ai_job"].get("running"):
            return False, "another AI generation is running"
        busy = [d for d in days if d in running_days()]
        if busy:
            return False, f"these days are building right now: {', '.join(busy)}"
        state["ai_job"] = {
            "running": True, "topic": topic, "current": "",
            "progress": [{"day": d, "status": "pending"} for d in days],
        }
        save_state()
    threading.Thread(target=_ai_worker, args=(topic, days), daemon=True).start()
    return True, "started"


@app.post("/api/ai-generate")
def api_ai_generate():
    body = request.get_json(force=True, silent=True) or {}
    topic = str(body.get("topic", "")).strip()[:120]
    if not topic:
        return jsonify({"error": "topic required"}), 400
    days = body.get("days") or []
    if not isinstance(days, list):
        return jsonify({"error": "days must be a list"}), 400
    days = [d for d in (safe_key(x) for x in days) if d]
    if not days:
        return jsonify({"error": "pick at least one day"}), 400
    if not (os.environ.get("OPENAI_API_KEY") or "").strip() \
            or "REPLACE" in os.environ.get("OPENAI_API_KEY", ""):
        return jsonify({"error": "add OPENAI_API_KEY to config/.env first "
                                 "(console Settings tab)"}), 400
    ok, msg = start_ai_job(topic, days)
    return (jsonify({"ok": ok, "msg": msg}), 200 if ok else 409)


@app.post("/api/ai-test")
def api_ai_test():
    try:
        script = _ai_generate_script("one surprising fact about human memory")
        n = len(script.get("video_pipeline", []))
        return jsonify({"ok": True, "scenes": n})
    except Exception as exc:  # noqa: BLE001
        return jsonify({"ok": False, "error": str(exc)[:300]}), 200


@app.post("/api/import")
def api_import():
    """Save a pasted ChatGPT script. Body: {text, replace(optional day key)}."""
    body = request.get_json(force=True, silent=True) or {}
    try:
        data = extract_json(body.get("text", ""))
        validate_payload(data, "pasted script")
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": f"could not parse JSON: {exc}"}), 400

    replace = safe_key(body.get("replace") or "")
    if replace:
        if replace in running_days():
            return jsonify({"error": "that day is building right now"}), 409
        key = replace
    else:
        n = 1
        while (CONTENT_DIR / f"custom_{n}.json").exists():
            n += 1
        key = f"custom_{n}"
    (CONTENT_DIR / f"{key}.json").write_text(json.dumps(data, indent=1))
    return jsonify({"ok": True, "key": key})


@app.post("/api/day/<day>")
def api_save_day(day):
    day = safe_key(day)
    if not day:
        return jsonify({"error": "invalid day key"}), 400
    data = request.get_json(force=True, silent=True)
    if not data:
        return jsonify({"error": "invalid JSON"}), 400
    try:
        validate_payload(data, day)
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": str(exc)}), 400
    (CONTENT_DIR / f"{day}.json").write_text(json.dumps(data, indent=1))
    return jsonify({"ok": True})


@app.post("/api/build/<day>")
def api_build(day):
    upload = (request.get_json(force=True, silent=True) or {}).get("upload", False)
    ok, msg = start_job(day, upload=upload)
    return (jsonify({"ok": ok, "msg": msg}), 200 if ok else 409)


@app.post("/api/stop/<day>")
def api_stop(day):
    job = state["jobs"].get(day)
    if not job or "_proc" not in job:
        return jsonify({"error": "not running"}), 404
    try:
        os.killpg(job["_proc"].pid, signal.SIGTERM)
    except Exception:
        pass
    return jsonify({"ok": True})


@app.post("/api/schedule")
def api_schedule():
    body = request.get_json(force=True, silent=True) or {}
    time_s = str(body.get("time", state["schedule"].get("time", "17:00")))
    try:
        hh, mm = time_s.split(":")
        assert 0 <= int(hh) <= 23 and 0 <= int(mm) <= 59
    except Exception:
        return jsonify({"error": "time must be HH:MM"}), 400
    state["schedule"]["time"] = f"{int(hh):02d}:{int(mm):02d}"
    state["schedule"]["enabled"] = bool(body.get("enabled"))
    save_state()
    return jsonify(state["schedule"])


@app.get("/videos/<path:name>")
def api_video(name):
    return send_from_directory(VIDEO_DIR, name)


@app.get("/api/log/<day>")
def api_log(day):
    job = state["jobs"].get(day, {})
    return jsonify({"log": job.get("log", [])})


def main():
    threading.Thread(target=scheduler_loop, daemon=True).start()
    for stale in running_days():
        state["jobs"][stale]["status"] = "interrupted"
    save_state()
    print(f"\n  SHORTS CONSOLE -> http://localhost:{PORT}")
    try:
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        print(f"  (same Wi-Fi, other devices) -> http://{ip}:{PORT}")
        s.close()
    except Exception:
        pass
    print("  Ctrl+C to stop.\n")
    app.run(host="0.0.0.0", port=PORT, threaded=True)


if __name__ == "__main__":
    main()
