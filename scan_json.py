#!/usr/bin/env python3
"""
Headless EV scanner that outputs JSON to stdout.
Used by the web app's scheduled scan to get structured pick data.

Usage:
    python scan_json.py                    # Scan today
    python scan_json.py --date 2026-04-21  # Scan specific date
    python scan_json.py --sports basketball_nba  # NBA only
"""
import json
import sys
import argparse
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional, Tuple

from config import (
    CALIBRATION_SHRINK,
    CANDIDATE_BOOKS,
    DEFAULT_SHARP_WEIGHT,
    DYNAMIC_CALIBRATION_ENABLED,
    DYNAMIC_CALIBRATION_MIN_PICKS,
    EXTREME_PLUS_MONEY,
    KELLY_FRACTION,
    KELLY_MAX_BET_FRACTION,
    LINE_WEIGHT,
    MARKET_WEIGHT,
    MAX_LOOKAHEAD_HOURS,
    MAX_MODEL_RANK_FOR_EXTREME,
    MIN_PROBABILITY_EDGE,
    MIN_REFERENCE_BOOKS,
    MIN_TOTAL_BOOKS_PER_GAME,
    MODEL_WEIGHT,
    REPORT_TIMEZONE,
    SHARP_BOOK_WEIGHTS,
)
from odds_api import get_odds
from probability import american_to_prob, remove_vig, sharp_probability, calibrated_hybrid_probability
from ev_calculator import calculate_ev, calculate_kelly
from model_input import get_model_prediction, normalize_team_code
from line_movement import record_line_snapshot, get_market_line_signal, detect_stale_lines
from bet_tracker import performance_diagnostics


def _normalize_book_name(title: str) -> str:
    normalized = "".join(ch for ch in (title or "").lower() if ch.isalnum())
    aliases = {"betonline": "betonlineag", "caesarssportsbook": "caesars", "williamhillus": "caesars"}
    return aliases.get(normalized, normalized)


def _get_sharp_weight(book_title: str) -> float:
    return SHARP_BOOK_WEIGHTS.get(_normalize_book_name(book_title), DEFAULT_SHARP_WEIGHT)


