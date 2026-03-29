"""App configuration."""
import os
from pathlib import Path

# Paths
PROJECT_ROOT = Path(__file__).resolve().parent
SCREENSHOTS_DIR = PROJECT_ROOT / "screenshots"
UPLOADS_DIR = PROJECT_ROOT / "uploads"
CREDENTIALS_FILE = PROJECT_ROOT / "client_secret.json"
PICKLE_FILE = PROJECT_ROOT / "youtube_credentials.pickle"

# YouTube
YOUTUBE_SCOPES = ["https://www.googleapis.com/auth/youtube.force-ssl"]

# Scraper
# Minimum confidence / length for a line to count as a song (chars)
MIN_SONG_LENGTH = 3
MAX_SONG_LENGTH = 200

# LLM (optional) – set OPENAI_API_KEY; optional OPENAI_RECOMMEND_MODEL (default gpt-4o-mini)
# Load .env from project root when present
try:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")
except ImportError:
    pass

# Ensure dirs exist
SCREENSHOTS_DIR.mkdir(exist_ok=True)
UPLOADS_DIR.mkdir(exist_ok=True)
