"""Pexels/Pixabay stock fetcher: videos + background music.

Free tiers only. Env: Pexels-API-Key (Pexels API secret key).
Pixabay key optional: PIXABAY_KEY env var (music fallback).

Docs: https://www.pexels.com/api/documentation/#videos
"""
import json
import os
import shutil
import subprocess

import requests

from common import ASSET_DIR, load_env, setup_logging

load_env()
log = setup_logging("assets")

PEXELS_VIDEO_URL = "https://api.pexels.com/videos/search"
PEXELS_PHOTO_URL = "https://api.pexels.com/v1/search"
PIXABAY_MUSIC_URL = "https://pixabay.com/api/?type=music"

UA = {"User-Agent": "shorts-pipeline/1.0"}


def pexels_key():
    key = os.environ.get("Pexels-API-Key") or os.environ.get("PEXELS_API_KEY")
    if not key or "REPLACE" in key:
        raise SystemExit("Set Pexels-API-Key in config/.env (get one free at "
                         "https://www.pexels.com/api/)")
    return key


def _retry(fn, tries=3, base=2.0):
    """Retry helper with backoff for flaky mobile networks."""
    import time
    last = None
    for i in range(tries):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001
            last = exc
            if i < tries - 1:
                time.sleep(base * (2 ** i))
    raise last


def search_videos(query: str, per_page: int = 10, orientation: str = "portrait"):
    """Return list of candidate video files (portrait, HD)."""
    def _call():
        r = requests.get(
            PEXELS_VIDEO_URL,
            headers={"Authorization": pexels_key(), **UA},
            params={"query": query, "per_page": per_page,
                    "orientation": orientation},
            timeout=30,
        )
        r.raise_for_status()
        return r
    r = _retry(_call)
    results = []
    for vid in r.json().get("videos", []):
        files = vid.get("video_files", [])
        # prefer portrait hd mp4, smallest >= 720p
        files = [f for f in files if f.get("file_type") == "video/mp4"]
        portrait = [f for f in files if (f.get("height") or 0) >= 1280
                    and (f.get("width") or 0) < (f.get("height") or 0)]
        pool = portrait or files
        if not pool:
            continue
        pool.sort(key=lambda f: f.get("height") or 0)
        results.append({
            "pexels_id": vid.get("id"),
            "url": pool[-1].get("link"),
            "duration": vid.get("duration", 10),
            "query": query,
        })
    return results


def download(url: str, dest) -> str:
    dest = str(dest)

    def _call():
        with requests.get(url, stream=True, timeout=120, headers=UA) as r:
            r.raise_for_status()
            with open(dest + ".part", "wb") as fh:
                shutil.copyfileobj(r.raw, fh)
        return True

    _retry(_call)
    os.replace(dest + ".part", dest)
    return dest


def fetch_scene_assets(day: str, payload: dict) -> dict:
    """Download one background clip per scene. Returns {scene_id: path}."""
    day_dir = ASSET_DIR / day / "video"
    day_dir.mkdir(parents=True, exist_ok=True)
    cache_file = day_dir / "asset_map.json"
    cache = json.loads(cache_file.read_text()) if cache_file.exists() else {}

    used_ids = set(v.get("pexels_id") for v in cache.values())
    mapping = {}
    for scene in payload["video_pipeline"]:
        sid = scene["scene_id"]
        if sid in cache:
            mapping[sid] = cache[sid]
            continue
        query = scene["visual_generation_prompt"]
        candidates = search_videos(query)
        picked = None
        for cand in candidates:
            if cand["pexels_id"] in used_ids:
                continue  # avoid repeating same clip within one Short
            picked = cand
            break
        if picked is None and candidates:
            picked = candidates[0]
        if picked is None:
            log.warning("no video for scene %s query=%r", sid, query)
            continue
        ext = ".mp4"
        dest = day_dir / f"scene_{sid}{ext}"
        if not dest.exists():
            download(picked["url"], dest)
        used_ids.add(picked["pexels_id"])
        mapping[sid] = {"path": str(dest), "pexels_id": picked["pexels_id"],
                        "query": query}
        log.info("scene %s <- pexels %s (%s)", sid, picked["pexels_id"], query)

    cache_file.write_text(json.dumps(mapping, indent=2))
    return mapping


def fetch_music(payload: dict, day: str):
    """Fetch a background music track. Pixabay music (free) or local fallback."""
    vibe = payload.get("audio_profile", {}).get("bg_music_vibe", "dark cinematic")
    day_dir = ASSET_DIR / day
    out = day_dir / "music.mp3"
    if out.exists():
        return str(out)
    key = os.environ.get("PIXABAY_KEY")
    if key:
        try:
            r = requests.get(PIXABAY_MUSIC_URL,
                             params={"key": key, "q": vibe.split()[0], "per_page": 5},
                             timeout=30)
            r.raise_for_status()
            hits = r.json().get("hits", [])
            if hits:
                download(hits[0]["audio"], out)
                log.info("music from pixabay: %s", hits[0].get("tags"))
                return str(out)
        except Exception as exc:  # noqa: BLE001
            log.warning("pixabay music failed: %s", exc)
    log.warning("no PIXABAY_KEY set or no hit; render will proceed without music")
    return None


def main():
    import sys
    from common import load_payload
    day = sys.argv[1] if len(sys.argv) > 1 else None
    if not day:
        raise SystemExit("usage: python pexels_assets.py <day_key>")
    payload = load_payload(day)
    mapping = fetch_scene_assets(day, payload)
    fetch_music(payload, day)
    log.info("assets ready for %s: %d scenes", day, len(mapping))


if __name__ == "__main__":
    main()
