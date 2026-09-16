"""Shared helpers: config loading, logging, content validation."""
import json
import logging
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
ENV_FILE = BASE_DIR / "config" / ".env"
CONTENT_DIR = BASE_DIR / "content"
ASSET_DIR = BASE_DIR / "output" / "assets"
VIDEO_DIR = BASE_DIR / "output" / "videos"
LOG_DIR = BASE_DIR / "logs"

for d in (CONTENT_DIR, ASSET_DIR, VIDEO_DIR, LOG_DIR):
    d.mkdir(parents=True, exist_ok=True)


def load_env():
    """Parse config/.env into os.environ (no external deps)."""
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


def setup_logging(name: str) -> logging.Logger:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(LOG_DIR / f"{name}.log"),
            logging.StreamHandler(sys.stdout),
        ],
    )
    return logging.getLogger(name)


def load_payload(day: str) -> dict:
    path = CONTENT_DIR / f"{day}.json"
    if not path.exists():
        raise FileNotFoundError(f"No content payload for {day}: {path}")
    data = json.loads(path.read_text())
    validate_payload(data, path.name)
    return data


def validate_payload(data: dict, name: str = ""):
    """Fail fast on malformed content payloads before spending API credits."""
    scenes = data.get("video_pipeline") or []
    if not scenes:
        raise ValueError(f"{name}: video_pipeline empty")
    total = 0.0
    words = 0
    for i, s in enumerate(scenes, 1):
        for key in ("narration_audio_text", "visual_generation_prompt",
                    "on_screen_text_overlay", "duration_seconds"):
            if key not in s:
                raise ValueError(f"{name} scene {i}: missing {key}")
        d = float(s["duration_seconds"])
        if not 3.5 <= d <= 6.0:
            raise ValueError(f"{name} scene {i}: duration {d} outside 3.5-6.0")
        total += d
        words += len(s["narration_audio_text"].split())
    if not 40 <= total <= 62:
        raise ValueError(f"{name}: total duration {total}s outside 40-62s")
    if not 100 <= words <= 135:
        raise word_count_error(name, words)
    meta = data.get("metadata") or {}
    if len(meta.get("title", "")) > 100:
        raise ValueError(f"{name}: title exceeds YouTube 100 char limit")


def word_count_error(name: str, words: int) -> ValueError:
    return ValueError(f"{name}: narration word count {words} outside 100-135")


def day_from_date(d=None) -> str:
    import datetime
    d = d or datetime.date.today()
    return ["monday", "tuesday", "wednesday", "thursday", "friday",
            "saturday", "sunday"][d.weekday()]


def today_key() -> str:
    import datetime
    return datetime.date.today().isoformat()
