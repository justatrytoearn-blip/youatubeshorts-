"""Narration generator. Uses edge-tts (free Microsoft neural voices).

python -m pip install edge-tts

Voice selection model (audio_profile in each script JSON):
  language       e.g. "en", "hi", "es"  (default "en")
  voice_id       exact edge-tts voice, e.g. "hi-IN-SwaraNeural"
  recommended_voice_style  free text / legacy ("deep male authoritative",
                 "energetic young female", ...) - parsed as fallback
  pace_multiplier          1.0 / 1.15 / 1.25 ... (delivery speed)
  target_seconds           optional: total narration length to aim for;
                           the engine re-synthesizes at adjusted speed if
                           the first pass misses by more than 4 seconds
"""
import asyncio
import json
import os
import re
from pathlib import Path

from common import ASSET_DIR, load_env, setup_logging

load_env()
log = setup_logging("tts")

# (voice_id, label, gender) - natural, expressive voices listed first.
# Gender "child" marks the few genuine child voices edge-tts offers.
VOICE_CATALOG = {
    "en": [
        ("en-US-AndrewNeural", "US • Andrew — deep male, most natural", "male"),
        ("en-US-BrianNeural", "US • Brian — male, casual warm", "male"),
        ("en-US-ChristopherNeural", "US • Christopher — documentary male", "male"),
        ("en-US-GuyNeural", "US • Guy — energetic male", "male"),
        ("en-US-DavisNeural", "US • Davis — calm male", "male"),
        ("en-US-AvaNeural", "US • Ava — female, warm", "female"),
        ("en-US-EmmaNeural", "US • Emma — female, friendly", "female"),
        ("en-US-AriaNeural", "US • Aria — female, energetic", "female"),
        ("en-US-JennyNeural", "US • Jenny — female, conversational", "female"),
        ("en-US-AnaNeural", "US • Ana — child voice", "child"),
        ("en-GB-RyanNeural", "UK • Ryan — male", "male"),
        ("en-GB-SoniaNeural", "UK • Sonia — female", "female"),
        ("en-IN-PrabhatNeural", "India • Prabhat — male", "male"),
        ("en-IN-NeerjaNeural", "India • Neerja — female", "female"),
    ],
    "hi": [
        ("hi-IN-MadhurNeural", "Hindi • Madhur — male", "male"),
        ("hi-IN-SwaraNeural", "Hindi • Swara — female", "female"),
    ],
    "es": [
        ("es-ES-AlvaroNeural", "Spanish (Spain) • Álvaro — male", "male"),
        ("es-ES-ElviraNeural", "Spanish (Spain) • Elvira — female", "female"),
        ("es-MX-JorgeNeural", "Spanish (Mexico) • Jorge — male", "male"),
        ("es-MX-DaliaNeural", "Spanish (Mexico) • Dalia — female", "female"),
    ],
    "pt": [
        ("pt-BR-AntonioNeural", "Portuguese (Brazil) • Antônio — male", "male"),
        ("pt-BR-FranciscaNeural", "Portuguese (Brazil) • Francisca — female",
         "female"),
    ],
    "fr": [
        ("fr-FR-HenriNeural", "French • Henri — male", "male"),
        ("fr-FR-DeniseNeural", "French • Denise — female", "female"),
    ],
    "de": [
        ("de-DE-ConradNeural", "German • Conrad — male", "male"),
        ("de-DE-KatjaNeural", "German • Katja — female", "female"),
    ],
    "id": [
        ("id-ID-ArdiNeural", "Indonesian • Ardi — male", "male"),
        ("id-ID-GadisNeural", "Indonesian • Gadis — female", "female"),
    ],
    "ar": [
        ("ar-SA-HamedNeural", "Arabic • Hamed — male", "male"),
        ("ar-SA-ZariyahNeural", "Arabic • Zariyah — female", "female"),
    ],
    "bn": [
        ("bn-IN-BashkarNeural", "Bengali • Bashkar — male", "male"),
        ("bn-IN-TanishaaNeural", "Bengali • Tanishaa — female", "female"),
    ],
    "ta": [
        ("ta-IN-ValluvarNeural", "Tamil • Valluvar — male", "male"),
        ("ta-IN-PallaviNeural", "Tamil • Pallavi — female", "female"),
    ],
    "ru": [
        ("ru-RU-DmitryNeural", "Russian • Dmitry — male", "male"),
        ("ru-RU-SvetlanaNeural", "Russian • Svetlana — female", "female"),
    ],
    "ja": [
        ("ja-JP-KeitaNeural", "Japanese • Keita — male", "male"),
        ("ja-JP-NanamiNeural", "Japanese • Nanami — female", "female"),
    ],
}
DEFAULT_LANGUAGE = "en"
_env_voice = (os.environ.get("DEFAULT_VOICE") or "").strip()
DEFAULT_VOICE = _env_voice or "en-US-AndrewNeural"
FALLBACK_VOICE = "en-US-GuyNeural"

