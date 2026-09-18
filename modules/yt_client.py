"""YouTube client: OAuth + uploads + read APIs using ONLY requests.

No google-* packages needed (those break on Termux/Android with dlopen
errors from compiled cryptography wheels). Everything is plain HTTP:

  OAuth loopback flow : consent URL -> browser -> paste redirect URL
                        (a local listener on :1 auto-catches it when possible)
  Token refresh       : POST oauth2.googleapis.com/token
  Resumable upload    : POST uploadType=resumable, then PUT chunks
  Stats/comments      : GET www.googleapis.com/youtube/v3/...

Token is stored in config/token.json and refreshed automatically.

Endpoints can be overridden via env for testing:
  YT_AUTH_URI, YT_TOKEN_URI, YT_API_BASE, YT_UPLOAD_BASE
"""
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

import requests

from common import BASE_DIR, load_env

load_env()

TOKEN_FILE = BASE_DIR / "config" / "token.json"
SCOPES = ["https://www.googleapis.com/auth/youtube.upload",
          "https://www.googleapis.com/auth/youtube.readonly"]
CHUNK = 8 * 1024 * 1024  # 8 MiB


def _cfg(key: str, default: str) -> str:
    return os.environ.get(key, default)


class YouTubeError(RuntimeError):
    pass


# ------------------------------------------------------------------ OAuth ---
def creds_available() -> bool:
    if TOKEN_FILE.exists():
        try:
            return bool(json.loads(TOKEN_FILE.read_text()).get("refresh_token"))
        except Exception:
            return False
    return False


def client_credentials() -> tuple:
    cid = (os.environ.get("YT_CLIENT_ID") or "").strip()
    sec = (os.environ.get("YT_CLIENT_SECRET") or "").strip()
    if not cid or not sec or "REPLACE" in cid:
        raise YouTubeError(
            "YouTube app keys missing. Add YT_CLIENT_ID and YT_CLIENT_SECRET "
            "to config/.env (see GUIDE section 4b).")
    return cid, sec


def consent_url() -> str:
    cid, _ = client_credentials()
    q = urlencode({
        "client_id": cid,
        "redirect_uri": "http://localhost:1",
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",
        "prompt": "consent",
    })
    return _cfg("YT_AUTH_URI",
                "https://accounts.google.com/o/oauth2/auth") + "?" + q


def _exchange(code: str) -> dict:
    cid, sec = client_credentials()
    r = requests.post(_cfg("YT_TOKEN_URI",
                           "https://oauth2.googleapis.com/token"),
                      data={"code": code, "client_id": cid,
                            "client_secret": sec,
                            "redirect_uri": "http://localhost:1",
                            "grant_type": "authorization_code"},
                      timeout=60)
    if r.status_code != 200:
        raise YouTubeError(f"token exchange failed: {r.text[:200]}")
    tok = r.json()
    if not tok.get("refresh_token"):
        raise YouTubeError(
            "no refresh token returned. Revoke the app at "
            "myaccount.google.com/permissions, then connect again "
            "(this happens when consent was already granted once).")
    return tok


def _save(tok: dict):
    tok = dict(tok)
    tok["expires_at"] = time.time() + int(tok.get("expires_in", 3600)) - 120
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(json.dumps(tok, indent=1))


class _Catch(BaseHTTPRequestHandler):
    """Local listener that grabs ?code=... from the browser redirect."""
    code = None

    def log_message(self, *a):  # silence
        pass

    def do_GET(self):
        code = parse_qs(urlparse(self.path).query).get("code", [None])[0]
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        ok = b"<h2 style='font-family:sans-serif'>&#9989; Connected. You can close this tab.</h2>"
        err = b"<h2 style='font-family:sans-serif'>Almost! Copy the FULL url from the address bar and paste it in the console.</h2>"
        self.wfile.write(ok if code else err)
        if code:
            _Catch.code = code

    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()


