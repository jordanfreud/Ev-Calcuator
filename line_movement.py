"""
Line movement tracking and signal generation.

Detects when sharp money has moved odds, indicating market consensus shift.
Now returns a SIGNED signal: positive = away strengthened, negative = home strengthened.
"""

import json
import os
from datetime import datetime, timezone
from typing import Dict, List, Tuple, Optional

from config import STALE_LINE_THRESHOLD_HOURS


LINE_HISTORY_FILE = "line_history.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def record_line_snapshot(event_id: str, book_name: str, away_odds: int, home_odds: int) -> None:
    """Record current line for an event to track movement."""
    history = _load_line_history()

    if event_id not in history:
        history[event_id] = {}

    if book_name not in history[event_id]:
        history[event_id][book_name] = []

    entry = {
        "timestamp": _now_iso(),
        "away_odds": away_odds,
        "home_odds": home_odds,
    }

    history[event_id][book_name].append(entry)
    _save_line_history(history)


def get_market_line_signal(event_id: str, candidate_lines: List[Tuple[str, int, int]]) -> float:
    """
    Consensus line-movement signal across all candidate books.

    Returns a SIGNED signal in [-0.05, +0.05]:
      - Positive: away team probability increased (away got sharper action)
      - Negative: home team probability increased (home got sharper action)
      - Zero: no meaningful movement or no history

    candidate_lines format: [(book_title, odds_home, odds_away), ...]
    """
    history = _load_line_history()
    event_history = history.get(event_id, {})

    if not candidate_lines:
        return 0.0

    away_deltas = []
    home_deltas = []

    for book_title, odds_home, odds_away in candidate_lines:
        book_history = event_history.get(book_title, [])
        if not book_history:
            continue

        opening = book_history[0]
        open_away_odds = opening.get("away_odds")
        open_home_odds = opening.get("home_odds")
        if open_away_odds is None or open_home_odds is None:
            continue

        open_away_prob, open_home_prob = _no_vig_pair(open_away_odds, open_home_odds)
        now_away_prob, now_home_prob = _no_vig_pair(odds_away, odds_home)

        # Signed delta: positive means that side's probability INCREASED
        away_deltas.append(now_away_prob - open_away_prob)
        home_deltas.append(now_home_prob - open_home_prob)

    if not away_deltas:
        return 0.0

    avg_away_delta = sum(away_deltas) / len(away_deltas)
    avg_home_delta = sum(home_deltas) / len(home_deltas)

    # Return the stronger directional signal, bounded to [-0.05, +0.05]
    if abs(avg_away_delta) >= abs(avg_home_delta):
        # Away moved more — positive signal means away strengthened
        return max(-0.05, min(0.05, avg_away_delta * 2.0))
    else:
        # Home moved more — negative signal means home strengthened
        return max(-0.05, min(0.05, -avg_home_delta * 2.0))


def detect_stale_lines(event_id: str, candidate_lines: List[Tuple[str, int, int]]) -> List[str]:
    """
    Detect books whose lines haven't updated recently.

    Returns list of book names with stale lines (no update in STALE_LINE_THRESHOLD_HOURS).
    Stale lines are a major source of phantom edge — the line may no longer exist.
    """
    history = _load_line_history()
    event_history = history.get(event_id, {})
    now = datetime.now(timezone.utc)
    stale_books = []

    for book_title, _, _ in candidate_lines:
        book_history = event_history.get(book_title, [])
        if len(book_history) < 2:
            # Only one snapshot — can't determine staleness, but flag if old
            if book_history:
                ts = _parse_timestamp(book_history[-1].get("timestamp", ""))
                if ts and (now - ts).total_seconds() / 3600 > STALE_LINE_THRESHOLD_HOURS:
                    stale_books.append(book_title)
            continue

        last_ts = _parse_timestamp(book_history[-1].get("timestamp", ""))
        if last_ts and (now - last_ts).total_seconds() / 3600 > STALE_LINE_THRESHOLD_HOURS:
            stale_books.append(book_title)

    return stale_books


def _parse_timestamp(ts_str: str) -> Optional[datetime]:
    if not ts_str:
        return None
    try:
        return datetime.fromisoformat(ts_str)
    except ValueError:
        return None


def _american_to_prob(odds: int) -> float:
    if odds > 0:
        return 100 / (odds + 100)
    return -odds / (-odds + 100)


def _no_vig_pair(away_odds: int, home_odds: int) -> Tuple[float, float]:
    away = _american_to_prob(away_odds)
    home = _american_to_prob(home_odds)
    total = away + home
    if total <= 0:
        return 0.5, 0.5
    return away / total, home / total


def _load_line_history() -> Dict:
    if not os.path.exists(LINE_HISTORY_FILE):
        return {}
    try:
        with open(LINE_HISTORY_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}


def _save_line_history(history: Dict) -> None:
    with open(LINE_HISTORY_FILE, "w") as f:
        json.dump(history, f, indent=2)
