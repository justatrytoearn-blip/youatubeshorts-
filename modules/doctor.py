"""Pre-flight doctor: verifies every dependency the pipeline needs.

Run:  python3 modules/doctor.py
Exit code 0 = green light. 1 = something needs fixing (it tells you what).
"""
import importlib
import shutil
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import BASE_DIR as ROOT  # noqa: E402
from common import load_env  # noqa: E402

GREEN, YELLOW, RED, RESET = "\033[92m", "\033[93m", "\033[91m", "\033[0m"
OK, WARN, FAIL = f"{GREEN}[OK]{RESET}", f"{YELLOW}[..]{RESET}", f"{RED}[X]{RESET}"

results = {"ok": 0, "warn": 0, "fail": 0}


def line(status, msg, fix=""):
    print(f"  {status} {msg}")
    if fix:
        print(f"       fix: {fix}")
    if status == OK:
        results["ok"] += 1
    elif status == WARN:
        results["warn"] += 1
    else:
        results["fail"] += 1


def check_ffmpeg():
    if shutil.which("ffmpeg") is None:
        line(FAIL, "ffmpeg not found",
             "bash scripts/setup.sh (or install ffmpeg for your OS)")
    else:
        line(OK, "ffmpeg installed")


def check_python_deps():
    for mod, pip_name in [("requests", "requests"),
                          ("edge_tts", "edge-tts"),
                          ("mutagen", "mutagen")]:
        try:
            importlib.import_module(mod)
            line(OK, f"python package: {pip_name}")
        except ImportError:
            line(FAIL, f"python package missing: {pip_name}",
                 "python3 -m pip install -r requirements.txt")


def check_env():
    env_file = ROOT / "config" / ".env"
    if not env_file.exists():
        line(FAIL, "config/.env missing",
             "cp config/env.example config/.env  then edit it")
        return
    line(OK, "config/.env exists")
    load_env()
    import os
    pex = os.environ.get("Pexels-API-Key", "")
    if not pex or "REPLACE" in pex:
        line(FAIL, "Pexels API key not set",
             "free key: https://www.pexels.com/api/ -> put in config/.env")
    else:
        line(OK, "Pexels API key set")

    yt_id = os.environ.get("YT_CLIENT_ID", "")
    yt_sec = os.environ.get("YT_CLIENT_SECRET", "")
    if "REPLACE" in yt_id or "REPLACE" in yt_sec:
        line(WARN, "YouTube OAuth creds not set (uploads will fail; local "
                   "renders still work)",
             "see GUIDE.md section 4: create Google Cloud OAuth client")
    else:
        line(OK, "YouTube OAuth creds set")


def check_content():
    from common import CONTENT_DIR
    import json
    days = sorted(CONTENT_DIR.glob("day*.json"))
    if not days:
        line(FAIL, "no content payloads in content/")
        return
    for p in days:
        try:
            data = json.loads(p.read_text())
            n = len(data["video_pipeline"])
            line(OK, f"content/{p.name}: {n} scenes")
        except Exception as exc:  # noqa: BLE001
            line(FAIL, f"content/{p.name} invalid: {exc}")


def check_write_dirs():
    for d in ("output/assets", "output/videos", "logs"):
        try:
            (ROOT / d).mkdir(parents=True, exist_ok=True)
            probe = ROOT / d / ".probe"
            probe.write_text("x")
            probe.unlink()
            line(OK, f"writable: {d}/")
        except OSError as exc:
            line(FAIL, f"not writable: {d}/ ({exc})")


def main():
    print("\n=== SHORTS PIPELINE DOCTOR ===")
    check_ffmpeg()
    check_python_deps()
    check_env()
    check_content()
    check_write_dirs()
    print("")
    if results["fail"]:
        print(f"{RED}Doctor found {results['fail']} blocker(s). "
              f"Fix the [X] items above, then rerun.{RESET}")
        sys.exit(1)
    print(f"{GREEN}All blockers clear. Next: python3 modules/daily.py "
          f"day1_monday (DRY_RUN=true first!){RESET}")
    sys.exit(0)


if __name__ == "__main__":
    main()
