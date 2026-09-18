"""Render engine: burns narration + music + captions + overlays into a
1080x1920 vertical MP4 using FFmpeg only (no MoviePy needed).

Inputs per day (produced by tts_engine.py + pexels_assets.py):
  output/assets/<day>/audio/scene_<id>.mp3
  output/assets/<day>/audio_durations.json
  output/assets/<day>/video/scene_<id>.mp4
  output/assets/<day>/music.mp3            (optional)

Output:
  output/videos/<day>_final.mp4
"""
import json
import subprocess
import sys
from pathlib import Path

from common import ASSET_DIR, VIDEO_DIR, load_payload, setup_logging

log = setup_logging("render")

W, H, FPS = 1080, 1920, 30


def run(cmd):
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"cmd failed: {' '.join(cmd)}\n{proc.stderr[-2000:]}")
    return proc


def probe_duration(path) -> float:
    out = run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
               "-of", "json", str(path)])
    return float(json.loads(out.stdout)["format"]["duration"])


def ensure_clip(src: Path, duration: float, tmp: Path,
                anim_sig: str = "") -> Path:
    """Normalize any stock clip: crop/scale to 1080x1920, loop if too short."""
    out = tmp / f"{src.stem}_{anim_sig or 'static'}_norm.mp4"
    vf = (
        f"scale={W}:{H}:force_original_aspect_ratio=increase,"
        f"crop={W}:{H},"
        f"fps={FPS},"
        "setsar=1"
    )
    run([
        "ffmpeg", "-y", "-stream_loop", "-1", "-i", str(src),
        "-t", f"{duration:.2f}", "-vf", vf, "-an",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-pix_fmt", "yuv420p", str(out),
    ])
    return out


def _find_font() -> str:
    """Pick a font that supports non-Latin captions when available."""
    import os
    for cand in (
            os.environ.get("CAPTION_FONT", ""),
            "/system/fonts/NotoSansCJK-Regular.ttc",
            "/system/fonts/NotoSansDevanagari-Regular.ttf",
            "/system/fonts/NotoSansArabic-Regular.ttf",
            "/system/fonts/NotoSansBengali-Regular.ttf",
            "/system/fonts/NotoSansTamil-Regular.ttf",
            "/system/fonts/NotoSansThai-Regular.ttf",
            "/system/fonts/DroidSansFallback.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
    ):
        if cand and Path(cand).exists():
            return cand
    return ""


def _motion_for(style: str, dur: float) -> str:
    """Ken-Burns style motion chain applied after crop (subtle, no shake)."""
    st = (style or "static").lower()
    frames = max(int(dur * 30), 30)
    if st == "zoom-in":
        return (f",zoompan=z='min(zoom+0.0008,1.15)':d={frames}:"
                "x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1080x1920:fps=30")
    if st == "zoom-out":
        return (f",zoompan=z='if(lte(zoom,1.0),1.15,max(1.001,zoom-0.0008))':"
                f"d={frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
                "s=1080x1920:fps=30")
    if st == "pan-up":
        return (f",crop=1080:1920:0:'max(0,(ih-1920)*(1-t/{max(dur, .1):.2f}))'")
    if st == "pan-down":
        return (f",crop=1080:1920:0:'(ih-1920)*t/{max(dur, .1):.2f}'")
    return ""


def burn_scene(video: Path, audio: Path, text: str, tmp: Path, idx: int,
               scene_duration: float, motion: str = "static") -> Path:
    """Concat-ready scene: stock video + narration + caption + motion."""
    out = tmp / f"scene_{idx}.mp4"
    safe = (text.replace("\\", "\\\\").replace(":", "\\:")
            .replace("'", "\\\u2019").replace("%", "\\%"))
    font = _find_font()
    font_opt = f"fontfile={font}:" if font else ""
    drawtext = (
        f"drawtext={font_opt}text='{safe}':"
        f"fontcolor=white:fontsize=64:borderw=4:bordercolor=black@0.8:"
        f"x=(w-text_w)/2:y=h-360:"
        f"box=1:boxcolor=black@0.35:boxborderw=22"
    )
    motion_chain = _motion_for(motion, scene_duration)
    run([
        "ffmpeg", "-y",
        "-i", str(video), "-i", str(audio),
        "-vf", f"fps=30,scale=1080:1920:force_original_aspect_ratio=increase,"
               f"crop=1080:1920,setsar=1{motion_chain},{drawtext}",
        "-map", "0:v", "-map", "1:a",
        "-t", f"{scene_duration:.2f}",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-ar", "44100",
        "-shortest",
        str(out),
    ])
    if not out.exists() or out.stat().st_size < 10_000:
        raise RuntimeError(f"scene render failed: {out}")
    return out


