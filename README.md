# Sonic Sesh – Playlist from Screenshots

Turn screenshots of songs (Spotify, Apple Music, etc.) into a single, ranked list and push it to a YouTube playlist.

---

## What is this? (Plain language)

**Sonic Sesh** is a small app for groups of friends who share screenshots of songs they like (e.g. in a chat). Instead of manually copying song names:

1. **You collect screenshots** – Either upload them in the app or drop image files into a folder.
2. **The app “reads” the images** – It uses **OpenAI Vision** on every screenshot (same **`OPENAI_API_KEY`** as optional AI recommendations). Works the same locally and on Vercel.
3. **It ranks the songs** – If the same song appears on multiple screenshots (e.g. several friends had it), it gets a higher “weight” and appears higher in the list. So the list reflects what’s popular across everyone’s picks.
4. **Optional: AI recommendations** – After the scraper runs, you can ask an LLM (OpenAI) for extra songs that match the vibe of what people already picked. Those appear as a second list; you choose which ones go on the playlist like the screenshot-based songs.
5. **You can push to YouTube** – You pick which songs to keep (screenshot list + any AI picks), give the playlist a name, and the app creates a YouTube playlist and adds a video for each song (by searching YouTube).

No song list is saved on disk: each time you run the scraper, it looks at **all screenshots currently in the folder** (or that you just uploaded), reads them again, and recalculates the rankings. Add or remove screenshots and run again to get an updated list.

---

## How it works (User flow)

| Step | What the user does | What happens |
|------|--------------------|--------------|
| 1 | Clicks **Authenticate YouTube** (once) | Signs in with Google in the browser; the app saves access so it can create playlists on their behalf. |
| 2 | Adds screenshots | Either **uploads** images in the app or puts images in the **`screenshots/`** folder and chooses “Use screenshots folder”. |
| 3 | Clicks **Run scraper and get weighted suggestions** | The app sends each image to **OpenAI Vision**, extracts song lines, counts how many screenshots each song appeared in (weight), and shows a sorted list. |
| 4 | Adjusts **Min weight** (optional) | Filters out songs that appeared in fewer than N screenshots (e.g. min weight 2 = only songs that showed up in at least 2 screenshots). |
| 5 | **Optional:** **Generate AI recommendations** | Sends the weighted song list (as text) to OpenAI; the model returns new “Artist - Title” suggestions that fit the same taste. Requires `OPENAI_API_KEY`. |
| 6 | Selects which songs to add | Checks/unchecks screenshot-based songs and any AI rows; “Select all” / “Clear” applies to both. |
| 7 | Fills playlist title, description, privacy | Then clicks **Create playlist and add songs**. |
| 8 | Result | A new YouTube playlist is created; for each selected song the app searches YouTube and adds the first result. A link to the playlist is shown; any failed songs are listed. |

---

## Weights (Plain language)

- **Weight** = number of screenshots that contained that song.
- **Example:** If “Blinding Lights - The Weeknd” appears in 3 different screenshots, its weight is 3. If it appears in only 1, weight is 1.
- The list is **sorted by weight (highest first)**, so songs that multiple people had rise to the top.
- **Min weight** lets you hide one-off picks or bad extractions (e.g. only show songs that appeared in at least 2 screenshots).

**Technical:** Weights are computed **per run**. Every time you run the scraper, the app processes all images in the current set (folder or upload), aggregates song lines, and counts occurrences. There is no persistent store of past runs; each run is independent.

---

## OpenAI (`OPENAI_API_KEY`)

- **Screenshot reading:** Each image is sent to **OpenAI Vision** (`scraper.py`). Set **`OPENAI_VISION_MODEL`** if you want something other than the default `gpt-4o-mini`. **`OPENAI_VISION_MAX_SIDE`** (default `2048`) limits image size before upload to save tokens.
- **AI recommendations (optional):** After weighted suggestions exist, the app can call OpenAI with **text only** (song titles) for more picks. Optional **`OPENAI_RECOMMEND_MODEL`** (default `gpt-4o-mini`).
- **Privacy / cost:** Screenshots and text go to OpenAI’s API; you pay per request. Re-running **Run scraper** clears stored AI suggestions for that session.

