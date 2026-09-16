"""YouTube Shorts uploader via official YouTube Data API v3.

One-time OAuth flow:
  1. Create a Google Cloud project, enable "YouTube Data API v3".
  2. Create OAuth Client ID (Desktop app), put credentials in config/.env.
  3. First run opens a browser for consent; token saved to config/token.json
     and auto-refreshed afterwards.

Install: python -m pip install google-api-python-client google-auth-oauthlib
"""
import json
import os
import sys
from pathlib import Path

from common import BASE_DIR, load_env, setup_logging

load_env()
log = setup_logging("upload")

TOKEN_FILE = BASE_DIR / "config" / "token.json"
SCOPES = ["https://www.googleapis.com/auth/youtube.upload",
          "https://www.googleapis.com/auth/youtube.readonly"]


def get_service():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    client_config = {
        "installed": {
            "client_id": os.environ["YT_CLIENT_ID"],
            "client_secret": os.environ["YT_CLIENT_SECRET"],
            "redirect_uris": ["http://localhost:1"],
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }
    creds = None
    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    if not creds or not creds.valid:
        flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
        creds = flow.run_local_server(port=1, open_browser=False,
                                      success_message="You can close this tab.")
    TOKEN_FILE.write_text(creds.to_json())
    from googleapiclient.discovery import build
    return build("youtube", "v3", credentials=creds)


def upload_short(video_path: Path, payload: dict) -> str:
    """Upload video as a Short; returns videoId."""
    meta = payload["metadata"]
    tags = meta.get("tags", [])
    body = {
        "snippet": {
            # Title stays <=100 chars; #Shorts drives the Shorts shelf.
            "title": meta["title"][:100],
            "description": meta["description"][:5000],
            "tags": tags,
            "categoryId": "27",  # Education
        },
        "status": {
            "privacyStatus": "public",
            "selfDeclaredMadeForKids": False,
            "notifySubscribers": True,
        },
    }
    from googleapiclient.http import MediaFileUpload

    media = MediaFileUpload(str(video_path), chunksize=8 * 1024 * 1024,
                            resumable=True, mimetype="video/mp4")
    yt = get_service()
    request = yt.videos().insert(
        part="snippet,status", body=body, media_body=media)
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            log.info("upload %.0f%%", status.progress() * 100)
    vid = response["id"]
    log.info("UPLOADED %s -> https://youtube.com/shorts/%s",
             video_path.name, vid)
    return vid


def main():
    if len(sys.argv) < 3:
        raise SystemExit("usage: python upload.py <video.mp4> <day_key>")
    video = Path(sys.argv[1])
    day = sys.argv[2]
    from common import load_payload
    payload = load_payload(day)
    if os.environ.get("DRY_RUN", "false").lower() == "true":
        log.info("DRY_RUN=true - skipping upload of %s", video)
        return
    upload_short(video, payload)


if __name__ == "__main__":
    main()
