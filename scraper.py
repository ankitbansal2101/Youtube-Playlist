"""
Picture scraper: extract song titles (and artists) from screenshots using OCR.
Outputs normalized "Artist - Title" or "Title - Artist" strings for downstream use.
"""
from pathlib import Path
import re
from typing import List, Tuple

try:
    import pytesseract
    from PIL import Image
except ImportError:
    pytesseract = None
    Image = None

from config import MIN_SONG_LENGTH, MAX_SONG_LENGTH, UPLOADS_DIR, SCREENSHOTS_DIR


def extract_text_from_image(image_path: Path) -> str:
    """Run OCR on an image and return raw text."""
    if Image is None or pytesseract is None:
        raise ImportError("Install Pillow and pytesseract. Also install Tesseract: https://github.com/tesseract-ocr/tesseract")
    path = Path(image_path)
    if not path.exists():
        raise FileNotFoundError(f"Image not found: {path}")
    img = Image.open(path)
    # Prefer full page; for screenshots, default config is usually fine
    text = pytesseract.image_to_string(img)
    return text or ""


def clean_line(line: str) -> str:
    """Normalize a line: strip, collapse spaces, remove noisy chars."""
    line = line.strip()
    line = re.sub(r"\s+", " ", line)
    line = re.sub(r"^[\d.\-•·\s]+", "", line)  # leading numbers/bullets
    return line.strip()


def looks_like_song_line(line: str) -> bool:
    """Heuristic: line could be 'Artist - Song' or 'Song - Artist'."""
    if not line or len(line) < MIN_SONG_LENGTH or len(line) > MAX_SONG_LENGTH:
        return False
    # Often contains a dash or " - " between artist and title
    if " - " in line or " – " in line or " — " in line:
        return True
    # Or just a title (single part)
    if re.match(r"^[\w\s\d\'\"\-\.\,\&\ feat\.]+$", line, re.I):
        return True
    return False


def parse_song_lines(raw_text: str) -> List[str]:
    """From raw OCR text, return list of candidate song lines (normalized)."""
    seen = set()
    out = []
    for line in raw_text.splitlines():
        line = clean_line(line)
        if not line:
            continue
        if not looks_like_song_line(line):
            continue
        # Normalize dash to " - "
        line = re.sub(r"\s*[–—]\s*", " - ", line)
        key = line.lower()
        if key not in seen:
            seen.add(key)
            out.append(line)
    return out


def scrape_image(image_path: Path) -> List[str]:
    """Extract song-like lines from a single image. Returns list of strings."""
    raw = extract_text_from_image(image_path)
    return parse_song_lines(raw)


def scrape_directory(
    directory: Path = None,
    extensions: Tuple[str, ...] = (".png", ".jpg", ".jpeg", ".webp", ".bmp"),
) -> List[Tuple[Path, List[str]]]:
    """
    Scan a directory for images, run OCR on each, return list of
    (image_path, list_of_song_lines) for each image.
    """
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
            results.append((path, []))  # keep path, empty songs so UI can show failure
    return results


def scrape_uploaded_files(paths: List[Path]) -> List[Tuple[Path, List[str]]]:
    """Scrape a list of uploaded file paths. Same return shape as scrape_directory."""
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