def connect_interactive() -> dict:
    """Full consent flow for terminal use. Opens/catches port 1 if allowed,
    otherwise asks the user to paste the redirect URL."""
    import webbrowser
    url = consent_url()
    print("\nSTEP 1 - open this link in your browser and approve:\n")
    print(url + "\n")
    try:
        webbrowser.open(url)
    except Exception:
        pass
    caught = {"code": None}

    def listen():
        try:
            srv = HTTPServer(("127.0.0.1", 1), _Catch)
            srv.timeout = 300
            while _Catch.code is None:
                srv.handle_request()
            caught["code"] = _Catch.code
        except Exception:
            pass  # port 1 not permitted (non-root Android) - manual paste

    t = threading.Thread(target=listen, daemon=True)
    t.start()
    print("STEP 2 - waiting for the browser redirect on localhost:1 ...")
    print("(if the page shows an error, that is normal: copy the FULL url")
    print(" from the address bar - it contains ?code= - and paste below)\n")
    deadline = time.time() + 300
    while time.time() < deadline and caught["code"] is None:
        if _Catch.code:
            caught["code"] = _Catch.code
            break
        try:
            import select
            import sys
            if select.select([sys.stdin], [], [], 1.0)[0]:
                pasted = sys.stdin.readline().strip()
                if pasted:
                    code = parse_qs(urlparse(pasted).query).get("code", [None])[0]
                    if code:
                        caught["code"] = code
                        break
        except Exception:
            time.sleep(1)
    if not caught["code"]:
        raise YouTubeError(
            "timed out waiting for consent. Run again and paste the "
            "redirect URL when asked.")
    tok = _exchange(caught["code"])
    _save(tok)
    print("\nYouTube connected. Token saved to", TOKEN_FILE)
    return tok


def parse_redirect(url: str) -> str | None:
    """Extract ?code= from a pasted redirect URL (None if absent)."""
    return parse_qs(urlparse(url or "").query).get("code", [None])[0]


def finish_connect(redirect_url: str) -> dict:
    """Complete consent from a pasted redirect URL; saves the token."""
    code = parse_redirect(redirect_url)
    if not code:
        raise YouTubeError(
            "no ?code= found in that link. Copy the FULL address-bar URL "
            "from the page the browser landed on.")
    tok = _exchange(code)
    _save(tok)
    return tok


def get_access_token() -> str:
    """Valid access token from token.json, refreshing when needed."""
    if not TOKEN_FILE.exists():
        raise YouTubeError(
            "YouTube not connected yet. Finish one consent flow first "
            "(Stats tab 'Connect' button, or run upload.py once).")
    tok = json.loads(TOKEN_FILE.read_text())
    if time.time() < tok.get("expires_at", 0):
        return tok["access_token"]
    cid, sec = client_credentials()
    r = requests.post(_cfg("YT_TOKEN_URI",
                           "https://oauth2.googleapis.com/token"),
                      data={"refresh_token": tok["refresh_token"],
                            "client_id": cid, "client_secret": sec,
                            "grant_type": "refresh_token"}, timeout=60)
    if r.status_code != 200:
        raise YouTubeError(f"token refresh failed: {r.text[:200]}")
    tok.update(r.json())
    _save(tok)
    return tok["access_token"]


def _headers():
    return {"Authorization": "Bearer " + get_access_token()}


