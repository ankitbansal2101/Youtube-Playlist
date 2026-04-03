"""
Aggregate scraped song lines and assign weights.
Weight = number of times a song appears (across screenshots) so popular picks rank higher.
"""
from collections import defaultdict
from pathlib import Path
from typing import List, Tuple

from scraper import scrape_directory, scrape_uploaded_files


def normalize_for_key(s: str) -> str:
    """Normalize string for deduplication (lowercase, collapse spaces)."""
    return " ".join(s.lower().split()).strip()


def aggregate_songs(
    results: List[Tuple[Path, List[str]]],
    min_weight: int = 1,
) -> List[Tuple[str, int, List[Path]]]:
    """
    From list of (image_path, song_lines), aggregate by song string.
    Returns list of (song_string, weight, list_of_source_paths) sorted by weight descending.
    """
    # song_key -> (display_string, weight, set of source paths)
    by_key: dict[str, Tuple[str, int, set]] = defaultdict(lambda: ("", 0, set()))
    for path, lines in results:
        for line in lines:
            if not line.strip():
                continue
            key = normalize_for_key(line)
            prev_display, count, sources = by_key[key]
            by_key[key] = (line.strip(), count + 1, sources | {path})
    out = []
    for key, (display, weight, sources) in by_key.items():
        if weight >= min_weight:
            out.append((display, weight, sorted(sources)))
    out.sort(key=lambda x: (-x[1], x[0]))
    return out


def get_suggestions_from_directory(
    directory: Path = None,
    min_weight: int = 1,
) -> List[Tuple[str, int, List[Path]]]:
    """Scrape directory then return weighted suggestions."""
    results = scrape_directory(directory)
    return aggregate_songs(results, min_weight=min_weight)


def get_suggestions_from_uploads(
    paths: List[Path],
    min_weight: int = 1,
) -> List[Tuple[str, int, List[Path]]]:
    """Scrape uploaded files then return weighted suggestions."""
    results = scrape_uploaded_files(paths)
    return aggregate_songs(results, min_weight=min_weight)


def aggregate_uploads_with_raw_count(
    paths: List[Path],
    min_weight: int = 1,
) -> tuple[List[Tuple[str, int, List[Path]]], int]:
    """Like get_suggestions_from_uploads; also returns count of raw lines before min_weight filter."""
    results = scrape_uploaded_files(paths)
    raw_count = sum(len(lines) for _, lines in results)
    return aggregate_songs(results, min_weight=min_weight), raw_count


def aggregate_directory_with_raw_count(
    directory: Path = None,
    min_weight: int = 1,
) -> tuple[List[Tuple[str, int, List[Path]]], int]:
    results = scrape_directory(directory)
    raw_count = sum(len(lines) for _, lines in results)
    return aggregate_songs(results, min_weight=min_weight), raw_count