def _parse_commence_time(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _is_real_matchup(game: Dict[str, Any]) -> bool:
    if not game.get("id"):
        return False
    commence_time = _parse_commence_time(game.get("commence_time"))
    if not commence_time:
        return False
    hours_to_start = (commence_time - datetime.now(timezone.utc)).total_seconds() / 3600.0
    if hours_to_start > MAX_LOOKAHEAD_HOURS:
        return False
    bookmakers = game.get("bookmakers") or []
    if len(bookmakers) < MIN_TOTAL_BOOKS_PER_GAME:
        return False
    return True


def _on_scan_date(game: Dict[str, Any], scan_date: str) -> bool:
    commence_time = _parse_commence_time(game.get("commence_time"))
    if not commence_time:
        return False
    return commence_time.astimezone(REPORT_TIMEZONE).date().isoformat() == scan_date


def _local_game_date(game: Dict[str, Any]) -> Optional[str]:
    commence_time = _parse_commence_time(game.get("commence_time"))
    if not commence_time:
        return None
    return commence_time.astimezone(REPORT_TIMEZONE).date().isoformat()


def _extract_prices(outcomes, home_team, away_team):
    if len(outcomes) != 2:
        return None
    prices = {row.get("name"): row.get("price") for row in outcomes}
    if home_team not in prices or away_team not in prices:
        return None
    return prices[home_team], prices[away_team]


def _select_best(candidate_lines, home_team, target_team):
    best_book, best_odds, dk_odds = None, None, None
    for book_title, odds_home, odds_away in candidate_lines:
        team_odds = odds_home if target_team == home_team else odds_away
        if best_odds is None or team_odds > best_odds:
            best_odds = team_odds
            best_book = book_title
        if _normalize_book_name(book_title) == "draftkings":
            dk_odds = team_odds
    return best_book, best_odds, dk_odds


def _get_dynamic_calibration_shrink() -> float:
    if not DYNAMIC_CALIBRATION_ENABLED:
        return CALIBRATION_SHRINK
    try:
        diag = performance_diagnostics()
        sports = diag.get("sports", {})
        total_graded = sum(s.get("graded", 0) for s in sports.values())
        if total_graded < DYNAMIC_CALIBRATION_MIN_PICKS:
            return CALIBRATION_SHRINK
        total_brier = sum(s.get("avg_brier", 0.25) * s.get("graded", 0) for s in sports.values())
        avg_brier = total_brier / total_graded if total_graded > 0 else 0.25
        if avg_brier < 0.22:
            return 0.0
        elif avg_brier > 0.28:
            return 0.08
        else:
            return (avg_brier - 0.22) / (0.28 - 0.22) * 0.08
    except Exception:
        return CALIBRATION_SHRINK


def scan_ev_bets(
    scan_date: Optional[str] = None,
    sports_filter: Optional[List[str]] = None,
    ev_floor: float = 0.0001,
    min_edge: Optional[float] = None,
) -> Dict[str, Any]:
    """Run the EV scanner and return structured JSON data."""
    if scan_date is None:
        scan_date = datetime.now(REPORT_TIMEZONE).date().isoformat()

    calibration_shrink = _get_dynamic_calibration_shrink()
    data = get_odds(sports_filter=sports_filter) if sports_filter else get_odds()

    result = {
        "scan_date": scan_date,
        "calibration_shrink": round(calibration_shrink, 4),
        "picks": [],
        "errors": [],
    }

    if not data:
        result["errors"].append("No data returned from odds API")
        return result

    qualifying = [g for g in data if _is_real_matchup(g)]
    games = [g for g in qualifying if _on_scan_date(g, scan_date)]

    if not games:
        available = sorted({d for d in (_local_game_date(g) for g in qualifying) if d})
        nearest = [d for d in available if d >= scan_date]
        fallback = nearest[0] if nearest else (available[-1] if available else None)
        if fallback and fallback != scan_date:
            scan_date = fallback
            result["scan_date"] = scan_date
            games = [g for g in qualifying if _on_scan_date(g, scan_date)]

    if not games:
        result["errors"].append(f"No qualifying games for {scan_date}")
        return result

    bets = []

    for game in games:
        event_id = game.get("id")
        home_team = game.get("home_team")
        away_team = game.get("away_team")
        sport = game.get("sport_key", "unknown")

        ref_prob_pairs, ref_odds_list, ref_weights = [], [], []
        candidate_lines = []

        for bk in game.get("bookmakers", []):
            markets = bk.get("markets")
            if not markets:
                continue
            outcomes = markets[0].get("outcomes", [])
            prices = _extract_prices(outcomes, home_team, away_team)
            if not prices:
                continue
            oh, oa = prices
            ph, pa = american_to_prob(oh), american_to_prob(oa)
            nvh, nva = remove_vig(ph, pa)
            normalized = _normalize_book_name(bk.get("title"))
            if normalized in CANDIDATE_BOOKS:
                candidate_lines.append((bk.get("title"), oh, oa))
            else:
                ref_prob_pairs.append((nvh, nva))
                ref_odds_list.append((oh, oa))
                ref_weights.append(_get_sharp_weight(bk.get("title")))

        if not candidate_lines:
            continue

        if len(ref_prob_pairs) < MIN_REFERENCE_BOOKS:
            for _, oh, oa in candidate_lines:
                ph, pa = american_to_prob(oh), american_to_prob(oa)
                nvh, nva = remove_vig(ph, pa)
                ref_prob_pairs.append((nvh, nva))
                ref_odds_list.append((oh, oa))
                ref_weights.append(DEFAULT_SHARP_WEIGHT)

        if len(ref_prob_pairs) < 2:
            continue

        sharp_probs = sharp_probability(ref_prob_pairs, ref_odds_list, ref_weights)
        if not sharp_probs:
            continue

        market_prob_home, market_prob_away = sharp_probs

        model_pred = get_model_prediction(away_team, home_team, date_str=scan_date)
        model_prob_pair = None
        model_source = "market_only"

        for bt, oh, oa in candidate_lines:
            record_line_snapshot(event_id, bt, oa, oh)

        line_signal = get_market_line_signal(event_id, candidate_lines)
        stale_books = detect_stale_lines(event_id, candidate_lines)

        if model_pred:
            model_prob_pair = (model_pred["away_win_prob"], model_pred["home_win_prob"])
            model_source = f"model (rank {model_pred.get('confidence', '?')})"

        (true_prob_away, true_prob_home), blend = calibrated_hybrid_probability(
            market_prob_pair=(market_prob_away, market_prob_home),
            model_prob_pair=model_prob_pair,
            line_signal=line_signal,
            market_weight=MARKET_WEIGHT,
            model_weight=MODEL_WEIGHT,
            line_weight=LINE_WEIGHT,
            calibration_shrink=calibration_shrink,
        )

        for team, true_prob, is_home in [
            (home_team, true_prob_home, True),
            (away_team, true_prob_away, False),
        ]:
            best_book, best_odds, dk_odds = _select_best(
                candidate_lines, home_team, team
            )
            if best_odds is None:
                continue

            ev = calculate_ev(true_prob, best_odds)
            implied_prob = american_to_prob(best_odds)
            prob_edge = true_prob - implied_prob
            kelly = calculate_kelly(true_prob, best_odds, KELLY_FRACTION, KELLY_MAX_BET_FRACTION)

            if ev < ev_floor:
                continue
            if min_edge is not None and prob_edge < min_edge:
                continue
            if best_odds >= EXTREME_PLUS_MONEY and (not model_pred or int(model_pred.get("confidence", 99)) > MAX_MODEL_RANK_FOR_EXTREME):
                continue

            market_prob = market_prob_home if is_home else market_prob_away
            model_prob = None
            if model_pred:
                model_prob = model_pred.get("home_win_prob") if is_home else model_pred.get("away_win_prob")
            base_blend = blend["base_blend_home"] if is_home else blend["base_blend_away"]

            bets.append({
                "sport": sport,
                "away_team": away_team,
                "home_team": home_team,
                "picked_team": team,
                "side": "home" if is_home else "away",
                "best_book": best_book,
                "best_odds": int(best_odds),
                "implied_prob": round(implied_prob, 4),
                "ev_percent": round(ev * 100, 2),
                "true_prob": round(true_prob, 4),
                "kelly_quarter": round(kelly.get("fractional_kelly", 0), 4),
                "kelly_drawdown": round(kelly.get("drawdown_kelly", 0), 4),
                "kelly_recommended": round(kelly.get("recommended", 0), 4),
                "analysis": {
                    "sharp_consensus": round(market_prob, 4),
                    "model_prob": round(model_prob, 4) if model_prob else None,
                    "model_source": model_source,
                    "model_rank": model_pred.get("confidence") if model_pred else None,
                    "base_blend": round(base_blend, 4),
                    "line_signal": round(line_signal, 4),
                    "calibration_shrink": round(calibration_shrink, 4),
                    "final_true_prob": round(true_prob, 4),
                    "implied_prob": round(implied_prob, 4),
                    "probability_edge": round(prob_edge, 4),
                    "market_weight": MARKET_WEIGHT,
                    "model_weight": MODEL_WEIGHT,
                    "line_weight": LINE_WEIGHT,
                },
                "stale_warning": best_book in stale_books,
            })

    # One best pick per game
    best_by_game = {}
    for b in bets:
        key = f"{b['away_team']}@{b['home_team']}"
        if key not in best_by_game or b["ev_percent"] > best_by_game[key]["ev_percent"]:
            best_by_game[key] = b

    result["picks"] = sorted(best_by_game.values(), key=lambda x: x["ev_percent"], reverse=True)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="EV Scanner (JSON output)")
    parser.add_argument("--date", type=str, default=None, help="Scan date (YYYY-MM-DD)")
    parser.add_argument("--sports", type=str, nargs="+", default=None, help="Sports to scan")
    args = parser.parse_args()

    output = scan_ev_bets(scan_date=args.date, sports_filter=args.sports)
    json.dump(output, sys.stdout, indent=2)
    sys.stdout.write("\n")
