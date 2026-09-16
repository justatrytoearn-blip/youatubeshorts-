"""Scheduler loop: run daily.py once per day at UPLOAD_HHMM local time.

Run permanently on a always-on machine:
    nohup python modules/scheduler.py > logs/scheduler.log 2>&1 &

For servers prefer cron (see scripts/run_daily.sh + crontab example in README);
this loop is for laptops/Windows where cron is unavailable.
"""
import os
import time
from datetime import datetime, timedelta

from common import load_env, setup_logging

load_env()
log = setup_logging("scheduler")

HHMM = os.environ.get("UPLOAD_HHMM", "17:00")
TZ = os.environ.get("TIMEZONE", "")


def next_run() -> datetime:
    now = datetime.now()
    target = now.replace(hour=int(HHMM[:2]), minute=int(HHMM[3:5]),
                         second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return target


def main():
    log.info("scheduler live; daily run at %s (tz=%s)", HHMM, TZ or "local")
    while True:
        target = next_run()
        log.info("next run: %s", target)
        while datetime.now() < target:
            time.sleep(30)
        try:
            import subprocess
            from pathlib import Path
            here = Path(__file__).resolve().parent
            subprocess.run(["python", str(here / "daily.py")], check=True)
        except Exception as exc:  # noqa: BLE001
            log.error("daily run failed: %s", exc)


if __name__ == "__main__":
    main()
