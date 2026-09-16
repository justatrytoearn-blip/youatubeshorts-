"""Narration generator. Uses edge-tts (free Microsoft neural voices).

python -m pip install edge-tts
"""
import asyncio
import json
import re
from pathlib import Path

from common import ASSET_DIR, load_env, setup_logging

load_env()
log = setup_logging("tts")

# Voice map: content voice-style -> edge-tts voice id
VOICE_MAP = {
    "authoritative": "en-US-GuyNeural",       # deep male
    "documentary": "en-US-ChristopherNeural",  # deeper documentary
    "conversational": "en-US-BrandonNeural",   # energetic young male
    "whisper": "en-US-DavisNeural",
    "female": "en-US-JennyNeural",
}
FALLBACK_VOICE = "en-US-GuyNeural"

# edge-tts rate offsets tuned so 100-130 word scripts land at 45-55s
# (measured: fragment-heavy lines with many periods add pauses, so the
# base offsets are deliberately punchy)
RATE_MAP = {1.0: "+15%", 1.1: "+25%", 1.15: "+30%", 1.2: "+35%", 1.25: "+40%"}


def pick_voice(style_text: str) -> str:
    s = style_text.lower()
    for key, voice in VOICE_MAP.items():
        if key in s:
            return voice
    return FALLBACK_VOICE


async def synth_scene(text: str, voice: str, rate: str, out_path: Path) -> Path:
    """Synthesize one scene with retries (mobile networks drop mid-stream)."""
    import edge_tts
    delays = [2, 5, 10]
    last_exc = None
    for attempt in range(1 + len(delays)):
        try:
            communicate = edge_tts.Communicate(text, voice, rate=rate)
            await communicate.save(str(out_path))
            if out_path.exists() and out_path.stat().st_size > 1024:
                return out_path
            raise RuntimeError("edge-tts wrote no/short audio")
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt < len(delays):
                wait = delays[attempt]
                log.warning("tts attempt %d failed (%s); retrying in %ds",
                            attempt + 1, type(exc).__name__, wait)
                await asyncio.sleep(wait)
    raise last_exc


async def build_day_audio(day: str, payload: dict) -> dict:
    """Generate one mp3 per scene. Returns {scene_id: (mp3_path, duration)}."""
    import mutagen  # pip install mutagen  (duration probing)

    profile = payload.get("audio_profile", {})
    voice = pick_voice(profile.get("recommended_voice_style", ""))
    pace = float(profile.get("pace_multiplier", 1.0))
    rate = RATE_MAP.get(pace, "+10%")

    day_dir = ASSET_DIR / day / "audio"
    day_dir.mkdir(parents=True, exist_ok=True)

    durations = {}
    for scene in payload["video_pipeline"]:
        sid = scene["scene_id"]
        mp3 = day_dir / f"scene_{sid}.mp3"
        if mp3.exists() and mp3.stat().st_size > 1024:
            # resume support: skip scenes already synthesized
            probe = mutagen.File(str(mp3))
            durations[sid] = probe.info.length
            log.info("day=%s scene=%s cached (%.2fs)", day, sid, durations[sid])
            continue
        await synth_scene(scene["narration_audio_text"], voice, rate, mp3)
        probe = mutagen.File(str(mp3))
        durations[sid] = probe.info.length
        log.info("day=%s scene=%s voice=%s dur=%.2fs", day, sid, voice,
                 durations[sid])
    return durations


def main():
    import sys
    day = sys.argv[1] if len(sys.argv) > 1 else None
    if not day:
        log.error("usage: python tts_engine.py <day_key e.g. day1_monday>")
        sys.exit(2)
    from common import load_payload
    payload = load_payload(day)
    durs = asyncio.run(build_day_audio(day, payload))
    (ASSET_DIR / day / "audio_durations.json").write_text(
        json.dumps(durs, indent=2))
    log.info("audio complete for %s", day)


if __name__ == "__main__":
    main()