# ----------------------------------------------------------------- upload ---
def upload_short(video_path: Path, meta: dict, log=print) -> str:
    """Resumable upload of a finished render. meta = payload['metadata'].
    Returns the new videoId. Logs progress percent lines."""
    api = _cfg("YT_UPLOAD_BASE",
               "https://www.googleapis.com/upload/youtube/v3")
    body = {
        "snippet": {
            "title": (meta.get("title") or "Short")[:100],
            "description": (meta.get("description") or "")[:5000],
            "tags": meta.get("tags", [])[:30],
            "categoryId": "27",  # Education
        },
        "status": {
            "privacyStatus": "public",
            "selfDeclaredMadeForKids": False,
            "notifySubscribers": True,
        },
    }
    size = video_path.stat().st_size
    r = requests.post(
        api + "/videos?uploadType=resumable&part=snippet,status",
        json=body, headers=_headers(), timeout=60)
    if r.status_code not in (200, 201):
        raise YouTubeError(f"upload init failed: {r.text[:200]}")
    loc = r.headers["Location"]

    offset, attempt = 0, 0
    with video_path.open("rb") as f:
        while offset < size:
            f.seek(offset)
            chunk = f.read(CHUNK)
            end = offset + len(chunk) - 1
            cr = f"bytes {offset}-{end}/{size}" if len(chunk) else \
                f"*/{size}"
            try:
                rr = requests.put(loc, data=chunk,
                                  headers={"Content-Length": str(len(chunk)),
                                           "Content-Range": cr},
                                  timeout=600)
                attempt = 0
            except Exception as exc:
                attempt += 1
                if attempt > 5:
                    raise YouTubeError(f"upload network error: {exc}")
                time.sleep(3 * attempt)
                offset = _resume_from(loc, size)
                continue
            if rr.status_code in (200, 201):
                vid = rr.json()["id"]
                log("UPLOADED %s -> https://youtube.com/shorts/%s",
                    video_path.name, vid)
                return vid
            if rr.status_code == 308:
                rng = rr.headers.get("Range", "bytes=0-0")
                offset = int(rng.split("-")[1]) + 1
                attempt = 0
                log("upload %d%%", offset * 100 // size)
                continue
            if rr.status_code >= 500 or rr.status_code == 429:
                attempt += 1
                if attempt > 5:
                    raise YouTubeError(
                        f"upload server error {rr.status_code}")
                time.sleep(3 * attempt)
                offset = _resume_from(loc, size)
                continue
            raise YouTubeError(f"upload failed {rr.status_code}: "
                               f"{rr.text[:200]}")
    raise YouTubeError("upload ended unexpectedly")


def _resume_from(loc: str, size: int) -> int:
    try:
        st = requests.put(loc, headers={"Content-Range": f"*/{size}",
                                        "Content-Length": "0"}, timeout=60)
        rng = st.headers.get("Range")
        if rng:
            return int(rng.split("-")[1]) + 1
    except Exception:
        pass
    return 0


# ---------------------------------------------------------------- reading ---
def _api_get(path: str, params: dict) -> dict:
    r = requests.get(_cfg("YT_API_BASE",
                          "https://www.googleapis.com/youtube/v3")
                     + path, params=params, headers=_headers(), timeout=60)
    if r.status_code != 200:
        raise YouTubeError(f"YouTube API {r.status_code}: {r.text[:200]}")
    return r.json()


def get_video(vid: str) -> dict | None:
    """Metadata for one video id (None if not found/unreachable)."""
    return (get_videos([vid]) or [None])[0]


def get_videos(ids: list) -> list:
    """Batch metadata for video ids (skips unreachable batches)."""
    out = []
    for i in range(0, len(ids), 50):
        try:
            out += _api_get("/videos", {"part": "snippet,statistics,"
                                                 "contentDetails",
                                        "id": ",".join(ids[i:i + 50])}) \
                .get("items", [])
        except Exception:
            continue
    return out


def list_my_videos(max_results: int = 25) -> list:
    """Recent uploads of the connected channel ([{...videoId...}])."""
    try:
        items = _api_get("/search", {"part": "id", "forMine": "true",
                                     "order": "date", "type": "video",
                                     "maxResults": max_results}) \
            .get("items", [])
        out = []
        for it in items:
            vid = it.get("id", {}).get("videoId")
            if vid:
                out.append({"id": {"videoId": vid}})
        return out
    except Exception:
        return []


def top_comments(vid: str, limit: int = 3) -> list:
    try:
        items = _api_get("/commentThreads",
                         {"part": "snippet", "videoId": vid,
                          "order": "relevance",
                          "maxResults": limit}).get("items", [])
        out = []
        for c in items:
            sn = c["snippet"]["topLevelComment"]["snippet"]
            out.append({"author": sn.get("authorDisplayName", ""),
                        "text": (sn.get("textOriginal", "")
                                 or sn.get("textDisplay", ""))[:160]})
        return out
    except Exception:
        return []
