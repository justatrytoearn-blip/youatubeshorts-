#!/usr/bin/env bash
# ============================================================
#  START HERE - one command bootstrap for absolute beginners
#  Usage:  bash start_here.sh
#  Asks you for API keys interactively, installs everything,
#  runs the doctor, then offers a first test render.
# ============================================================
set -euo pipefail
cd "$(dirname "$0")"

echo ""
echo "=========================================="
echo "   YOUTUBE SHORTS PIPELINE - START HERE   "
echo "=========================================="

# ---- 1. python + ffmpeg ------------------------------------
echo ""
echo "[1/5] Checking system tools..."
if ! command -v python3 >/dev/null; then
  echo "python3 missing - trying to install..."
  if command -v apt-get >/dev/null; then sudo apt-get update -y && sudo apt-get install -y python3 python3-pip
  elif command -v dnf >/dev/null; then sudo dnf install -y python3 python3-pip
  elif command -v pacman >/dev/null; then sudo pacman -S --noconfirm python python-pip
  elif command -v pkg >/dev/null; then pkg install -y python
  elif command -v brew >/dev/null; then brew install python
  else echo "Install Python 3.10+ manually from https://python.org"; exit 1; fi
fi
python3 -m pip --version >/dev/null 2>&1 || python3 -m ensurepip --upgrade

if ! command -v ffmpeg >/dev/null; then
  echo "ffmpeg missing - trying to install..."
  if command -v apt-get >/dev/null; then sudo apt-get update -y && sudo apt-get install -y ffmpeg
  elif command -v dnf >/dev/null; then sudo dnf install -y ffmpeg
  elif command -v pacman >/dev/null; then sudo pacman -S --noconfirm ffmpeg
  elif command -v pkg >/dev/null; then pkg install -y ffmpeg
  elif command -v brew >/dev/null; then brew install ffmpeg
  else echo "Install ffmpeg manually: https://ffmpeg.org/download.html"; exit 1; fi
fi
echo "python3 + ffmpeg ready."

# ---- 2. python packages ------------------------------------
echo ""
echo "[2/5] Installing python packages..."
python3 -m pip install -q -r requirements.txt || \
python3 -m pip install -q --break-system-packages -r requirements.txt
echo "packages ready."

# ---- 3. config/.env ----------------------------------------
echo ""
echo "[3/5] Setting up config/.env..."
mkdir -p config
if [ ! -f config/.env ]; then
  cp config/env.example config/.env
fi

ask_key() {
  local var="$1" prompt="$2" current
  current=$(grep -E "^${var}=" config/.env | head -1 | cut -d= -f2- | tr -d '"' || true)
  if [ -n "$current" ] && [[ "$current" != *"REPLACE"* ]]; then
    echo "  $var already set - skipping (delete line in config/.env to re-enter)"
    return
  fi
  echo "  $prompt"
  read -r -p "  > " val
  if [ -n "$val" ]; then
    if grep -qE "^${var}=" config/.env; then
      python3 - "$var" "$val" <<'PYEOF'
import re, sys
var, val = sys.argv[1], sys.argv[2]
p = "config/.env"
text = open(p).read()
text = re.sub(rf'(?m)^{var}=.*$', f'{var}="{val}"', text)
open(p, "w").write(text)
PYEOF
    fi
  fi
}

ask_key "Pexels-API-Key" "Paste your FREE Pexels API key (get: https://www.pexels.com/api/)"
ask_key "YT_CLIENT_ID" "Paste YouTube OAuth Client ID (or press Enter to skip - uploads will be skipped)"
ask_key "YT_CLIENT_SECRET" "Paste YouTube OAuth Client Secret (or press Enter to skip)"

read -r -p "Daily upload time (HH:MM, default 17:00): " uph
if [ -n "${uph:-}" ]; then
  python3 - "$uph" <<'PYEOF'
import re, sys
val = sys.argv[1]
p = "config/.env"
text = open(p).read()
text = re.sub(r'(?m)^UPLOAD_HHMM=.*$', f'UPLOAD_HHMM="{val}"', text)
open(p, "w").write(text)
PYEOF
fi

# ---- 4. doctor ---------------------------------------------
echo ""
echo "[4/5] Running doctor (environment check)..."
python3 modules/doctor.py || true

# ---- 5. first test render ----------------------------------
echo ""
echo "[5/5] Optional first test render (Monday video, no upload)..."
read -r -p "Build a test video now? [y/N]: " go
if [[ "${go:-}" == "y" || "${go:-}" == "Y" ]]; then
  DRY_RUN=true python3 modules/daily.py day1_monday
  echo ""
  echo "Test video: output/videos/day1_monday_final.mp4"
fi

echo ""
echo "=========================================="
echo " Done! Full guide: GUIDE.md"
echo " Quick reference:  README.md"
echo "=========================================="