# legacy style text -> voice (old scripts keep working)
LEGACY_STYLE_MAP = {
    "authoritative": "en-US-AndrewNeural",
    "documentary": "en-US-ChristopherNeural",
    "conversational": "en-US-BrianNeural",
    "whisper": "en-US-DavisNeural",
    "female": "en-US-AvaNeural",
}

# edge-tts rate offsets tuned so 100-130 word scripts land at 45-55s
# (fragment-heavy lines add pauses, so offsets are deliberately punchy)
TUNED_RATES = {1.0: "+15%", 1.1: "+25%", 1.15: "+30%", 1.2: "+35%",
               1.25: "+40%"}


def rate_for(profile: dict) -> str:
    try:
        pace = float(profile.get("pace_multiplier", 1.0) or 1.0)
    except (TypeError, ValueError):
        pace = 1.0
    key = round(pace, 2)
    if key in TUNED_RATES:
        return TUNED_RATES[key]
    pct = int(round((pace - 1) * 100))
    pct = max(-50, min(80, pct))
    return f"{'+' if pct >= 0 else ''}{pct}%"


def voices_for(lang: str) -> list:
    return VOICE_CATALOG.get(str(lang or "en").lower(),
                             VOICE_CATALOG[DEFAULT_LANGUAGE])


def voices_payload() -> dict:
    """Serializable catalog for the console dropdowns."""
    return {"languages": {lang: [{"id": v, "label": lab, "gender": g}
                                  for v, lab, g in voices]
                          for lang, voices in VOICE_CATALOG.items()}}


