"""Daily orchestrator: TTS -> assets -> render -> upload, for one day.

Usage:
  python modules/daily.py            # auto-detects today's weekday payload
  python modules/daily.py day3_wednesday
Env:
  DRY_RUN=true   -> build only, skip upload
"""
import os
import sys
from pathlib import Path

from common import VIDEO_DIR, day_from_date, load_env, load_payload, setup_logging

load_env()
log = setup_logging("daily")


def run_step(cmd, cwd=None):
    import subprocess
    cmd = [sys.executable] + cmd[1:] if cmd[0] == "python" else cmd
    log.info("STEP: %s", " ".join(cmd))
    proc = subprocess.run(cmd, cwd=cwd)
    if proc.returncode != 0:
        raise SystemExit(f"step failed: {' '.join(cmd)}")


def main():
    here = Path(__file__).resolve().parent
    day = sys.argv[1] if len(sys.argv) > 1 else day_from_date()
    payload = load_payload(day)  # validate early
    log.info("=== %s | niche=%s | title=%r ===", day,
             payload.get("selected_niche"),
             payload.get("metadata", {}).get("title"))

    run_step(["python", str(here / "tts_engine.py"), day])
    run_step(["python", str(here / "pexels_assets.py"), day])
    run_step(["python", str(here / "render.py"), day])

    final = VIDEO_DIR / f"{day}_final.mp4"
    if not final.exists():
        raise SystemExit(f"render missing: {final}")

    if os.environ.get("DRY_RUN", "false").lower() == "true":
        log.info("DRY_RUN=true -> keeping local only: %s", final)
        return
    run_step(["python", str(here / "upload.py"), str(final), day])
    log.info("DONE %s", day)


if __name__ == "__main__":
    main()