def concat(scenes: list, tmp: Path) -> Path:
    listing = tmp / "concat.txt"
    listing.write_text("".join(f"file '{p}'\n" for p in scenes))
    out = tmp / "concat.mp4"
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(listing),
         "-c", "copy", str(out)])
    return out


def mix_music(video: Path, music, gain_db: float, out: Path):
    """Duck music under narration via sidechain, or lay it flat if no music."""
    if music:
        fc = (
            f"[1:a]volume={gain_db}db[m];"
            "[0:a][m]amix=inputs=2:duration=first:dropout_transition=3,"
            "loudnorm=I=-14:TP=-1.5:LRA=11[a]"
        )
        run(["ffmpeg", "-y", "-i", str(video), "-i", str(music),
             "-filter_complex", fc, "-map", "0:v", "-map", "[a]",
             "-c:v", "copy",
             "-c:a", "aac", "-b:a", "192k", str(out)])
    else:
        run(["ffmpeg", "-y", "-i", str(video), "-c", "copy", str(out)])


def render_day(day: str) -> Path:
    payload = load_payload(day)
    a_dir = ASSET_DIR / day
    audio_dir = a_dir / "audio"
    video_dir = a_dir / "video"
    tmp = VIDEO_DIR / f"tmp_{day}"
    tmp.mkdir(parents=True, exist_ok=True)

    durations = json.loads((a_dir / "audio_durations.json").read_text())
    asset_map = json.loads((video_dir / "asset_map.json").read_text())
    music = a_dir / "music.mp3"
    music = music if music.exists() else None
    prof = payload.get("audio_profile", {})
    try:
        gain = float(prof.get("music_volume_db", -18.0))
    except (TypeError, ValueError):
        gain = -18.0

    scene_files = []
    for scene in payload["video_pipeline"]:
        sid = str(scene["scene_id"])
        narration = audio_dir / f"scene_{sid}.mp3"
        clip = video_dir / f"scene_{sid}.mp4"
        if not narration.exists() or sid not in asset_map:
            raise FileNotFoundError(f"missing assets for scene {sid} of {day}; "
                                    "run tts_engine.py + pexels_assets.py first")
        narr_dur = float(durations[sid])
        # Scene length = max(planned, narration + padding). Narration is
        # never clipped: if TTS runs long the scene stretches to fit.
        target = max(float(scene["duration_seconds"]), narr_dur + 0.45)
        anim = str(scene.get("animation_style",
                             prof.get("animation_style", "static")))
        norm = ensure_clip(clip, target, tmp, anim_sig=anim.replace("-", ""))
        burned = burn_scene(Path(asset_map[sid]["path"]), narration,
                            scene["on_screen_text_overlay"], tmp, sid,
                            target, motion=scene.get("animation_style",
                                                     prof.get("animation_style",
                                                              "static")))
        scene_files.append(burned)

    final_raw = concat(scene_files, tmp)
    out = VIDEO_DIR / f"{day}_final.mp4"
    mix_music(final_raw, music, gain, out)
    log.info("RENDER OK %s -> %s (%.1fs)", day, out, probe_duration(out))
    return out


def main():
    day = sys.argv[1] if len(sys.argv) > 1 else None
    if not day:
        raise SystemExit("usage: python render.py <day_key>")
    render_day(day)


if __name__ == "__main__":
    main()
