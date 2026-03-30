"""App configuration."""
import json
import os
from pathlib import Path

# Paths
PROJECT_ROOT = Path(__file__).resolve().parent
IS_VERCEL = os.environ.get("VERCEL") == "1"

if IS_VERCEL:
    _TMP_BASE = Path("/tmp/sonic_sesh")
    SCREENSHOTS_DIR = _TMP_BASE / "screenshots"
    UPLOADS_DIR = _TMP_BASE / "uploads"
else:
    SCREENSHOTS_DIR = PROJECT_ROOT / "screenshots"
    UPLOADS_DIR = PROJECT_ROOT / "uploads"

CREDENTIALS_FILE = PROJECT_ROOT / "client_secret.json"
PICKLE_FILE = PROJECT_ROOT / "youtube_credentials.pickle"

# YouTube
YOUTUBE_SCOPES = ["https://www.googleapis.com/auth/youtube.force-ssl"]

# Scraper
MIN_SONG_LENGTH = 3
MAX_SONG_LENGTH = 200

# LLM (optional)
try:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")
except ImportError:
    pass


def get_public_base_url() -> str | None:
    """HTTPS origin for OAuth redirect (Vercel or custom)."""
    base = (os.environ.get("PUBLIC_BASE_URL") or "").strip().rstrip("/")
    if base:
        return base
    vercel_url = os.environ.get("VERCEL_URL", "").strip()
    if vercel_url:
        return "https://" + vercel_url.lstrip("/")
    return None


def has_client_secret_config() -> bool:
    """True if client_secret.json exists or JSON is in env (for Vercel)."""
    if CREDENTIALS_FILE.exists():
        return True
    raw = os.environ.get("GOOGLE_CLIENT_SECRET_JSON", "").strip()
    return bool(raw)


def load_google_client_config() -> dict:
    """
    Load Google OAuth client JSON (web or installed) from file or GOOGLE_CLIENT_SECRET_JSON env.
    """
    if CREDENTIALS_FILE.exists():
        return json.loads(CREDENTIALS_FILE.read_text(encoding="utf-8"))
    raw = os.environ.get("GOOGLE_CLIENT_SECRET_JSON", "").strip()
    if not raw:
        raise FileNotFoundError(
            "Missing OAuth client config. Add client_secret.json locally or set "
            "GOOGLE_CLIENT_SECRET_JSON in the environment (Vercel)."
        )
    return json.loads(raw)


# Ensure dirs exist (local only; /tmp on Vercel is fine at runtime)
SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
