"""
Simple NBA power-rating model using free nba_api data.

Builds team power ratings from:
  1. Season net rating (offensive - defensive rating)
  2. Recent form (last 10 games net rating)
  3. Home court advantage (historical ~3 points)

Converts power differential to win probability via logistic function.
No ML required — this is a Massey-style rating system.
"""

import json
import math
import os
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from nba_api.stats.endpoints import leaguedashteamstats, scoreboardv3
from nba_api.stats.static import teams as nba_teams


# ─── Config ──────────────────────────────────────────────────────────────────
SEASON = "2025-26"
SEASON_TYPE = "Regular Season"
HOME_COURT_ADVANTAGE = 3.0  # ~3 points historically
SEASON_WEIGHT = 0.60
RECENT_WEIGHT = 0.40
CACHE_FILE = "nba_ratings_cache.json"
CACHE_TTL_HOURS = 6


def _get_team_map() -> Dict[int, dict]:
    """Map team_id -> team info."""
    return {t["id"]: t for t in nba_teams.get_teams()}


def _fetch_team_ratings(last_n: int = 0) -> Dict[int, dict]:
    """Fetch advanced team stats from nba_api. last_n=0 means full season."""
    kwargs = {
        "season": SEASON,
        "season_type_all_star": SEASON_TYPE,
        "per_mode_detailed": "PerGame",
        "measure_type_detailed_defense": "Advanced",
    }
    if last_n > 0:
        kwargs["last_n_games"] = last_n

    stats = leaguedashteamstats.LeagueDashTeamStats(**kwargs)
    df = stats.get_data_frames()[0]

    ratings = {}
    for _, row in df.iterrows():
        ratings[int(row["TEAM_ID"])] = {
            "team_name": row["TEAM_NAME"],
            "w": int(row["W"]),
            "l": int(row["L"]),
            "w_pct": float(row["W_PCT"]),
            "off_rating": float(row["OFF_RATING"]),
            "def_rating": float(row["DEF_RATING"]),
            "net_rating": float(row["NET_RATING"]),
            "pace": float(row["PACE"]),
        }
    return ratings


def _logistic_prob(rating_diff: float, scale: float = 7.5) -> float:
    """Convert point differential to win probability via logistic function.
    
    Scale of 7.5 means a 7.5-point rating advantage ≈ 73% win probability.
    This is calibrated to historical NBA data.
    """
    return 1.0 / (1.0 + math.exp(-rating_diff / scale))


def build_power_ratings() -> Dict[int, dict]:
    """Build blended power ratings (season + recent form).
    
    Returns dict keyed by team_id with:
      - power_rating: blended net rating
      - season_net: full season net rating
      - recent_net: last 10 games net rating
      - team_name, w, l, w_pct
    """
    # Check cache
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r") as f:
                cache = json.load(f)
            cached_at = datetime.fromisoformat(cache["cached_at"])
            if datetime.now() - cached_at < timedelta(hours=CACHE_TTL_HOURS):
                return {int(k): v for k, v in cache["ratings"].items()}
        except (json.JSONDecodeError, KeyError, ValueError):
            pass

    # Fetch fresh data
    season_ratings = _fetch_team_ratings(last_n=0)
    time.sleep(1)  # Rate limit courtesy
    recent_ratings = _fetch_team_ratings(last_n=10)

    power = {}
    for team_id, season in season_ratings.items():
        recent = recent_ratings.get(team_id, season)
        blended_net = (SEASON_WEIGHT * season["net_rating"]) + (RECENT_WEIGHT * recent["net_rating"])

        power[team_id] = {
            "team_name": season["team_name"],
            "w": season["w"],
            "l": season["l"],
            "w_pct": season["w_pct"],
            "season_net": season["net_rating"],
            "recent_net": recent["net_rating"],
            "power_rating": round(blended_net, 2),
            "off_rating": season["off_rating"],
            "def_rating": season["def_rating"],
            "pace": season["pace"],
        }

    # Cache
    cache_data = {
        "cached_at": datetime.now().isoformat(),
        "ratings": {str(k): v for k, v in power.items()},
    }
    with open(CACHE_FILE, "w") as f:
        json.dump(cache_data, f, indent=2)

    return power


