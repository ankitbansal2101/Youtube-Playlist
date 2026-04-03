"""
Use an LLM to suggest additional songs based on songs extracted from screenshots.
Requires OPENAI_API_KEY in project .env (or host env when .env is not deployed).
"""
import json
import os
import re
from typing import List

from config import get_openai_api_key


def _client():
    try:
        from openai import OpenAI
    except ImportError as e:
        raise ImportError("Install the openai package: pip install openai") from e
    key = get_openai_api_key()
    if not key:
        raise ValueError(
            "Set OPENAI_API_KEY in the project .env file in the project folder."
        )
    return OpenAI(api_key=key)


def generate_recommendations(
    seed_songs: List[str],
    *,
    count: int = 10,
    model: str | None = None,
) -> List[str]:
    """
    Given a list of song strings (e.g. 'Artist - Title'), ask the model for similar
    or complementary tracks. Returns a list of 'Artist - Title' strings (no numbering).
    """
    if not seed_songs:
        return []
    count = max(1, min(30, int(count)))
    model = model or os.environ.get("OPENAI_RECOMMEND_MODEL", "gpt-4o-mini")

    seeds = "\n".join(f"- {s}" for s in seed_songs[:50])
    system = (
        "You are a music discovery assistant. Given a list of songs the user already likes, "
        "suggest NEW songs that fit the same vibe, genres, or energy. "
        "Do not repeat any seed song. Prefer well-known artists when possible. "
        "Respond with ONLY valid JSON: {\"recommendations\": [\"Artist - Title\", ...]} "
        f"with exactly {count} items, each a single string 'Artist - Title'."
    )
    user = f"Songs from the group:\n{seeds}\n\nSuggest {count} more songs as JSON."

    client = _client()
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0.7,
        response_format={"type": "json_object"},
    )
    text = (resp.choices[0].message.content or "").strip()
    data = json.loads(text)
    raw = data.get("recommendations") or data.get("songs") or []
    out = []
    seen = {s.lower().strip() for s in seed_songs}
    for item in raw:
        if not isinstance(item, str):
            continue
        line = re.sub(r"^\d+[\.\)]\s*", "", item.strip())
        if not line or len(line) > 200:
            continue
        key = line.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(line)
        if len(out) >= count:
            break
    return out
