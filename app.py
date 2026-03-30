"""
Flask UI: upload screenshots → scrape → weighted suggestions → create YouTube playlist.
"""
import os
from datetime import datetime
from pathlib import Path

from flask import Flask, redirect, render_template, request, session, url_for
from werkzeug.middleware.proxy_fix import ProxyFix

from config import (
    CREDENTIALS_FILE,
    IS_VERCEL,
    PICKLE_FILE,
    SCREENSHOTS_DIR,
    get_public_base_url,
    has_client_secret_config,
)
from scraper import scrape_directory, scrape_uploaded_files
from suggestions import (
    get_suggestions_from_directory,
    get_suggestions_from_uploads,
)
from llm_recommendations import generate_recommendations
from youtube_client import (
    authenticate_youtube,
    create_web_oauth_flow,
    load_youtube_client,
    build_playlist_from_songs,
    youtube_credentials_ready,
)

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "sonic-sesh-secret-change-in-production")
if IS_VERCEL:
    app.config["SESSION_COOKIE_SECURE"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)


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
    )


@app.route("/scrape", methods=["POST"])
def scrape():
    min_weight = int(request.form.get("min_weight", 1))
    mode = request.form.get("mode", "folder")

    if mode == "upload":
        files = request.files.getlist("screenshots")
        paths = []
        for f in files:
            if f and f.filename:
                path = SCREENSHOTS_DIR / Path(f.filename).name
                f.save(str(path))
                paths.append(path)
        if paths:
            suggestions = get_suggestions_from_uploads(paths, min_weight=min_weight)
        else:
            suggestions = []
    else:
        suggestions = get_suggestions_from_directory(SCREENSHOTS_DIR, min_weight=min_weight)

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
        return redirect(url_for("index") + f"?error={request.quote(str(e))}")


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
        return redirect(url_for("index") + f"?error={request.quote(str(e))}")


@app.route("/auth/youtube")
def auth_youtube():
    if not has_client_secret_config():
        return redirect(url_for("index") + "?error=no_client_secret")

    base = get_public_base_url()
    if base:
        redirect_uri = base.rstrip("/") + "/auth/youtube/callback"
        try:
            flow = create_web_oauth_flow(redirect_uri)
            authorization_url, state = flow.authorization_url(
                access_type="offline",
                include_granted_scopes="true",
                prompt="consent",
            )
            session["oauth_state"] = state
            session["oauth_redirect_uri"] = redirect_uri
            return redirect(authorization_url)
        except Exception as e:
            return redirect(url_for("index") + f"?error={request.quote(str(e))}")

    if not CREDENTIALS_FILE.exists():
        return redirect(url_for("index") + "?error=no_client_secret")
    try:
        authenticate_youtube()
        return redirect(url_for("index") + "?auth=ok")
    except Exception as e:
        return redirect(url_for("index") + f"?error={request.quote(str(e))}")


@app.route("/auth/youtube/callback")
def auth_youtube_callback():
    base = get_public_base_url()
    if not base:
        return redirect(url_for("index") + "?error=oauth")
    if request.args.get("state") != session.get("oauth_state"):
        return redirect(url_for("index") + "?error=oauth_state")
    redirect_uri = session.get("oauth_redirect_uri") or (base.rstrip("/") + "/auth/youtube/callback")
    try:
        flow = create_web_oauth_flow(redirect_uri)
        flow.fetch_token(authorization_response=request.url)
        creds = flow.credentials
        session["youtube_creds_json"] = creds.to_json()
        session.pop("oauth_state", None)
        session.pop("oauth_redirect_uri", None)
        return redirect(url_for("index") + "?auth=ok")
    except Exception as e:
        return redirect(url_for("index") + f"?error={request.quote(str(e))}")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(debug=True, host="127.0.0.1", port=port)
