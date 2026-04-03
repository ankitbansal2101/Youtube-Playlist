"""
Picture scraper: extract song lines from screenshots using OpenAI Vision only.
Requires OPENAI_API_KEY, Pillow for image encoding.
"""
from __future__ import annotations

import base64
import io
import json
import logging
import os
import re
from pathlib import Path
from typing import List, Tuple

from PIL import Image

from config import (
    MAX_SONG_LENGTH,
    MIN_SONG_LENGTH,
    OPENAI_VISION_MODEL_DEFAULT,
    SCREENSHOTS_DIR,
    get_openai_api_key,
)


class VisionOpenAIQuotaError(Exception):
    """OpenAI returned insufficient_quota / billing — not a model or image issue."""


def _is_openai_quota_exhausted(exc: BaseException) -> bool:
    """True for 429 insufficient_quota (no credits / billing)."""
    low = str(exc).lower()
    if "insufficient_quota" in low or "exceeded your current quota" in low:
        return True
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        err = body.get("error")
        if isinstance(err, dict) and err.get("code") == "insufficient_quota":
            return True
    resp = getattr(exc, "response", None)
    if resp is not None:
        try:
            data = resp.json()
            err = data.get("error") if isinstance(data, dict) else None
            if isinstance(err, dict) and err.get("code") == "insufficient_quota":
                return True
        except Exception:
            pass
    return False


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


def _parse_vision_json(text: str) -> dict:
    """Model sometimes wraps JSON in markdown despite response_format."""
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
        text = re.sub(r"\s*```\s*$", "", text)
    return json.loads(text)


def _coerce_song_entry(item) -> str | None:
    """Normalize string or {artist, title} objects from the model."""
    if isinstance(item, str):
        s = item.strip()
        return s if s else None
    if not isinstance(item, dict):
        return None
    artist = (
        item.get("artist")
        or item.get("Artist")
        or item.get("artists")
        or ""
    )
    title = (
        item.get("title")
        or item.get("Title")
        or item.get("song")
        or item.get("name")
        or ""
    )
    if isinstance(artist, list):
        artist = ", ".join(str(a) for a in artist if a)
    if isinstance(title, list):
        title = ", ".join(str(t) for t in title if t)
    artist = str(artist).strip()
    title = str(title).strip()
    if artist and title:
        return f"{artist} - {title}"
    if title:
        return title
    if artist:
        return artist
    return None


def scrape_image(image_path: Path) -> List[str]:
    """
    Extract song lines from a music-app screenshot via OpenAI Vision.
    Returns deduplicated 'Artist - Title' (or 'Title - Artist') strings.
    """
    try:
        from openai import OpenAI
    except ImportError as e:
        raise ImportError("pip install openai") from e
    key = get_openai_api_key()
    if not key:
        raise ValueError(
            "Set OPENAI_API_KEY in the project .env file (required for OpenAI Vision screenshot reading)."
        )
    path = Path(image_path)
    if not path.exists():
        raise FileNotFoundError(f"Image not found: {path}")

    model = (os.environ.get("OPENAI_VISION_MODEL") or "").strip() or OPENAI_VISION_MODEL_DEFAULT
    data_url = _image_to_data_url(path)

    system = (
        "Extract music from this screenshot. If any song title, now-playing bar, or music link preview is visible, "
        "the JSON must list them — never return an empty songs array when music text is on screen.\n"
        "Include: now-playing / mini player (combine artist + title); each chat link-preview card; each row in "
        "similar-artist or track lists. Use 'Artist - Title' strings, or objects {\"artist\":\"...\",\"title\":\"...\"}.\n"
        "Ignore status bar, tabs, battery, timestamps, long bios, 'Provided to YouTube by…' boilerplate.\n"
        "No raw http(s) URLs in strings. Keep feat./remix/subtitle text in the same string.\n"
        "Return only: {\"songs\": [...]}."
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
                        "text": "Return {\"songs\": [...]} with every music item you can read (see system rules).",
                    },
                    {
                        "type": "image_url",
                        "image_url": {"url": data_url, "detail": "high"},
                    },
                ],
            },
        ],
        temperature=0.1,
        max_tokens=4096,
        response_format={"type": "json_object"},
    )
    text = (resp.choices[0].message.content or "").strip()
    try:
        data = _parse_vision_json(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"Vision model returned invalid JSON: {e}") from e
    raw_list = data.get("songs") or data.get("tracks") or []
    if not isinstance(raw_list, list):
        raw_list = []
    out: List[str] = []
    seen = set()
    for item in raw_list:
        coerced = _coerce_song_entry(item)
        if not coerced:
            continue
        line = clean_line(coerced)
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


# Titles with parentheses, brackets, slashes, etc. failed the old strict charset check.
_LINE_JUNK = re.compile(
    r"^(read more|see all|see all releases|see all artists|for you|my collection|search|profile)$",
    re.I,
)


def looks_like_song_line(line: str) -> bool:
    if not line or len(line) < MIN_SONG_LENGTH or len(line) > MAX_SONG_LENGTH:
        return False
    if _LINE_JUNK.match(line.strip()):
        return False
    if " - " in line or " – " in line or " — " in line:
        return True
    # Single-field artist or title: need letters/numbers (unicode-aware)
    if not re.search(r"[\w\d]", line, re.UNICODE):
        return False
    allowed = re.compile(
        r"^[\w\s\d'\".,&/()\[\]:;!?@%#—–\-·+|*=`~♪♫]+$",
        re.UNICODE,
    )
    return bool(allowed.match(line))


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
        except Exception as e:
            if _is_openai_quota_exhausted(e):
                logging.error("OpenAI billing/quota exhausted (%s)", path.name)
                raise VisionOpenAIQuotaError(
                    "OpenAI API reports insufficient quota. Add payment method or credits at "
                    "https://platform.openai.com/account/billing"
                ) from e
            logging.exception("OpenAI Vision failed for %s", path.name)
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
        except Exception as e:
            if _is_openai_quota_exhausted(e):
                logging.error("OpenAI billing/quota exhausted (%s)", path.name)
                raise VisionOpenAIQuotaError(
                    "OpenAI API reports insufficient quota. Add payment method or credits at "
                    "https://platform.openai.com/account/billing"
                ) from e
            logging.exception("OpenAI Vision failed for %s", path.name)
            results.append((path, []))
    return results
