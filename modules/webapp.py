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

from common import (BASE_DIR, CONTENT_DIR, VIDEO_DIR, day_from_date, load_env,
                    load_payload, validate_payload)

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
            "history": []}


def load_state():
    st = default_state()
    if STATE_FILE.exists():
        try:
            st.update(json.loads(STATE_FILE.read_text()))
        except Exception:
            pass
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
        "video": job.get("video") if
        (VIDEO_DIR / f"{key}_final.mp4").exists() else None,
        "url": job.get("url"),
        "upload": job.get("upload"),
    }


@app.get("/api/state")
def api_state():
    with _lock:
        days = [_day_info(k) for k in day_keys()]
        return jsonify({"days": days, "schedule": state["schedule"],
                        "history": state["history"][:10],
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
