"""
Picture scraper: extract song titles from screenshots.
Uses OpenAI Vision when OPENAI_API_KEY is set; otherwise Tesseract (local).
"""
import base64
import json
import os
import re
from pathlib import Path
from typing import List, Tuple

from config import (
    MAX_SONG_LENGTH,
    MIN_SONG_LENGTH,
    OPENAI_VISION_MODEL,
    SCREENSHOTS_DIR,
)

try:
    import pytesseract
    from PIL import Image
except ImportError:
    pytesseract = None
    Image = None

_MIME_BY_EXT = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
}


def _openai_key_set() -> bool:
    return bool(os.environ.get("OPENAI_API_KEY", "").strip())


def _mime_for_path(path: Path) -> str:
    return _MIME_BY_EXT.get(path.suffix.lower(), "image/png")


def extract_songs_openai_vision(image_path: Path) -> List[str]:
    """Use OpenAI vision to list songs from a music-app screenshot."""
    try:
        from openai import OpenAI
    except ImportError as e:
        raise ImportError("Install openai: pip install openai") from e

    path = Path(image_path)
    if not path.exists():
        raise FileNotFoundError(f"Image not found: {path}")

    raw_bytes = path.read_bytes()
    b64 = base64.standard_b64encode(raw_bytes).decode("ascii")
    mime = _mime_for_path(path)
    data_url = f"data:{mime};base64,{b64}"

    client = OpenAI()
    system = (
        "You read screenshots of music apps (Spotify, Apple Music, YouTube Music, etc.). "
        "Extract every distinct song row visible. Output JSON only."
    )
    user_text = (
        'Return JSON: {"songs": ["Artist - Title", ...]}. '
        "Use a single hyphen with spaces: \" - \" between artist and title. "
        "Skip UI chrome, section headers, and duplicates. "
        "If only a title is visible, use \"Unknown Artist - Title\"."
    )

    resp = client.chat.completions.create(
        model=OPENAI_VISION_MODEL,
        messages=[
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": user_text},
                    {"type": "image_url", "image_url": {"url": data_url, "detail": "auto"}},
                ],
            },
        ],
        response_format={"type": "json_object"},
        max_tokens=2000,
    )
    text = (resp.choices[0].message.content or "").strip()
    data = json.loads(text)
    raw_list = data.get("songs") or data.get("tracks") or []
    out = []
    seen = set()
    for item in raw_list:
        if not isinstance(item, str):
            continue
        line = clean_line(re.sub(r"^\d+[\.\)]\s*", "", item.strip()))
        if not line or len(line) < MIN_SONG_LENGTH or len(line) > MAX_SONG_LENGTH:
            continue
        line = re.sub(r"\s*[–—]\s*", " - ", line)
        key = line.lower()
        if key not in seen:
            seen.add(key)
            out.append(line)
    return out


def extract_text_tesseract(image_path: Path) -> str:
    """Run Tesseract OCR on an image and return raw text."""
    if Image is None or pytesseract is None:
        raise ImportError(
            "Install Pillow and pytesseract, and system Tesseract, or set OPENAI_API_KEY for OpenAI Vision."
        )
    path = Path(image_path)
    if not path.exists():
        raise FileNotFoundError(f"Image not found: {path}")
    img = Image.open(path)
    text = pytesseract.image_to_string(img)
    return text or ""


def extract_text_from_image(image_path: Path) -> str:
    """Raw text from image (Tesseract only; OpenAI path uses structured JSON in scrape_image)."""
    return extract_text_tesseract(image_path)


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


def parse_song_lines(raw_text: str) -> List[str]:
    seen = set()
    out = []
    for line in raw_text.splitlines():
        line = clean_line(line)
        if not line:
            continue
        if not looks_like_song_line(line):
            continue
        line = re.sub(r"\s*[–—]\s*", " - ", line)
        key = line.lower()
        if key not in seen:
            seen.add(key)
            out.append(line)
    return out


def scrape_image(image_path: Path) -> List[str]:
    """Extract song-like lines from a single image."""
    path = Path(image_path)
    if _openai_key_set():
        return extract_songs_openai_vision(path)
    raw = extract_text_tesseract(path)
    return parse_song_lines(raw)


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
