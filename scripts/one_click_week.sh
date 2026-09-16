#!/usr/bin/env bash
# Renders all 7 videos in one go (no uploads). Great first test.
set -euo pipefail
cd "$(dirname "$0")/.."
export DRY_RUN=true

for day in day1_monday day2_tuesday day3_wednesday day4_thursday \
           day5_friday day6_saturday day7_sunday; do
  echo "===== $day ====="
  python modules/daily.py "$day"
done
echo "All 7 videos in output/videos/"