Implementation: `scraper.py` (Vision JSON `songs` array), `llm_recommendations.py` (recommendations from seeds).

---

## Technical overview

### Architecture

- **UI:** Flask web app (single page). Users upload files or point to a folder, trigger the scraper, optionally request LLM recommendations, and create a YouTube playlist.
- **Scraper:** Reads images from disk (or uploads), sends each to **OpenAI Vision**, returns song-like lines per image.
- **Suggestions:** Takes scraper output (list of `(image_path, list_of_song_lines)`), normalizes and deduplicates song strings, counts how many images each song appeared in (weight), sorts by weight, optionally filters by min weight.
- **LLM recommendations (optional):** `llm_recommendations.py` sends seed song strings to OpenAI Chat Completions (JSON mode), parses `recommendations`, dedupes against seeds.
- **YouTube:** OAuth 2.0 (one-time) with stored credentials; then create playlist, search by song query, add first video result per song. All via YouTube Data API v3.

### Data flow

```
Screenshots (folder or upload)
    → scraper.py (OpenAI Vision per image → song lines per image)
    → suggestions.py (aggregate by song → weight = count of images)
    → Session (suggestions list in memory)
    → [optional] llm_recommendations.py (OpenAI → more “Artist - Title” strings)
    → User selects songs + playlist metadata
    → youtube_client.py (create playlist, search per song, add items)
    → Playlist URL
```

Nothing is stored in a database or file except: (1) OAuth credentials (`youtube_credentials.pickle`), (2) uploaded/saved images in `screenshots/` (or `uploads/`). Song lists and weights exist only in memory for that run.

### Project structure

| File / folder | Role |
|---------------|------|
| `app.py` | Flask app: routes for index, scrape, LLM recommendations, create playlist, YouTube auth. |
| `llm_recommendations.py` | Optional OpenAI-based song recommendations from seed list. |
| `scraper.py` | OpenAI Vision → song lines per image. |
| `suggestions.py` | Aggregate lines by song, compute weight, sort and filter. |
| `youtube_client.py` | OAuth, create playlist, search video, add to playlist. |
| `config.py` | Paths (screenshots, credentials), song-line length limits, YouTube scopes. |
| `templates/` | Flask HTML (base + index). |
| `screenshots/` | Default folder for screenshot images (created if missing). |
| `client_secret.json` | Google OAuth client secret (you add this; not in git). |
| `youtube_credentials.pickle` | Stored OAuth tokens after first login (local only; not in git). |
| `runtime.txt` / `.vercelignore` | Vercel deployment helpers. |
| `.env.example` | Example environment variables (copy to `.env` locally). |

### Tech stack

- **Python 3.10+**
- **Flask** – Web UI.
- **Pillow** – Image resize/encode for Vision; **OpenAI** – Vision (screenshots) + chat (recommendations).
- **Google APIs** – `google-auth-oauthlib`, `google-api-python-client` for YouTube Data API v3.

---

## Setup

### 1. Python

- **Python 3.10+**. No system OCR install—screenshots use **OpenAI Vision** only.

### 2. Dependencies

