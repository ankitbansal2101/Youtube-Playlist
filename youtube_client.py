"""
YouTube API client: authenticate, create playlist, search videos, add to playlist.
Local: desktop OAuth + pickle. Deployed (Vercel): web OAuth + Flask session JSON.
"""
import json
import os
import pickle
from datetime import datetime
from pathlib import Path

import google_auth_oauthlib.flow
import googleapiclient.discovery
import googleapiclient.errors
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

from config import CREDENTIALS_FILE, PICKLE_FILE, YOUTUBE_SCOPES, load_google_client_config


def _client_config_for_web_flow(client_config: dict, redirect_uri: str) -> dict:
    """Build a 'web' block for google_auth_oauthlib Flow (works with Web or Desktop JSON)."""
    if "web" in client_config:
        return client_config
    if "installed" in client_config:
        inst = client_config["installed"]
        return {
            "web": {
                "client_id": inst["client_id"],
                "client_secret": inst["client_secret"],
                "auth_uri": inst.get("auth_uri", "https://accounts.google.com/o/oauth2/auth"),
                "token_uri": inst.get("token_uri", "https://oauth2.googleapis.com/token"),
                "redirect_uris": [redirect_uri],
            }
        }
    raise ValueError("OAuth JSON must contain 'web' or 'installed'")


def create_web_oauth_flow(redirect_uri: str):
    """Flow for browser redirect (Vercel / HTTPS)."""
    raw = load_google_client_config()
    cfg = _client_config_for_web_flow(raw, redirect_uri)
    # PKCE stores code_verifier on the Flow instance. We create a new Flow on callback,
    # so PKCE must be off or token exchange fails with "Missing code verifier".
    return google_auth_oauthlib.flow.Flow.from_client_config(
        cfg,
        scopes=YOUTUBE_SCOPES,
        redirect_uri=redirect_uri,
        autogenerate_code_verifier=False,
    )


def credentials_to_session_json(creds: Credentials) -> str:
    return creds.to_json()


def credentials_from_session_json(data: str) -> Credentials:
    info = json.loads(data)
    return Credentials.from_authorized_user_info(info, YOUTUBE_SCOPES)


def refresh_session_credentials_if_needed(creds: Credentials) -> Credentials:
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
    return creds


def authenticate_youtube():
    """Run OAuth flow (local browser server) and save credentials. Returns YouTube API resource."""
    os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"
    if not CREDENTIALS_FILE.exists():
        raise FileNotFoundError(
            f"OAuth client secrets not found at {CREDENTIALS_FILE}. "
            "Download from Google Cloud Console and save as client_secret.json"
        )
    flow = google_auth_oauthlib.flow.InstalledAppFlow.from_client_secrets_file(
        str(CREDENTIALS_FILE), YOUTUBE_SCOPES
    )
    credentials = flow.run_local_server(port=0)
    with open(PICKLE_FILE, "wb") as token:
        pickle.dump(credentials, token)
    return googleapiclient.discovery.build("youtube", "v3", credentials=credentials)


def load_youtube_client():
    """Load credentials from Flask session (deployed), else pickle file."""
    try:
        from flask import has_request_context, session
    except ImportError:
        has_request_context = lambda: False
        session = None

    if has_request_context() and session is not None:
        raw = session.get("youtube_creds_json")
        if raw:
            creds = credentials_from_session_json(raw)
            creds = refresh_session_credentials_if_needed(creds)
            session["youtube_creds_json"] = creds.to_json()
            return googleapiclient.discovery.build("youtube", "v3", credentials=creds)

    if not PICKLE_FILE.exists():
        raise FileNotFoundError(
            "No saved credentials. Authenticate YouTube in the app first."
        )
    with open(PICKLE_FILE, "rb") as token:
        credentials = pickle.load(token)
    return googleapiclient.discovery.build("youtube", "v3", credentials=credentials)


def youtube_credentials_ready(session_dict: dict) -> bool:
    """Whether we have tokens (session JSON or pickle)."""
    if session_dict and session_dict.get("youtube_creds_json"):
        return True
    return PICKLE_FILE.exists()


def get_youtube():
    if PICKLE_FILE.exists():
        return load_youtube_client()
    return authenticate_youtube()


def create_playlist(youtube, title: str, description: str, privacy: str = "public"):
    request = youtube.playlists().insert(
        part="snippet,status",
        body={
            "snippet": {
                "title": title,
                "description": description,
                "tags": ["Auto-generated", "Playlist"],
                "defaultLanguage": "en",
            },
            "status": {"privacyStatus": privacy},
        },
    )
    response = request.execute()
    return response["id"], response["snippet"]["title"]


def add_video_to_playlist(youtube, playlist_id: str, video_id: str):
    youtube.playlistItems().insert(
        part="snippet",
        body={
            "snippet": {
                "playlistId": playlist_id,
                "resourceId": {"kind": "youtube#video", "videoId": video_id},
            }
        },
    ).execute()


def search_video(youtube, query: str, max_results: int = 1):
    request = youtube.search().list(
        part="id",
        q=query,
        type="video",
        maxResults=max_results,
    )
    response = request.execute()
    items = response.get("items") or []
    if not items:
        return None
    return items[0]["id"]["videoId"]


def build_playlist_from_songs(
    youtube,
    songs: list[str],
    playlist_title: str = None,
    playlist_description: str = "",
    privacy: str = "public",
):
    datestr = datetime.now().strftime("%Y-%m-%d")
    title = playlist_title or f"Sonic Sesh auto-gen playlist {datestr}"
    desc = playlist_description or f"Auto-generated playlist – {datestr}"
    playlist_id, _ = create_playlist(youtube, title, desc, privacy)
    playlist_link = f"https://www.youtube.com/playlist?list={playlist_id}"
    results = []
    for song in songs:
        video_id = None
        err = None
        try:
            video_id = search_video(youtube, song)
            if video_id:
                add_video_to_playlist(youtube, playlist_id, video_id)
            else:
                err = "No video found"
        except googleapiclient.errors.HttpError as e:
            err = str(e)
        except Exception as e:
            err = str(e)
        results.append((song, video_id, err))
    return playlist_id, playlist_link, results
