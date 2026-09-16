#!/usr/bin/env bash
# Daily entrypoint used by cron / systemd / Task Scheduler.
# Crontab line (17:00 daily):
#   0 17 * * * /root/shorts-pipeline/scripts/run_daily.sh >> /root/shorts-pipeline/logs/cron.log 2>&1
set -euo pipefail

PIPELINE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PIPELINE_DIR"

# Export everything in config/.env (values may be quoted)
set -a
[ -f config/.env ] && . ./config/.env
set +a

# Right timezone so "today's" weekday payload matches the user's calendar
export TZ="${TIMEZONE:-UTC}"

DAY="${1:-}"
if [ -z "$DAY" ]; then
  DAY=$(TZ="$TZ" date +%A | tr '[:upper:]' '[:lower:]')
  case "$DAY" in
    monday) DAY="day1_monday" ;;
    tuesday) DAY="day2_tuesday" ;;
    wednesday) DAY="day3_wednesday" ;;
    thursday) DAY="day4_thursday" ;;
    friday) DAY="day5_friday" ;;
    saturday) DAY="day6_saturday" ;;
    sunday) DAY="day7_sunday" ;;
  esac
fi

mkdir -p logs
python3 modules/daily.py "$DAY" 2>&1 | tee -a "logs/$(date +%F)_run.log"