def pick_voice(profile: dict) -> tuple:
    """Return (voice_id, rate) from an audio_profile dict."""
    lang = str(profile.get("language") or DEFAULT_LANGUAGE).lower()
    rate = rate_for(profile)

    vid = str(profile.get("voice_id") or "").strip()
    if vid:
        return vid, rate

    style = str(profile.get("recommended_voice_style") or "").lower()
    if style:
        want = None
        if "child" in style or "kid" in style:
            want = "child"
        elif "teen" in style or "young" in style:
            want = "teen"
        elif "female" in style or "woman" in style or "girl" in style:
            want = "female"
        elif "male" in style or "man" in style or "boy" in style:
            want = "male"
        pool = voices_for(lang)
        cand = []
        if want in ("female", "male", "child"):
            cand = [v for v, _, g in pool if g == want]
        elif want == "teen":  # no dedicated teen voices; youngest adults
            cand = [v for v, _, g in pool if g in ("male", "female")]
        if "uk" in style or "british" in style:
            cand = [v for v in cand or [p[0] for p in pool]
                    if v.startswith("en-GB")] or \
                   [v for v, _, _ in pool if v.startswith("en-GB")]
        if "india" in style or "indian" in style:
            cand = [v for v in cand or [p[0] for p in pool]
                    if v.startswith("en-IN")] or \
                   [v for v, _, _ in pool if v.startswith("en-IN")]
        prefer = ("Christopher" if "documentary" in style
                  else "Andrew" if "deep" in style else None)
        if prefer:
            for v, _, _ in pool:
                if prefer in v:
                    cand = [v] + [x for x in cand if x != v]
                    break
        if cand:
            return cand[0], rate
        for key, voice in LEGACY_STYLE_MAP.items():
            if key in style:
                return voice, rate
    return DEFAULT_VOICE, rate


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
    """Generate one mp3 per scene. Returns {scene_id: duration_seconds}.

    Honors voice/language/pace changes (re-synthesizes when they change)
    and optional audio_profile.target_seconds (one re-synthesis pass at
    an adjusted rate when the first pass misses the target by >4s).
    """
    import mutagen

    profile = payload.get("audio_profile", {})
    default_voice, rate = pick_voice(profile)

    day_dir = ASSET_DIR / day / "audio"
    day_dir.mkdir(parents=True, exist_ok=True)
    meta_file = day_dir / "voice_meta.json"
    prev = {}
    if meta_file.exists():
        try:
            prev = json.loads(meta_file.read_text())
        except Exception:
            prev = {}

    scenes = payload["video_pipeline"]
    durations = {}

    def scene_voice_for(scene):
        """Per-scene override (scene.voice_profile) or the script default."""
        sp = scene.get("voice_profile") or {}
        if not sp:
            return default_voice, rate
        merged = dict(profile)
        merged.update(sp)
        return pick_voice(merged)

    async def synth_all():
        for scene in scenes:
            sid = str(scene["scene_id"])
            s_voice, s_rate = scene_voice_for(scene)
            mp3 = day_dir / f"scene_{sid}.mp3"
            cached = mp3.exists() and mp3.stat().st_size > 1024
            if cached and prev.get("scenes", {}).get(sid) != s_voice:
                log.info("scene %s voice changed -> re-synthesizing", sid)
                mp3.unlink()
                cached = False
            if cached:
                durations[sid] = mutagen.File(str(mp3)).info.length
                log.info("day=%s scene=%s cached (%.2fs)", day, sid,
                         durations[sid])
                continue
            await synth_scene(scene["narration_audio_text"], s_voice,
                              s_rate, mp3)
            durations[sid] = mutagen.File(str(mp3)).info.length
            log.info("day=%s scene=%s voice=%s rate=%s dur=%.2fs",
                     day, sid, s_voice, s_rate, durations[sid])

    # default voice changed -> old audio is stale
    if prev and (prev.get("voice") != default_voice):
        log.info("voice changed %s -> %s; re-synthesizing %s",
                 prev.get("voice"), default_voice, day)
        for mp3 in day_dir.glob("scene_*.mp3"):
            mp3.unlink()

    await synth_all()

    # optional duration targeting
    try:
        target = float(profile.get("target_seconds") or 0)
    except (TypeError, ValueError):
        target = 0.0
    total = sum(durations.values())
    if target and total and abs(total - target) > 4 and rate:
        cur = int(rate.replace("+", "").replace("%", "") or 0)
        adj = max(-50, min(80, cur + int(round((total / target - 1) * 100))))
        new_rate = f"{'+' if adj >= 0 else ''}{adj}%"
        if new_rate != rate:
            log.info("target=%.0fs got=%.1fs -> adjusting rate to %s",
                     target, total, new_rate)
            rate = new_rate
            durations.clear()
            for mp3 in day_dir.glob("scene_*.mp3"):
                mp3.unlink()
            await synth_all()

    meta_file.write_text(json.dumps({
        "voice": default_voice, "rate": rate,
        "scenes": {str(s["scene_id"]): scene_voice_for(s)[0]
                   for s in scenes}}))
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
