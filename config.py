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

# Scraper (OpenAI Vision only — see OPENAI_API_KEY, OPENAI_VISION_MODEL)
MIN_SONG_LENGTH = 3
MAX_SONG_LENGTH = 200
# Vision default; use gpt-4.1 for denser UI if your key supports it (set OPENAI_VISION_MODEL).
OPENAI_VISION_MODEL_DEFAULT = "gpt-4o"

def reload_dotenv_from_project() -> None:
    """Load ``PROJECT_ROOT/.env`` with override so file values beat the shell (local dev)."""
    try:
        from dotenv import load_dotenv

        load_dotenv(PROJECT_ROOT / ".env", override=True)
    except ImportError:
        pass


reload_dotenv_from_project()


def get_openai_api_key() -> str:
    """
    Return ``OPENAI_API_KEY`` after re-reading ``.env`` so the key in the project file
    is always used when present (overrides a stale ``export OPENAI_API_KEY=...``).
    On Vercel, ``.env`` is usually absent; the dashboard env var is used instead.
    """
    reload_dotenv_from_project()
    return (os.environ.get("OPENAI_API_KEY") or "").strip()


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
        text = CREDENTIALS_FILE.read_text(encoding="utf-8")
        return _parse_client_secret_json(text)

    raw = os.environ.get("GOOGLE_CLIENT_SECRET_JSON", "").strip()
    if not raw:
        raise FileNotFoundError(
            "Missing OAuth client config. Add client_secret.json locally or set "
            "GOOGLE_CLIENT_SECRET_JSON in the environment (Vercel)."
        )
    return _parse_client_secret_json(raw)


def _parse_client_secret_json(text: str) -> dict:
    """Parse client JSON; strip BOM; tolerate common Vercel paste mistakes."""
    text = text.lstrip("\ufeff").strip()
    if not text.startswith("{"):
        import base64

        try:
            text = base64.b64decode(text).decode("utf-8")
        except Exception:
            pass
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(
            "GOOGLE_CLIENT_SECRET_JSON is not valid JSON. Paste the full downloaded "
            f"credentials file as one line (no surrounding quotes). Parser error: {e}"
        ) from e


# Ensure dirs exist (local only; /tmp on Vercel is fine at runtime)
SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
