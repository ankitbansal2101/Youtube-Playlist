"""
YouTube API client: authenticate, create playlist, search videos, add to playlist.
"""
import os
import pickle
from datetime import datetime
from pathlib import Path

import google_auth_oauthlib.flow
import googleapiclient.discovery
import googleapiclient.errors

from config import CREDENTIALS_FILE, PICKLE_FILE, YOUTUBE_SCOPES


def authenticate_youtube():
    """Run OAuth flow (browser) and save credentials. Returns YouTube API resource."""
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
    """Load previously saved credentials and return YouTube API resource."""
    if not PICKLE_FILE.exists():
        raise FileNotFoundError(
            "No saved credentials. Run 'Authenticate' once in the UI (or call authenticate_youtube())."
        )
    with open(PICKLE_FILE, "rb") as token:
        credentials = pickle.load(token)
    return googleapiclient.discovery.build("youtube", "v3", credentials=credentials)


def get_youtube():
    """Use saved credentials if available; otherwise require auth."""
    if PICKLE_FILE.exists():
        return load_youtube_client()
    return authenticate_youtube()


def create_playlist(youtube, title: str, description: str, privacy: str = "public"):
    """Create a playlist. Returns (playlist_id, title)."""
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
    """Append one video to a playlist."""
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
    """
    Search YouTube for a video by query. Returns video_id or None if not found.
    """
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
    """
    Create a new playlist and add each song (search then add first result).
    Returns (playlist_id, playlist_link, list of (song, video_id or None, error_msg)).
    """
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
