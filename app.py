"""
Flask UI: upload screenshots → scrape → weighted suggestions → create YouTube playlist.
"""
import os
import secrets
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from flask import Flask, jsonify, redirect, render_template, request, session, url_for

_ROOT = Path(__file__).resolve().parent
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from werkzeug.middleware.proxy_fix import ProxyFix

from config import (
    CREDENTIALS_FILE,
    IS_VERCEL,
    PICKLE_FILE,
    SCREENSHOTS_DIR,
    get_public_base_url,
    has_client_secret_config,
)
from scraper import VisionOpenAIQuotaError, scrape_directory, scrape_uploaded_files

_SCRAPE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}


def _scrapeable_image_count() -> int:
    if not SCREENSHOTS_DIR.exists():
        return 0
    return sum(1 for p in SCREENSHOTS_DIR.iterdir() if p.suffix.lower() in _SCRAPE_EXT)
from suggestions import (
    aggregate_directory_with_raw_count,
    aggregate_uploads_with_raw_count,
)
from llm_recommendations import generate_recommendations
from youtube_client import (
    authenticate_youtube,
    create_web_oauth_flow,
    load_youtube_client,
    build_playlist_from_songs,
    youtube_credentials_ready,
)

app = Flask(__name__, template_folder=str(_ROOT / "templates"))
# Some hosts (e.g. Vercel) run with a different CWD; explicit path finds templates.
application = app  # WSGI alias for platforms that expect `application`
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "sonic-sesh-secret-change-in-production")
# After Google redirects back, the browser must send the session cookie (for youtube_creds_json).
# SameSite=None + Secure is required for that cross-site return on HTTPS (Vercel, ngrok, etc.).
_public_base = get_public_base_url()
if _public_base and _public_base.lower().startswith("https://"):
    app.config["SESSION_COOKIE_SECURE"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "None"
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

_OAUTH_STATE_SALT = "youtube-oauth-state-v1"
_OAUTH_STATE_MAX_AGE = 900  # 15 minutes


def _oauth_state_signer():
    return URLSafeTimedSerializer(app.secret_key, salt=_OAUTH_STATE_SALT)


def _make_signed_oauth_state() -> str:
    return _oauth_state_signer().dumps({"n": secrets.token_hex(16)})


def _verify_signed_oauth_state(state_param: str | None) -> bool:
    if not state_param:
        return False
    try:
        _oauth_state_signer().loads(state_param, max_age=_OAUTH_STATE_MAX_AGE)
        return True
    except (BadSignature, SignatureExpired):
        return False


def _public_authorization_response() -> str:
    """
    Google token exchange requires the redirect_uri to match the registered HTTPS URL.
    On Vercel, request.url may be http:// internally; rebuild with the public origin.
    """
    from urllib.parse import urlencode

    base = get_public_base_url()
    if not base:
        return request.url
    args = request.args.to_dict(flat=True)
    query = urlencode(args)
    path = "/auth/youtube/callback"
    return f"{base.rstrip('/')}{path}?{query}" if query else f"{base.rstrip('/')}{path}"


@app.route("/health")
def health():
    return jsonify(status="ok")


@app.route("/")
def index():
    suggestions = session.get("suggestions", [])
    playlist_link = session.pop("playlist_link", None)
    failed_count = session.pop("playlist_failed", None)
    return render_template(
        "index.html",
        suggestions=suggestions,
        llm_recommendations=session.get("llm_recommendations", []),
        credentials_loaded=youtube_credentials_ready(dict(session)),
        credentials_file_missing=not has_client_secret_config(),
        screenshots_dir=SCREENSHOTS_DIR,
        playlist_link=playlist_link,
        auth_ok=request.args.get("auth") == "ok",
        error=request.args.get("error"),
        failed_count=failed_count,
        now=datetime.now().strftime("%Y-%m-%d"),
        is_vercel=IS_VERCEL,
        public_base_url=get_public_base_url(),
        cleared=request.args.get("cleared"),
        cleared_scope=request.args.get("scope"),
    )


@app.route("/scrape", methods=["POST"])
def scrape():
    min_weight = int(request.form.get("min_weight", 1))
    mode = request.form.get("mode", "folder")

    paths: list = []
    try:
        if mode == "upload":
            files = request.files.getlist("screenshots")
            for f in files:
                if f and f.filename:
                    path = SCREENSHOTS_DIR / Path(f.filename).name
                    f.save(str(path))
                    paths.append(path)
            if not paths:
                return redirect(url_for("index") + "?error=no_upload")
            suggestions, raw_lines = aggregate_uploads_with_raw_count(
                paths, min_weight=min_weight
            )
        else:
            if _scrapeable_image_count() == 0:
                return redirect(url_for("index") + "?error=no_screenshots")
            suggestions, raw_lines = aggregate_directory_with_raw_count(
                SCREENSHOTS_DIR, min_weight=min_weight
            )
    except VisionOpenAIQuotaError:
        session.pop("suggestions", None)
        session.pop("llm_recommendations", None)
        return redirect(url_for("index") + "?error=openai_quota")

    if not suggestions and raw_lines == 0:
        session.pop("suggestions", None)
        session.pop("llm_recommendations", None)
        return redirect(url_for("index") + "?error=vision_empty")
    if not suggestions and raw_lines > 0:
        session.pop("suggestions", None)
        session.pop("llm_recommendations", None)
        return redirect(url_for("index") + "?error=min_weight_no_match")

    session["suggestions"] = [(s[0], s[1], len(s[2])) for s in suggestions]
    session.pop("llm_recommendations", None)
    return redirect(url_for("index"))


@app.route("/llm-recommendations", methods=["POST"])
def llm_recommendations_route():
    suggestions = session.get("suggestions", [])
    if not suggestions:
        return redirect(url_for("index") + "?error=no_suggestions_for_llm")
    try:
        count = int(request.form.get("llm_count", 10))
    except ValueError:
        count = 10
    seeds = [s[0] for s in sorted(suggestions, key=lambda x: -x[1])][:40]
    try:
        recs = generate_recommendations(seeds, count=count)
        session["llm_recommendations"] = recs
        return redirect(url_for("index") + "?llm=ok")
    except Exception as e:
        return redirect(url_for("index") + f"?error={quote(str(e))}")


@app.route("/clear-suggestions", methods=["POST"])
def clear_suggestions():
    """
    scope=screenshots — remove weighted list from Vision scrape and AI picks (AI depends on seeds).
    scope=llm — remove only AI recommendations; keep screenshot suggestions.
    """
    scope = (request.form.get("scope") or "screenshots").strip().lower()
    if scope == "llm":
        session.pop("llm_recommendations", None)
    else:
        session.pop("suggestions", None)
        session.pop("llm_recommendations", None)
        scope = "screenshots"
    session.modified = True
    return redirect(url_for("index", cleared="1", scope=scope))


@app.route("/playlist", methods=["POST"])
def create_playlist():
    if not youtube_credentials_ready(dict(session)):
        return redirect(url_for("index") + "?error=auth")
    chosen = request.form.getlist("songs")
    if not chosen:
        return redirect(url_for("index") + "?error=no_songs")
    title = request.form.get("playlist_title", f"Sonic Sesh auto-gen {datetime.now().strftime('%Y-%m-%d')}")
    description = request.form.get("playlist_description", "Auto-generated from friend screenshots.")
    privacy = request.form.get("privacy", "public")
    try:
        youtube = load_youtube_client()
        playlist_id, link, results = build_playlist_from_songs(
            youtube, chosen,
            playlist_title=title,
            playlist_description=description,
            privacy=privacy,
        )
        failed = [(s, e) for s, v, e in results if e]
        session["playlist_link"] = link
        session["playlist_failed"] = len(failed)
        return redirect(url_for("index"))
    except Exception as e:
        return redirect(url_for("index") + f"?error={quote(str(e))}")


@app.route("/auth/youtube")
def auth_youtube():
    if not has_client_secret_config():
        return redirect(url_for("index") + "?error=no_client_secret")

    base = get_public_base_url()
    if base:
        redirect_uri = base.rstrip("/") + "/auth/youtube/callback"
        try:
            flow = create_web_oauth_flow(redirect_uri)
            signed_state = _make_signed_oauth_state()
            authorization_url, _ = flow.authorization_url(
                access_type="offline",
                include_granted_scopes="true",
                prompt="consent",
                state=signed_state,
            )
            session.modified = True
            return redirect(authorization_url)
        except Exception as e:
            return redirect(url_for("index") + f"?error={quote(str(e))}")

    if not CREDENTIALS_FILE.exists():
        return redirect(url_for("index") + "?error=no_client_secret")
    try:
        authenticate_youtube()
        return redirect(url_for("index") + "?auth=ok")
    except Exception as e:
        return redirect(url_for("index") + f"?error={quote(str(e))}")


@app.route("/auth/youtube/callback")
def auth_youtube_callback():
    base = get_public_base_url()
    if not base:
        return redirect(url_for("index") + "?error=oauth")
    raw_state = request.args.get("state")
    if not _verify_signed_oauth_state(raw_state):
        return redirect(url_for("index") + "?error=oauth_state")
    redirect_uri = base.rstrip("/") + "/auth/youtube/callback"
    try:
        flow = create_web_oauth_flow(redirect_uri)
        # New Flow instance must expect the same state Google returns on the callback URL
        flow.oauth2session._state = raw_state
        flow.fetch_token(authorization_response=_public_authorization_response())
        creds = flow.credentials
        session["youtube_creds_json"] = creds.to_json()
        session.modified = True
        return redirect(url_for("index") + "?auth=ok")
    except Exception as e:
        return redirect(url_for("index") + f"?error={quote(str(e))}")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(debug=True, host="127.0.0.1", port=port)
