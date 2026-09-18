"""YouTube Shorts uploader - pure Python, no google-* packages.

Those packages pull in compiled cryptography wheels that fail on Termux
with "dlopen failed: cannot locate symbol" - yt_client.py avoids them
entirely by speaking OAuth + resumable-upload HTTP directly.

CLI (also used by the scheduler and web console):
    python upload.py <video.mp4> <day_key>

One-time consent: on first run a link is printed; open it, approve, and
the browser redirect is caught automatically (or paste the redirect URL).
Token is saved to config/token.json and refreshed automatically.
"""
import json
import sys
from pathlib import Path

from common import BASE_DIR, load_env, setup_logging

load_env()
log = setup_logging("upload")

sys.path.insert(0, str(Path(__file__).resolve().parent))
import yt_client  # noqa: E402


def main():
    if len(sys.argv) < 3:
        raise SystemExit("usage: python upload.py <video.mp4> <day_key>")
    video = Path(sys.argv[1])
    day = sys.argv[2]

    from common import load_payload
    payload = load_payload(day)

    import os
    if os.environ.get("DRY_RUN", "false").lower() == "true":
        log.info("DRY_RUN=true - skipping upload of %s", video)
        return
    if not yt_client.creds_available():
        log.info("No YouTube token yet - starting one-time consent flow.")
        yt_client.connect_interactive()

    vid = yt_client.upload_short(
        video, payload.get("metadata", {}),
        log=lambda *a, **k: log.info(*a, **k))
    log.info("UPLOADED %s -> https://youtube.com/shorts/%s",
             video.name, vid)


if __name__ == "__main__":
    main()
