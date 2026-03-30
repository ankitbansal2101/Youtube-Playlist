"""
Picture scraper: extract song lines from screenshots using OpenAI Vision only.
Requires OPENAI_API_KEY, Pillow for image encoding.
"""
from __future__ import annotations

import base64
import io
import json
import os
import re
from pathlib import Path
from typing import List, Tuple

from PIL import Image

from config import MIN_SONG_LENGTH, MAX_SONG_LENGTH, SCREENSHOTS_DIR


def _image_to_data_url(path: Path) -> str:
    """Resize very large images; encode as data URL for OpenAI Vision."""
    path = Path(path)
    img = Image.open(path)
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGB")
    w, h = img.size
    max_side = int(os.environ.get("OPENAI_VISION_MAX_SIDE", "2048"))
    if max(w, h) > max_side:
        scale = max_side / max(w, h)
        img = img.resize((int(w * scale), int(h * scale)), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    ext = path.suffix.lower()
    if ext in (".png",):
        img.save(buf, format="PNG", optimize=True)
        mime = "image/png"
    else:
        if img.mode == "RGBA":
            img = img.convert("RGB")
        img.save(buf, format="JPEG", quality=88)
        mime = "image/jpeg"
    b64 = base64.standard_b64encode(buf.getvalue()).decode("ascii")
    return f"data:{mime};base64,{b64}"


def scrape_image(image_path: Path) -> List[str]:
    """
    Extract song lines from a music-app screenshot via OpenAI Vision.
    Returns deduplicated 'Artist - Title' (or 'Title - Artist') strings.
    """
    try:
        from openai import OpenAI
    except ImportError as e:
        raise ImportError("pip install openai") from e
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        raise ValueError(
            "Set OPENAI_API_KEY in .env or your environment (required for OpenAI Vision screenshot reading)."
        )
    path = Path(image_path)
    if not path.exists():
        raise FileNotFoundError(f"Image not found: {path}")

    model = os.environ.get("OPENAI_VISION_MODEL", "gpt-4o-mini")
    data_url = _image_to_data_url(path)

    system = (
        "You read screenshots from music apps (Spotify, Apple Music, YouTube Music, etc.). "
        "Extract every distinct track row you see as 'Artist - Title' or 'Title - Artist'. "
        "Skip UI chrome (buttons, tabs, time, battery). Skip podcast/episode labels unless they look like songs. "
        "Respond with ONLY valid JSON: {\"songs\": [\"Artist - Title\", ...]} — no markdown, no extra keys."
    )
    client = OpenAI(api_key=key)
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": "List all songs visible in this screenshot as JSON.",
                    },
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            },
        ],
        temperature=0.2,
        max_tokens=2000,
        response_format={"type": "json_object"},
    )
    text = (resp.choices[0].message.content or "").strip()
    data = json.loads(text)
    raw_list = data.get("songs") or data.get("tracks") or []
    out: List[str] = []
    seen = set()
    for item in raw_list:
        if not isinstance(item, str):
            continue
        line = clean_line(item)
        line = re.sub(r"^\d+[\.\)]\s*", "", line)
        line = re.sub(r"\s*[–—]\s*", " - ", line)
        if not line or len(line) < MIN_SONG_LENGTH or len(line) > MAX_SONG_LENGTH:
            continue
        if not looks_like_song_line(line):
            continue
        key_l = line.lower()
        if key_l not in seen:
            seen.add(key_l)
            out.append(line)
    return out


def clean_line(line: str) -> str:
    line = line.strip()
    line = re.sub(r"\s+", " ", line)
    line = re.sub(r"^[\d.\-•·\s]+", "", line)
    return line.strip()


def looks_like_song_line(line: str) -> bool:
    if not line or len(line) < MIN_SONG_LENGTH or len(line) > MAX_SONG_LENGTH:
        return False
    if " - " in line or " – " in line or " — " in line:
        return True
    if re.match(r"^[\w\s\d\'\"\-\.\,\&\ feat\.]+$", line, re.I):
        return True
    return False


def scrape_directory(
    directory: Path = None,
    extensions: Tuple[str, ...] = (".png", ".jpg", ".jpeg", ".webp", ".bmp"),
) -> List[Tuple[Path, List[str]]]:
    directory = directory or SCREENSHOTS_DIR
    directory = Path(directory)
    if not directory.exists():
        return []
    results = []
    for path in sorted(directory.iterdir()):
        if path.suffix.lower() not in extensions:
            continue
        try:
            songs = scrape_image(path)
            results.append((path, songs))
        except Exception:
            results.append((path, []))
    return results


def scrape_uploaded_files(paths: List[Path]) -> List[Tuple[Path, List[str]]]:
    results = []
    for path in paths:
        path = Path(path)
        if not path.exists():
            continue
        try:
            songs = scrape_image(path)
            results.append((path, songs))
        except Exception:
            results.append((path, []))
    return results