def predict_game(
    away_team_id: int,
    home_team_id: int,
    power_ratings: Optional[Dict[int, dict]] = None,
) -> Optional[Dict]:
    """Predict a single NBA game.
    
    Returns dict with:
      - away_win_prob, home_win_prob
      - rating_diff (home advantage included)
      - power ratings for both teams
      - model_explanation: human-readable breakdown
    """
    if power_ratings is None:
        power_ratings = build_power_ratings()

    away = power_ratings.get(away_team_id)
    home = power_ratings.get(home_team_id)

    if not away or not home:
        return None

    # Rating diff from home team's perspective (positive = home favored)
    raw_diff = home["power_rating"] - away["power_rating"]
    adjusted_diff = raw_diff + HOME_COURT_ADVANTAGE

    home_win_prob = _logistic_prob(adjusted_diff)
    away_win_prob = 1.0 - home_win_prob

    explanation = (
        f"Power: {home['team_name']} {home['power_rating']:+.1f} vs {away['team_name']} {away['power_rating']:+.1f} "
        f"| Raw diff: {raw_diff:+.1f} | +HCA {HOME_COURT_ADVANTAGE:.1f} = {adjusted_diff:+.1f} "
        f"| Season NR: {home['season_net']:+.1f} vs {away['season_net']:+.1f} "
        f"| L10 NR: {home['recent_net']:+.1f} vs {away['recent_net']:+.1f}"
    )

    return {
        "away_team": away["team_name"],
        "home_team": home["team_name"],
        "away_win_prob": round(away_win_prob, 4),
        "home_win_prob": round(home_win_prob, 4),
        "rating_diff": round(adjusted_diff, 2),
        "home_power": home["power_rating"],
        "away_power": away["power_rating"],
        "explanation": explanation,
    }


def predict_todays_games() -> List[Dict]:
    """Predict all of today's NBA games.
    
    Returns list of prediction dicts.
    """
    power_ratings = build_power_ratings()
    team_map = _get_team_map()

    time.sleep(1)
    today = datetime.now().strftime("%Y-%m-%d")
    sb = scoreboardv3.ScoreboardV3(game_date=today)
    dfs = sb.get_data_frames()
    # Find the GameHeader frame (has HOME_TEAM_ID)
    games_df = None
    for df in dfs:
        if "HOME_TEAM_ID" in df.columns:
            games_df = df
            break
    if games_df is None or games_df.empty:
        return []
    games_df = games_df.drop_duplicates(subset=["GAME_ID"])

    predictions = []
    for _, game in games_df.iterrows():
        home_id = int(game["HOME_TEAM_ID"])
        away_id = int(game["VISITOR_TEAM_ID"])

        pred = predict_game(away_id, home_id, power_ratings)
        if pred:
            pred["game_id"] = str(game["GAME_ID"])
            pred["game_status"] = game.get("GAME_STATUS_TEXT", "")
            predictions.append(pred)

    return predictions


def get_nba_model_predictions_for_ev(power_ratings: Optional[Dict[int, dict]] = None) -> List[Dict]:
    """Format NBA model predictions for the EV calculator pipeline.
    
    Returns list of dicts compatible with model_input format:
      - away_team, home_team, predicted_winner, win_prob, rank, explanation
    """
    if power_ratings is None:
        power_ratings = build_power_ratings()

    team_map = _get_team_map()

    time.sleep(1)
    today = datetime.now().strftime("%Y-%m-%d")
    sb = scoreboardv3.ScoreboardV3(game_date=today)
    dfs = sb.get_data_frames()
    games_df = None
    for df in dfs:
        if "HOME_TEAM_ID" in df.columns:
            games_df = df
            break
    if games_df is None or games_df.empty:
        return []
    games_df = games_df.drop_duplicates(subset=["GAME_ID"])

    results = []
    for _, game in games_df.iterrows():
        home_id = int(game["HOME_TEAM_ID"])
        away_id = int(game["VISITOR_TEAM_ID"])

        pred = predict_game(away_id, home_id, power_ratings)
        if not pred:
            continue

        # Determine predicted winner and confidence
        if pred["home_win_prob"] > pred["away_win_prob"]:
            winner = pred["home_team"]
            confidence = pred["home_win_prob"]
        else:
            winner = pred["away_team"]
            confidence = pred["away_win_prob"]

        # Rank by edge magnitude (how far from 50/50)
        edge = abs(confidence - 0.5)

        results.append({
            "away_team": pred["away_team"],
            "home_team": pred["home_team"],
            "predicted_winner": winner,
            "away_prob": pred["away_win_prob"],
            "home_prob": pred["home_win_prob"],
            "confidence": confidence,
            "edge": edge,
            "explanation": pred["explanation"],
        })

    # Sort by edge descending, assign ranks
    results.sort(key=lambda x: x["edge"], reverse=True)
    for i, r in enumerate(results):
        r["rank"] = i + 1

    return results


if __name__ == "__main__":
    print("Building NBA power ratings...\n")
    ratings = build_power_ratings()

    # Show top 10 teams
    sorted_teams = sorted(ratings.values(), key=lambda x: x["power_rating"], reverse=True)
    print(f"{'Team':<25} {'Power':>7} {'Season':>8} {'L10':>8} {'Record':>8}")
    print("-" * 60)
    for t in sorted_teams[:10]:
        print(f"{t['team_name']:<25} {t['power_rating']:>+7.1f} {t['season_net']:>+8.1f} {t['recent_net']:>+8.1f} {t['w']}-{t['l']:>3}")

    print("\n--- Today's Predictions ---\n")
    preds = get_nba_model_predictions_for_ev(ratings)
    if not preds:
        print("No NBA games today.")
    for p in preds:
        print(f"#{p['rank']} {p['away_team']} @ {p['home_team']}")
        print(f"   Pick: {p['predicted_winner']} ({p['confidence']*100:.1f}%)")
        print(f"   {p['explanation']}\n")
