"""
Flask UI: upload screenshots → scrape → weighted suggestions → create YouTube playlist.
"""
from datetime import datetime
from pathlib import Path

from flask import Flask, redirect, render_template, request, session, url_for

from config import CREDENTIALS_FILE, PICKLE_FILE, SCREENSHOTS_DIR
from scraper import scrape_directory, scrape_uploaded_files
from suggestions import (
    aggregate_songs,
    get_suggestions_from_directory,
    get_suggestions_from_uploads,
)
from youtube_client import (
    authenticate_youtube,
    load_youtube_client,
    build_playlist_from_songs,
)

app = Flask(__name__)
app.secret_key = "sonic-sesh-secret-change-in-production"


@app.route("/")
def index():
    suggestions = session.get("suggestions", [])  # list of (song, weight, num_sources)
    playlist_link = session.pop("playlist_link", None)
    failed_count = session.pop("playlist_failed", None)
    return render_template(
        "index.html",
        suggestions=suggestions,
        credentials_loaded=PICKLE_FILE.exists(),
        credentials_file_missing=not CREDENTIALS_FILE.exists(),
        screenshots_dir=SCREENSHOTS_DIR,
        playlist_link=playlist_link,
        auth_ok=request.args.get("auth") == "ok",
        error=request.args.get("error"),
        failed_count=failed_count,
        now=datetime.now().strftime("%Y-%m-%d"),
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

    # Store (song, weight, num_sources) for template (sources list not needed in UI)
    session["suggestions"] = [(s[0], s[1], len(s[2])) for s in suggestions]
    return redirect(url_for("index"))


@app.route("/playlist", methods=["POST"])
def create_playlist():
    if not PICKLE_FILE.exists():
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
    if not CREDENTIALS_FILE.exists():
        return redirect(url_for("index") + "?error=no_client_secret")
    try:
        authenticate_youtube()
        return redirect(url_for("index") + "?auth=ok")
    except Exception as e:
        return redirect(url_for("index") + f"?error={request.quote(str(e))}")


if __name__ == "__main__":
    app.run(debug=True, port=5000)
