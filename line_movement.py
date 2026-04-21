"""
Line movement tracking and signal generation.

Detects when sharp money has moved odds, indicating agreement with our model.
"""

import json
import os
from datetime import datetime, timezone
from typing import Dict


LINE_HISTORY_FILE = "line_history.json"


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def record_line_snapshot(event_id: str, book_name: str, away_odds: int, home_odds: int):
    """Record current line for an event to track movement."""
    history = _load_line_history()
    
    if event_id not in history:
        history[event_id] = {}
    
    if book_name not in history[event_id]:
        history[event_id][book_name] = []
    
    # Add timestamp
    entry = {
        "timestamp": _now_iso(),
        "away_odds": away_odds,
        "home_odds": home_odds
    }
    
    history[event_id][book_name].append(entry)
    _save_line_history(history)


def get_line_movement_signal(event_id: str, book_name: str, current_away_odds: int, current_home_odds: int) -> float:
    """
    Calculate line movement signal (0.0 to 1.0).
    
    Returns:
        0.0: No movement detected
        +0.01-0.05: Sharp money moved odds (confidence boost)
        
    Logic:
    - If odds moved to higher payout (e.g., -110 to -105), sharp money backed it
    - If sharp books all moved same direction, strong signal
    """
    history = _load_line_history()
    
    if event_id not in history or book_name not in history[event_id]:
        return 0.0
    
    book_history = history[event_id][book_name]
    if len(book_history) < 1:
        return 0.0
    
    # Get the oldest line (opening)
    opening = book_history[0]
    opening_away = opening.get("away_odds", 0)
    opening_home = opening.get("home_odds", 0)
    
    # Calculate movement
    away_movement = current_away_odds - opening_away
    home_movement = current_home_odds - opening_home
    
    # Positive movement (odds got better) = sharp money
    # e.g., away_odds from -110 to -105 (+5) = sharp likes away
    # In American odds, higher positive = better for underdog, lower negative = better for favorite
    
    # Simple signal: any movement >= 5 points indicates sharp activity
    movement_signal = 0.0
    
    if abs(away_movement) >= 5:
        movement_signal = min(0.05, abs(away_movement) * 0.01)
    
    if abs(home_movement) >= 5:
        movement_signal = min(0.05, abs(home_movement) * 0.01)
    
    return movement_signal


def _american_to_prob(odds: int) -> float:
    if odds > 0:
        return 100 / (odds + 100)
    return -odds / (-odds + 100)


def _no_vig_pair(away_odds: int, home_odds: int):
    away = _american_to_prob(away_odds)
    home = _american_to_prob(home_odds)
    total = away + home
    if total <= 0:
        return 0.5, 0.5
    return away / total, home / total


def get_market_line_signal(event_id: str, candidate_lines) -> float:
    """
    Consensus line-movement signal across all candidate books.

    candidate_lines format: [(book_title, odds_home, odds_away), ...]
    Returns a bounded signal in [0.0, 0.05].
    """
    history = _load_line_history()
    event_history = history.get(event_id, {})

    if not candidate_lines:
        return 0.0

    opening_away_probs = []
    opening_home_probs = []
    current_away_probs = []
    current_home_probs = []

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

        opening_away_probs.append(open_away_prob)
        opening_home_probs.append(open_home_prob)
        current_away_probs.append(now_away_prob)
        current_home_probs.append(now_home_prob)

    if not opening_away_probs:
        return 0.0

    avg_open_away = sum(opening_away_probs) / len(opening_away_probs)
    avg_open_home = sum(opening_home_probs) / len(opening_home_probs)
    avg_now_away = sum(current_away_probs) / len(current_away_probs)
    avg_now_home = sum(current_home_probs) / len(current_home_probs)

    delta_away = abs(avg_now_away - avg_open_away)
    delta_home = abs(avg_now_home - avg_open_home)

    # Convert probability shift into bounded blend signal.
    # Example: 2.5 percentage-point move => 0.05 max signal.
    strongest_delta = max(delta_away, delta_home)
    return min(0.05, strongest_delta * 2.0)


def _load_line_history() -> Dict:
    """Load line movement history."""
    if not os.path.exists(LINE_HISTORY_FILE):
        return {}
    
    try:
        with open(LINE_HISTORY_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}


def _save_line_history(history: Dict):
    """Save line movement history."""
    with open(LINE_HISTORY_FILE, "w") as f:
        json.dump(history, f, indent=2)
