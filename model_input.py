"""
Model input layer for external predictions (e.g., friend's Discord model).

Format: JSON file with daily model predictions
Expected structure:
{
    "2026-04-12": [
        {
            "away_team": "SF",
            "home_team": "BAL",
            "away_odds": 110,
            "home_odds": -125,
            "run_diff": 1.11,
            "confidence": 4,
            "projected_winner": "Home"
        },
        ...
    ]
}
"""

import json
import math
import os
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional, List


MODEL_PREDICTIONS_FILE = "model_predictions.json"

MLB_TEAM_ABBR = {
    "ARIZONA DIAMONDBACKS": "ARI",
    "ATLANTA BRAVES": "ATL",
    "BALTIMORE ORIOLES": "BAL",
    "BOSTON RED SOX": "BOS",
    "CHICAGO CUBS": "CHC",
    "CHICAGO WHITE SOX": "CWS",
    "CINCINNATI REDS": "CIN",
    "CLEVELAND GUARDIANS": "CLE",
    "COLORADO ROCKIES": "COL",
    "DETROIT TIGERS": "DET",
    "HOUSTON ASTROS": "HOU",
    "KANSAS CITY ROYALS": "KC",
    "LOS ANGELES ANGELS": "LAA",
    "LOS ANGELES DODGERS": "LAD",
    "MIAMI MARLINS": "MIA",
    "MILWAUKEE BREWERS": "MIL",
    "MINNESOTA TWINS": "MIN",
    "NEW YORK METS": "NYM",
    "NEW YORK YANKEES": "NYY",
    "ATHLETICS": "ATH",
    "OAKLAND ATHLETICS": "ATH",
    "PHILADELPHIA PHILLIES": "PHI",
    "PITTSBURGH PIRATES": "PIT",
    "SAN DIEGO PADRES": "SD",
    "SAN FRANCISCO GIANTS": "SF",
    "SEATTLE MARINERS": "SEA",
    "ST. LOUIS CARDINALS": "STL",
    "ST LOUIS CARDINALS": "STL",
    "TAMPA BAY RAYS": "TB",
    "TEXAS RANGERS": "TEX",
    "TORONTO BLUE JAYS": "TOR",
    "WASHINGTON NATIONALS": "WSH",
}


def _normalize_team_code(team_name: str) -> str:
    if not team_name:
        return ""

    raw = team_name.upper().strip()
    if raw in MLB_TEAM_ABBR:
        return MLB_TEAM_ABBR[raw]

    if len(raw) <= 4:
        return raw

    return raw


def normalize_team_code(team_name: str) -> str:
    """Public wrapper for team normalization used by diagnostics/output."""
    return _normalize_team_code(team_name)


def run_diff_to_win_prob(run_diff: float, scaling: float = 1.5) -> float:
    """
    Convert run differential to win probability via logistic function.
    
    Args:
        run_diff: Projected run differential (e.g., 1.11, -0.96)
        scaling: Scaling factor for the curve (typical: 1.5 for MLB)
    
    Returns:
        Win probability for the team with positive run diff (0.0 to 1.0)
    """
    try:
        # Logistic: 1 / (1 + e^(-x/scaling))
        prob = 1 / (1 + math.exp(-run_diff / scaling))
        return max(0.0, min(1.0, prob))  # Clamp to [0, 1]
    except (OverflowError, ValueError):
        # Extreme values fallback
        return 1.0 if run_diff > 0 else 0.0


def load_model_predictions() -> Dict[str, List[dict]]:
    """Load model predictions from JSON file."""
    if not os.path.exists(MODEL_PREDICTIONS_FILE):
        return {}
    
    try:
        with open(MODEL_PREDICTIONS_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        print(f"Error loading model predictions: {e}")
        return {}


def model_predictions_count(date_str: str) -> int:
    predictions = load_model_predictions()
    return len(predictions.get(date_str, []))


def get_model_prediction(away_team: str, home_team: str, date_str: Optional[str] = None) -> Optional[dict]:
    """
    Get model prediction for a specific matchup.
    
    Args:
        away_team: Away team abbreviation (e.g., "SF")
        home_team: Home team abbreviation (e.g., "BAL")
        date_str: Date string (YYYY-MM-DD). If None, uses today.
    
    Returns:
        Prediction dict with:
            - run_diff: Projected run differential
            - away_win_prob: Away team win probability
            - home_win_prob: Home team win probability
            - confidence: Confidence rank (1-15, lower is better)
    """
    predictions = load_model_predictions()

    if date_str:
        candidate_dates = [date_str]
    else:
        now_utc = datetime.now(timezone.utc).date()
        candidate_dates = [
            now_utc.strftime("%Y-%m-%d"),
            (now_utc - timedelta(days=1)).strftime("%Y-%m-%d"),
            (now_utc + timedelta(days=1)).strftime("%Y-%m-%d"),
        ]
    
    # Normalize team names for matching
    away_norm = _normalize_team_code(away_team)
    home_norm = _normalize_team_code(home_team)
    
    for candidate_date in candidate_dates:
        day_predictions = predictions.get(candidate_date, [])

        for pred in day_predictions:
            pred_away = _normalize_team_code(pred.get("away_team", ""))
            pred_home = _normalize_team_code(pred.get("home_team", ""))

            if pred_away == away_norm and pred_home == home_norm:
                run_diff = pred.get("run_diff", 0.0)
                # Run diff is typically home-centric in the model
                # Positive = home team stronger
                home_win_prob = run_diff_to_win_prob(run_diff)
                away_win_prob = 1.0 - home_win_prob

                return {
                    "run_diff": run_diff,
                    "away_win_prob": away_win_prob,
                    "home_win_prob": home_win_prob,
                    "confidence": pred.get("confidence", 15),  # 1=best, 15=worst
                    "model_rank": pred.get("confidence"),  # Alias for clarity
                    "model_date": candidate_date,
                }
    
    return None


def save_model_predictions(predictions: Dict[str, List[dict]]):
    """Save model predictions to JSON file."""
    with open(MODEL_PREDICTIONS_FILE, "w") as f:
        json.dump(predictions, f, indent=2)
