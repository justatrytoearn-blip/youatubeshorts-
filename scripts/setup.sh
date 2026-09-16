#!/usr/bin/env bash
# One-time setup: python deps + ffmpeg + env file. Multi-platform.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "== [1/3] python packages =="
python3 -m pip install -q -r requirements.txt || \
python3 -m pip install -q --break-system-packages -r requirements.txt

echo "== [2/3] ffmpeg =="
if ! command -v ffmpeg >/dev/null; then
  if command -v apt-get >/dev/null; then sudo apt-get update -y && sudo apt-get install -y ffmpeg
  elif command -v dnf >/dev/null; then sudo dnf install -y ffmpeg
  elif command -v pacman >/dev/null; then sudo pacman -S --noconfirm ffmpeg
  elif command -v pkg >/dev/null; then pkg install -y ffmpeg
  elif command -v brew >/dev/null; then brew install ffmpeg
  else echo "Install ffmpeg manually: https://ffmpeg.org/download.html"; fi
else
  echo "ffmpeg already installed"
fi

echo "== [3/3] config =="
if [ ! -f config/.env ]; then
  cp config/env.example config/.env
  echo ">>> EDIT config/.env NOW: Pexels key + YouTube OAuth creds"
else
  echo "config/.env already exists"
fi

echo "setup done. next: bash start_here.sh (interactive) or see GUIDE.md"