```bash
cd "Youtube scraper"
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 3. OpenAI (required for “Run scraper”)

Add **`OPENAI_API_KEY`** to `.env` (local) or Vercel environment variables. Without it, scraping images will fail.

### 4. YouTube (for playlist creation)

1. [Google Cloud Console](https://console.cloud.google.com/) → create or select a project.
2. Enable **YouTube Data API v3** (APIs & Services → Library).
3. Create **OAuth 2.0 credentials** (APIs & Services → Credentials → Create Credentials → OAuth client ID → Desktop app).
4. Download the JSON and save it as **`client_secret.json`** in this project folder.
5. **OAuth consent screen:** If the app is in Testing, add your Google account as a test user (APIs & Services → OAuth consent screen → Test users). To allow anyone to sign in, publish the app (Publishing status → Publish app).

---

## Run the app

```bash
source .venv/bin/activate   # if not already
python app.py
```

Open **http://127.0.0.1:5000** (or the port shown in the terminal). Set **`OPENAI_API_KEY`**, authenticate YouTube once, then add screenshots, run the scraper, choose songs, and create the playlist.

---

## Deploy on Vercel

The repo includes **`runtime.txt`** and **`.vercelignore`**. Vercel detects **Flask** from **`app.py`** (zero-config). Do not add a legacy `vercel.json` with `@vercel/python` builds unless you have a specific reason—it often breaks Flask on current Vercel.

### Limitations on Vercel

- **Screenshot scraping** requires **`OPENAI_API_KEY`** (OpenAI Vision), same as locally.
- **Ephemeral disk:** uploads go under `/tmp` and do not persist across invocations.
- **YouTube tokens** are stored in the **signed session cookie** after web OAuth (not on disk). Use a strong **`FLASK_SECRET_KEY`** or users will lose auth when the secret changes.

### Google OAuth for production

1. In Google Cloud Console, create an OAuth client of type **Web application** (not only Desktop).
2. Under **Authorized redirect URIs**, add:
   - `https://<your-project>.vercel.app/auth/youtube/callback`
   - Add your production domain too if you use a custom domain.
3. Copy the client JSON. In the Vercel project → **Settings → Environment Variables**, add:
   - **`GOOGLE_CLIENT_SECRET_JSON`** – entire JSON as a single-line string (the `web` client object is fine).
   - **`FLASK_SECRET_KEY`** – long random string (e.g. `openssl rand -hex 32`).
   - **`OPENAI_API_KEY`** – required for screenshot reading (Vision) and for AI recommendations.
4. **`PUBLIC_BASE_URL`** – optional. If unset, the app uses `https://` + **`VERCEL_URL`** (set automatically by Vercel). Set `PUBLIC_BASE_URL` if you use a custom domain (e.g. `https://playlist.example.com`).

### Deploy

1. Install the [Vercel CLI](https://vercel.com/docs/cli) or connect the GitHub repo in the Vercel dashboard.
2. Import the project and deploy; Vercel will run `pip install -r requirements.txt` via the Python build.

```bash
npx vercel
```

### Files for Vercel

| File | Purpose |
|------|--------|
| `runtime.txt` | Python version for the build. |
| `.vercelignore` | Skips venv, secrets, and local data from uploads. |
| `.env.example` | Lists env vars to mirror in the Vercel dashboard. |

After deploy, open **`/health`** — expect `{"status":"ok"}`. If you see a generic 500 on **Authenticate YouTube**, check Vercel **Function logs**; common causes are invalid **`GOOGLE_CLIENT_SECRET_JSON`** (must be valid JSON) or a bad **`PUBLIC_BASE_URL`** for custom domains.

---

## Running without the UI (e.g. daily job)

Put new screenshots in `screenshots/` and call the logic from Python:

```python
from pathlib import Path
from suggestions import get_suggestions_from_directory
from youtube_client import load_youtube_client, build_playlist_from_songs

suggestions = get_suggestions_from_directory(Path("screenshots"), min_weight=1)
songs = [s[0] for s in suggestions]
youtube = load_youtube_client()
_, link, _ = build_playlist_from_songs(youtube, songs)
print(link)
```

You can schedule this with cron, Task Scheduler, or a small runner script.

---

## Config and security

- **`config.py`** – Paths for screenshots, uploads, credentials; min/max length for scraped song lines.
- **`.gitignore`** – Excludes `client_secret.json`, `youtube_credentials.pickle`, and upload/screenshot folders so secrets and user data aren’t committed.

---

## Notes

- **Screenshot reading:** OpenAI Vision costs per image; tune **`OPENAI_VISION_MODEL`** / **`OPENAI_VISION_MAX_SIDE`** if needed.
- **YouTube quota:** Creating playlists and searching consume API quota; for heavy or shared use, monitor usage in the Cloud Console.
