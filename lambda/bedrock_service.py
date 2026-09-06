"""
bedrock_service.py – Strava Storyteller v7
------------------------------------------
Generates a short Strava caption via Claude 3 Haiku, with athlete bio
context and stylistic “power‑phrase” guidance.
"""

from __future__ import annotations
import json, logging, os
from datetime import datetime

import boto3
from weather_service import get_weather

MODEL_ID = os.getenv(
    "BEDROCK_MODEL_ID", "anthropic.claude-3-haiku-20240307-v1:0"
)
REGION = os.getenv("BEDROCK_REGION", "us-east-1")

_br  = boto3.client("bedrock-runtime", region_name=REGION)
_log = logging.getLogger(__name__)


def build_prompt(act: dict, day_num: int, weather: str = "", *, ride_no: int | None = None) -> str:
    """
    Build the full Claude‑Haiku prompt for a single Strava activity.
    • Outputs are laser‑short (≤ 10 words) + original power‑phrase.
    • Adds extra internal tokens (gear, PRs, commute, song, ride counter)
      that Haiku can draw on for color—but never dumps verbatim.
    """
    # ── quick stats ────────────────────────────────────────────────────
    dist_km   = act.get("distance", 0) / 1_000
    move_min  = act.get("moving_time", 0) // 60
    elev_gain = act.get("total_elevation_gain", 0)
    pr_count  = act.get("pr_count", 0)

    when_local = "unknown"
    if "start_date_local" in act:
        try:
            when_local = datetime.fromisoformat(
                act["start_date_local"]
            ).strftime("%A %d %b %Y %I:%M %p")
        except ValueError:
            pass

    # ── extra context tokens ───────────────────────────────────────────
    gear_name  = (act.get("gear") or {}).get("name", "")          # e.g. “Canyon Endurace”
    song_title = act.get("song_title", "")                         # if you pipe Spotify later
    is_commute = bool(act.get("commute"))
    ride_no    = ride_no or "n/a"                                  # inject from a counter if you track one

    # ── system guidance for Haiku ──────────────────────────────────────
    system_block = f"""
You are Ashish’s Strava ghost‑writer.

### Athlete bio (internal, never quote)
- 29‑year‑old Nepali software engineer in Dallas
- 75 Hard disciple: 2×45 min workouts, 4 : 30 AM alarms, daily cold plunge
- Building to Ironman Florida (full, 1 Nov 2025); streak is **Day {day_num}**
- Past feats: 70.3 Waco, two marathons, 50 K ultra, Spartan Trifecta

### Caption contract
1. ONE sentence, ≤ 10 words, everyday language with a dash of swagger.
2. Optionally weave **one** stat (distance *or* time *or* climb) *only* if it sparks interest.
3. Name‑drop one vivid scene detail (weather, sunrise, trail vibe, gear, song, commute feel).
4. Finish with an **original** power‑phrase (≤ 6 words) + up to 2 tasteful emojis.
5. Never repeat the activity title, dump raw stats, add hashtags, or mention AI/prompts.
6. Output plain text only – no Markdown, no extra spaces.

### Dynamic tokens (for inspiration only – do NOT echo verbatim)
- Gear        : {gear_name or 'n/a'}
- PRs today   : {pr_count}
- Commute     : {"yes" if is_commute else "no"}
- Ride counter: {ride_no}
- Song        : {song_title or 'n/a'}
""".strip()

    # ── power‑phrase style examples (do NOT reuse) ─────────────────────
    examples = (
        "Power‑phrase examples (style only, never copy):\n"
        "• Legs charging, spirit soaring.\n"
        "• Quiet grind, loud results.\n"
        "• Fuel the furnace. 🔥\n"
    )

    # ── concise workout snapshot (for Haiku’s eyes only) ───────────────
    ctx_stats = (
        f"Title      : {act.get('name')}\n"
        f"Sport      : {act.get('type')}\n"
        f"Local time : {when_local}\n"
        f"Distance   : {dist_km:.1f} km\n"
        f"Moving min : {move_min}\n"
        f"Elev gain  : {elev_gain:.0f} m\n"
        f"Weather    : {weather or 'n/a'}\n"
    )

    raw_json = json.dumps(act, ensure_ascii=False)[:3000]

    # ── final prompt assembly ──────────────────────────────────────────
    return (
            f"{system_block}\n\n{examples}\n"
            "Workout snapshot (internal):\n" + ctx_stats +
            "\nExtra JSON (internal):\n" + raw_json +
            "\n---\nNow craft the caption:"
    )

def summarize(act: dict, day_num: int) -> str:
    """Call Bedrock/Haiku and return the caption."""
    lat = lon = None
    if isinstance(act.get("start_latlng"), list) and len(act["start_latlng"]) == 2:
        lat, lon = act["start_latlng"]

    weather = get_weather(lat, lon)
    prompt  = build_prompt(act, day_num, weather)

    body = json.dumps(
        {
            "anthropic_version": "bedrock-2023-05-31",
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 120,
            "temperature": 0.7,
            "top_p": 0.9,
        }
    )

    try:
        resp  = _br.invoke_model(
            modelId=MODEL_ID,
            body=body,
            accept="application/json",
            contentType="application/json",
        )
        return json.loads(resp["body"].read())["content"][0]["text"].strip()
    except Exception as exc:
        _log.error("Bedrock invocation failed: %s", exc)
        return ""
