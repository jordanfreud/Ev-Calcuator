import argparse
from datetime import datetime, timezone

from bet_tracker import (
    append_new_picks,
    format_diagnostics_report,
    grade_pending_picks,
    performance_diagnostics,
    performance_report,
)
from config import (
    CALIBRATION_SHRINK,
    CANDIDATE_BOOKS,
    EXTREME_PLUS_MONEY,
    EV_FLOOR,
    LINE_WEIGHT,
    MARKET_WEIGHT,
    MAX_LOOKAHEAD_HOURS,
    MAX_MODEL_RANK,
    MAX_MODEL_RANK_FOR_EXTREME,
    MIN_MODEL_COVERAGE,
    MIN_MODEL_ROWS_FOR_DATE,
    MIN_PROBABILITY_EDGE,
    MIN_REFERENCE_BOOKS,
    MIN_TOTAL_BOOKS_PER_GAME,
    MODEL_WEIGHT,
    PROD_MAX_MODEL_RANK,
    PROD_MIN_EDGE,
    PROD_REQUIRE_MODEL_MLB,
    REPORT_TIMEZONE,
    REQUIRE_MODEL_FOR_MLB,
)
from odds_api import get_odds
from probability import american_to_prob, remove_vig, sharp_probability, calibrated_hybrid_probability
from ev_calculator import calculate_ev
from model_input import get_model_prediction, model_predictions_count, normalize_team_code
from line_movement import record_line_snapshot, get_market_line_signal


def _normalize_book_name(title):
    normalized = "".join(ch for ch in (title or "").lower() if ch.isalnum())
    aliases = {
        "betonline": "betonlineag",
        "caesarssportsbook": "caesars",
        "williamhillus": "caesars",
    }
    return aliases.get(normalized, normalized)


def _parse_commence_time(value):
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _is_real_matchup(game):
    if not game.get("id"):
        return False

    commence_time = _parse_commence_time(game.get("commence_time"))
    if not commence_time:
        return False

    now = datetime.now(timezone.utc)
    hours_to_start = (commence_time - now).total_seconds() / 3600.0
    if hours_to_start > MAX_LOOKAHEAD_HOURS:
        return False

    bookmakers = game.get("bookmakers") or []
    if len(bookmakers) < MIN_TOTAL_BOOKS_PER_GAME:
        return False

    return True


def _on_scan_date(game, scan_date: str):
    commence_time = _parse_commence_time(game.get("commence_time"))
    if not commence_time:
        return False
    local_date = commence_time.astimezone(REPORT_TIMEZONE).date().isoformat()
    return local_date == scan_date


def _local_game_date(game):
    commence_time = _parse_commence_time(game.get("commence_time"))
    if not commence_time:
        return None
    return commence_time.astimezone(REPORT_TIMEZONE).date().isoformat()


def _extract_home_away_prices(outcomes, home_team, away_team):
    if len(outcomes) != 2:
        return None

    prices = {row.get("name"): row.get("price") for row in outcomes}
    if home_team not in prices or away_team not in prices:
        return None

    return prices[home_team], prices[away_team]


def _format_book_lines(book_lines, home_team, away_team):
    if not book_lines:
        return "n/a"

    parts = []
    for book_title in sorted(book_lines):
        odds_home, odds_away = book_lines[book_title]
        home_str = f"+{odds_home}" if odds_home > 0 else f"{odds_home}"
        away_str = f"+{odds_away}" if odds_away > 0 else f"{odds_away}"
        parts.append(f"{book_title}: {home_team} {home_str} | {away_team} {away_str}")
    return " ; ".join(parts)


def _get_team_line_for_book(book_title, odds_home, odds_away, home_team, target_team):
    return odds_home if target_team == home_team else odds_away


def _select_best_and_dk_line(candidate_lines, home_team, target_team):
    best_book = None
    best_odds = None
    dk_odds = None

    for book_title, odds_home, odds_away in candidate_lines:
        team_odds = _get_team_line_for_book(book_title, odds_home, odds_away, home_team, target_team)

        if best_odds is None or team_odds > best_odds:
            best_odds = team_odds
            best_book = book_title

        if _normalize_book_name(book_title) == "draftkings":
            dk_odds = team_odds

    return best_book, best_odds, dk_odds


def _pick_best_per_game(bets):
    best_by_event = {}
    for bet in bets:
        event_id = bet.get("event_id")
        if event_id not in best_by_event or bet["ev"] > best_by_event[event_id]["ev"]:
            best_by_event[event_id] = bet
    return list(best_by_event.values())


def _sport_priority(sport_key):
    priority = {
        "baseball_mlb": 0,
        "basketball_nba": 1,
    }
    return priority.get(sport_key, 99)


def find_ev_bets(
    scan_date=None,
    explain=False,
    positive_only=False,
    one_per_game=True,
    min_edge=MIN_PROBABILITY_EDGE,
    require_model_mlb=REQUIRE_MODEL_FOR_MLB,
    max_model_rank=MAX_MODEL_RANK,
    show_rejections=False,
    diagnostics=False,
    enforce_model_rows=False,
    min_model_rows=MIN_MODEL_ROWS_FOR_DATE,
):
    if scan_date is None:
        scan_date = datetime.now(REPORT_TIMEZONE).date().isoformat()

    ev_threshold = 0.0001 if positive_only else EV_FLOOR

    data = get_odds()

    if not data:
        print("No data returned")
        return

    qualifying_games = [g for g in data if _is_real_matchup(g)]
    available_dates = sorted({d for d in (_local_game_date(g) for g in qualifying_games) if d})

    auto_fallback_scan_date = False
    games_for_scan_date = [g for g in qualifying_games if _on_scan_date(g, scan_date)]
    if not games_for_scan_date and available_dates:
        # If the requested date has no qualifying games (common for late-night runs),
        # automatically scan the nearest available date in-feed.
        nearest_dates = [d for d in available_dates if d >= scan_date]
        fallback_date = nearest_dates[0] if nearest_dates else available_dates[-1]
        if fallback_date != scan_date:
            print(
                f"No qualifying games found for requested date {scan_date}. "
                f"Using nearest available date {fallback_date}."
            )
            scan_date = fallback_date
            auto_fallback_scan_date = True
            games_for_scan_date = [g for g in qualifying_games if _on_scan_date(g, scan_date)]

    if not games_for_scan_date:
        print(f"Scan Date ({REPORT_TIMEZONE.key}): {scan_date}")
        print("No qualifying games available from odds feed for this date window.")
        return

    bets = []
    rejections = []
    scan_stats = {
        "games_from_feed": len(data),
        "games_qualifying_window": len(qualifying_games),
        "games_on_scan_date": len(games_for_scan_date),
        "games_with_candidate_books": 0,
    }
    model_stats = {
        "mlb_games_seen": 0,
        "mlb_model_matches": 0,
        "mlb_model_misses": 0,
        "mlb_missing_matchups": [],
    }

    model_rows_for_date = model_predictions_count(scan_date)

    if enforce_model_rows and model_rows_for_date < min_model_rows:
        if auto_fallback_scan_date:
            print(
                f"Model rows for fallback scan date {scan_date}: {model_rows_for_date}. "
                "Continuing in market-only mode for this run."
            )
            require_model_mlb = False
        else:
            print(f"Scan Date ({REPORT_TIMEZONE.key}): {scan_date}")
            print(
                f"ABORTED: strict run requires at least {min_model_rows} model rows for date, "
                f"found {model_rows_for_date}."
            )
            print(
                "Action: load today model picks first, then rerun production profile."
            )
            return

    for game in games_for_scan_date:

        event_id = game.get("id")
        commence_time = game.get("commence_time")
        home_team = game.get("home_team")
        away_team = game.get("away_team")
        sport = game.get("sport_key", "unknown")

        reference_prob_pairs = []
        reference_odds_list = []
        candidate_lines = []

        for bookmaker in game.get("bookmakers", []):
            markets = bookmaker.get("markets")
            if not markets:
                continue

            market = markets[0]
            outcomes = market.get("outcomes", [])
            prices = _extract_home_away_prices(outcomes, home_team, away_team)
            if not prices:
                continue

            odds_home, odds_away = prices
            prob_home = american_to_prob(odds_home)
            prob_away = american_to_prob(odds_away)
            nv_prob_home, nv_prob_away = remove_vig(prob_home, prob_away)

            normalized = _normalize_book_name(bookmaker.get("title"))
            if normalized in CANDIDATE_BOOKS:
                title = bookmaker.get("title")
                candidate_lines.append((title, odds_home, odds_away))
            else:
                reference_prob_pairs.append((nv_prob_home, nv_prob_away))
                reference_odds_list.append((odds_home, odds_away))

        if not candidate_lines:
            continue

        scan_stats["games_with_candidate_books"] += 1

        if len(reference_prob_pairs) < MIN_REFERENCE_BOOKS:
            # fallback: use candidate books as reference if reference depth is thin
            for _, odds_home, odds_away in candidate_lines:
                prob_home = american_to_prob(odds_home)
                prob_away = american_to_prob(odds_away)
                nv_prob_home, nv_prob_away = remove_vig(prob_home, prob_away)
                reference_prob_pairs.append((nv_prob_home, nv_prob_away))
                reference_odds_list.append((odds_home, odds_away))

        if len(reference_prob_pairs) < 2:
            continue

        sharp_probs = sharp_probability(reference_prob_pairs, reference_odds_list)
        if not sharp_probs:
            continue

        market_prob_home, market_prob_away = sharp_probs
        true_prob_home, true_prob_away = market_prob_home, market_prob_away
        base_blend_prob_away, base_blend_prob_home = market_prob_away, market_prob_home
        line_signal = 0.0
        
        # === HYBRID: TRY TO GET MODEL PREDICTION ===
        if sport == "baseball_mlb":
            model_stats["mlb_games_seen"] += 1

        model_pred = get_model_prediction(away_team, home_team, date_str=scan_date)
        model_prob_pair = None
        model_source = "market_only"

        # Record snapshots every run so movement works even without model match.
        for book_title, odds_home, odds_away in candidate_lines:
            record_line_snapshot(event_id, book_title, odds_away, odds_home)

        # Compute consensus movement across candidate books.
        line_signal = get_market_line_signal(event_id, candidate_lines)
        
        if model_pred:
            if sport == "baseball_mlb":
                model_stats["mlb_model_matches"] += 1
            model_prob_pair = (model_pred["away_win_prob"], model_pred["home_win_prob"])
            model_source = f"model (rank {model_pred.get('confidence', '?')})"
            
            (true_prob_away, true_prob_home), blend_components = calibrated_hybrid_probability(
                market_prob_pair=(market_prob_away, market_prob_home),
                model_prob_pair=model_prob_pair,
                line_signal=line_signal,
                market_weight=MARKET_WEIGHT,
                model_weight=MODEL_WEIGHT,
                line_weight=LINE_WEIGHT,
                calibration_shrink=CALIBRATION_SHRINK,
            )
            base_blend_prob_away = blend_components["base_blend_away"]
            base_blend_prob_home = blend_components["base_blend_home"]
        elif sport == "baseball_mlb":
            model_stats["mlb_model_misses"] += 1
            model_stats["mlb_missing_matchups"].append(
                f"{normalize_team_code(away_team)} @ {normalize_team_code(home_team)}"
            )

        if not model_pred:
            (true_prob_away, true_prob_home), blend_components = calibrated_hybrid_probability(
                market_prob_pair=(market_prob_away, market_prob_home),
                model_prob_pair=None,
                line_signal=line_signal,
                market_weight=MARKET_WEIGHT,
                model_weight=MODEL_WEIGHT,
                line_weight=LINE_WEIGHT,
                calibration_shrink=CALIBRATION_SHRINK,
            )
            base_blend_prob_away = blend_components["base_blend_away"]
            base_blend_prob_home = blend_components["base_blend_home"]

        if sport == "baseball_mlb" and require_model_mlb and not model_pred:
            rejections.append({
                "game": f"{away_team} vs {home_team}",
                "sport": sport,
                "reason": "model_required_for_mlb",
            })
            continue

        if model_pred and max_model_rank is not None and model_pred.get("confidence") is not None:
            if int(model_pred["confidence"]) > int(max_model_rank):
                rejections.append({
                    "game": f"{away_team} vs {home_team}",
                    "sport": sport,
                    "reason": f"model_rank_above_limit({model_pred['confidence']} > {max_model_rank})",
                })
                continue
        # ===================================
        
        home_best_book, home_best_odds, home_dk_odds = _select_best_and_dk_line(
            candidate_lines, home_team, home_team
        )
        away_best_book, away_best_odds, away_dk_odds = _select_best_and_dk_line(
            candidate_lines, home_team, away_team
        )

        if home_best_odds is not None:
            ev_home = calculate_ev(true_prob_home, home_best_odds)
            implied_home = american_to_prob(home_best_odds)
            prob_edge_home = true_prob_home - implied_home
            reject_reason = None
            if ev_home < ev_threshold:
                reject_reason = "ev_below_threshold"
            elif min_edge is not None and prob_edge_home < min_edge:
                reject_reason = f"prob_edge_below_min({prob_edge_home:.4f} < {min_edge:.4f})"
            elif home_best_odds >= EXTREME_PLUS_MONEY and (not model_pred or int(model_pred.get("confidence", 99)) > MAX_MODEL_RANK_FOR_EXTREME):
                reject_reason = "extreme_plus_money_without_strong_model"

            if reject_reason:
                rejections.append({
                    "game": f"{away_team} vs {home_team}",
                    "sport": sport,
                    "team": home_team,
                    "ev": ev_home,
                    "reason": reject_reason,
                })
            else:
                bets.append({
                    "event_id": event_id,
                    "commence_time": commence_time,
                    "ev": ev_home,
                    "team": home_team,
                    "odds": home_best_odds,
                    "book": home_best_book,
                    "game": f"{away_team} vs {home_team}",
                    "sport": sport,
                    "draftkings_odds": home_dk_odds,
                    "model_source": model_source,
                    "model_rank": model_pred.get("confidence") if model_pred else None,
                    "market_prob": market_prob_home,
                    "model_prob": model_pred.get("home_win_prob") if model_pred else None,
                    "base_blend_prob": base_blend_prob_home,
                    "line_signal": line_signal,
                    "final_prob": true_prob_home,
                    "implied_prob": implied_home,
                    "probability_edge": prob_edge_home,
                })

        if away_best_odds is not None:
            ev_away = calculate_ev(true_prob_away, away_best_odds)
            implied_away = american_to_prob(away_best_odds)
            prob_edge_away = true_prob_away - implied_away
            reject_reason = None
            if ev_away < ev_threshold:
                reject_reason = "ev_below_threshold"
            elif min_edge is not None and prob_edge_away < min_edge:
                reject_reason = f"prob_edge_below_min({prob_edge_away:.4f} < {min_edge:.4f})"
            elif away_best_odds >= EXTREME_PLUS_MONEY and (not model_pred or int(model_pred.get("confidence", 99)) > MAX_MODEL_RANK_FOR_EXTREME):
                reject_reason = "extreme_plus_money_without_strong_model"

            if reject_reason:
                rejections.append({
                    "game": f"{away_team} vs {home_team}",
                    "sport": sport,
                    "team": away_team,
                    "ev": ev_away,
                    "reason": reject_reason,
                })
            else:
                bets.append({
                    "event_id": event_id,
                    "commence_time": commence_time,
                    "ev": ev_away,
                    "team": away_team,
                    "odds": away_best_odds,
                    "book": away_best_book,
                    "game": f"{away_team} vs {home_team}",
                    "sport": sport,
                    "draftkings_odds": away_dk_odds,
                    "model_source": model_source,
                    "model_rank": model_pred.get("confidence") if model_pred else None,
                    "market_prob": market_prob_away,
                    "model_prob": model_pred.get("away_win_prob") if model_pred else None,
                    "base_blend_prob": base_blend_prob_away,
                    "line_signal": line_signal,
                    "final_prob": true_prob_away,
                    "implied_prob": implied_away,
                    "probability_edge": prob_edge_away,
                })

    if not bets:
        print(f"Scan Date ({REPORT_TIMEZONE.key}): {scan_date}")
        print("No bets found at or above EV floor.")
        print(f"Model rows available for {scan_date}: {model_rows_for_date}")
        print(
            "Feed stats: "
            f"games={scan_stats['games_from_feed']} | "
            f"qualifying_window={scan_stats['games_qualifying_window']} | "
            f"on_scan_date={scan_stats['games_on_scan_date']} | "
            f"with_candidate_books={scan_stats['games_with_candidate_books']}"
        )
        if show_rejections and rejections:
            print("")
            print("===== Top Rejections =====")
            for row in sorted(rejections, key=lambda x: x.get("ev", -999), reverse=True)[:10]:
                game = row.get("game")
                team = row.get("team")
                ev = row.get("ev")
                ev_str = "n/a" if ev is None else f"EV {ev * 100:.2f}%"
                print(f"{game} ({row.get('sport')}) | {team} | {ev_str} | {row.get('reason')}")
        return

    if one_per_game:
        bets = _pick_best_per_game(bets)

    # Sort by sport priority, then EV descending inside each sport.
    bets.sort(key=lambda x: (_sport_priority(x.get("sport")), -x["ev"]))

    avg_ev = sum(b["ev"] for b in bets) / len(bets)
    avg_edge = sum(float(b.get("probability_edge") or 0.0) for b in bets) / len(bets)

    print(f"\n===== All Bets (EV >= {ev_threshold * 100:.2f}%) =====\n")
    print(f"Scan Date ({REPORT_TIMEZONE.key}): {scan_date}")
    print(
        f"Run Summary: picks={len(bets)} | avg_ev={avg_ev * 100:.2f}% | "
        f"avg_probability_edge={avg_edge * 100:.2f}pp"
    )
    print("")

    if model_stats["mlb_games_seen"]:
        print("===== MLB Model Coverage =====")
        coverage = model_stats["mlb_model_matches"] / model_stats["mlb_games_seen"]
        print(f"Model rows available for {scan_date}: {model_rows_for_date}")
        print(
            f"Seen: {model_stats['mlb_games_seen']} | "
            f"Matched: {model_stats['mlb_model_matches']} | "
            f"Missed: {model_stats['mlb_model_misses']}"
        )
        if coverage < MIN_MODEL_COVERAGE:
            print(
                f"ALERT: Model coverage {coverage * 100:.1f}% below minimum "
                f"{MIN_MODEL_COVERAGE * 100:.1f}%"
            )
        if model_stats["mlb_missing_matchups"]:
            misses = ", ".join(model_stats["mlb_missing_matchups"][:8])
            print(f"Unmatched MLB examples: {misses}")
        print("")

    current_sport = None
    for bet in bets:
        if bet["sport"] != current_sport:
            current_sport = bet["sport"]
            print(f"===== {current_sport} =====")

        odds = bet["odds"]
        odds_str = f"+{odds}" if odds > 0 else f"{odds}"
        dk_odds = bet.get("draftkings_odds")
        dk_odds_str = "n/a" if dk_odds is None else (f"+{dk_odds}" if dk_odds > 0 else f"{dk_odds}")
        model_rank = bet.get("model_rank")
        model_badge = f" [Model Rank: {model_rank}]" if model_rank else ""

        print(f"{bet['game']} ({bet['sport']})")
        print(f"  Best Book: {bet['book']}")
        print(f"  Team: {bet['team']}")
        print(f"  Best Line: {odds_str}")
        print(f"  DraftKings Line: {dk_odds_str}")
        print(f"  EV: {round(bet['ev'] * 100, 2)}%{model_badge}\n")

        if explain:
            market_prob = bet.get("market_prob")
            model_prob = bet.get("model_prob")
            base_blend_prob = bet.get("base_blend_prob")
            final_prob = bet.get("final_prob")
            implied_prob = bet.get("implied_prob")
            line_signal_value = bet.get("line_signal", 0.0)

            edge = (final_prob - implied_prob) if final_prob is not None and implied_prob is not None else None
            line_impact = (final_prob - base_blend_prob) if final_prob is not None and base_blend_prob is not None else 0.0

            print("  Reasoning:")
            print(f"    Market Prob: {market_prob * 100:.2f}%")
            if model_prob is not None:
                print(f"    Model Prob: {model_prob * 100:.2f}%")
                print("    Weights: market 60%, model 30%, line boost up to 10% of signal")
            else:
                print("    Model Prob: n/a (market-only fallback)")
            print(f"    Base Blend (no line): {base_blend_prob * 100:.2f}%")
            print(f"    Line Signal: {line_signal_value:.4f} | Line Impact: {line_impact * 100:.2f}pp")
            print(f"    Final True Prob: {final_prob * 100:.2f}%")
            print(f"    Implied Prob @ Best Line: {implied_prob * 100:.2f}%")
            print(f"    Probability Edge: {edge * 100:.2f}pp")
            min_edge_str = "disabled" if min_edge is None else f"{min_edge * 100:.2f}pp"
            print(f"    Filter Gate: min_edge={min_edge_str}, passed=yes")
            print("")

    if show_rejections and rejections:
        print("===== Top Rejections =====")
        for row in sorted(rejections, key=lambda x: x.get("ev", -999), reverse=True)[:10]:
            team = row.get("team", "n/a")
            ev_val = row.get("ev")
            ev_str = "n/a" if ev_val is None else f"{ev_val * 100:.2f}%"
            print(f"{row.get('game')} ({row.get('sport')}) | {team} | EV {ev_str} | {row.get('reason')}")
        print("")

    inserted = append_new_picks(bets)
    graded = grade_pending_picks()
    report = performance_report()

    print(f"Logged new picks: {inserted}")
    print(f"Newly graded picks: {graded}\n")

    print("===== Performance: All-Time =====")
    print(report["all_time"])
    print("\n===== Performance: Current Week (Mon-Sun, America/Chicago) =====")
    print(report["weekly"])
    print("\n===== Performance: Yesterday (America/Chicago) =====")
    print(report["yesterday"])

    if diagnostics:
        print("\n===== Diagnostics =====")
        diag = performance_diagnostics()
        print(format_diagnostics_report(diag))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run EV betting scan")
    parser.add_argument(
        "--date",
        default=datetime.now(REPORT_TIMEZONE).date().isoformat(),
        help="Scan date in YYYY-MM-DD (report timezone)",
    )
    parser.add_argument("--explain", action="store_true", help="Show detailed probability reasoning")
    parser.add_argument(
        "--positive-only",
        action="store_true",
        help="Only show picks with EV > 0.00%%",
    )
    parser.add_argument(
        "--all-sides",
        action="store_true",
        help="Allow both sides of the same game (disables one-pick-per-game filter)",
    )
    parser.add_argument(
        "--min-edge",
        type=float,
        default=MIN_PROBABILITY_EDGE,
        help="Minimum probability edge required (decimal, e.g. 0.01 = 1 percentage point)",
    )
    parser.add_argument(
        "--require-model-mlb",
        action="store_true",
        help="Require model match for MLB picks",
    )
    parser.add_argument(
        "--max-model-rank",
        type=int,
        default=MAX_MODEL_RANK,
        help="Maximum allowed model rank (lower is better). Omit to disable.",
    )
    parser.add_argument(
        "--show-rejections",
        action="store_true",
        help="Show top candidates rejected by filters",
    )
    parser.add_argument(
        "--diagnostics",
        action="store_true",
        help="Show Brier/log-loss/ROI cohort diagnostics",
    )
    parser.add_argument(
        "--prod-profile",
        action="store_true",
        help="Apply production defaults for predictability and durable edge",
    )
    parser.add_argument(
        "--min-model-rows",
        type=int,
        default=MIN_MODEL_ROWS_FOR_DATE,
        help="Minimum same-day model rows required when strict model coverage enforcement is enabled",
    )
    args = parser.parse_args()

    if args.prod_profile:
        args.positive_only = True
        args.all_sides = False
        args.min_edge = PROD_MIN_EDGE
        args.require_model_mlb = PROD_REQUIRE_MODEL_MLB
        args.max_model_rank = PROD_MAX_MODEL_RANK

    find_ev_bets(
        scan_date=args.date,
        explain=args.explain,
        positive_only=args.positive_only,
        one_per_game=(not args.all_sides),
        min_edge=args.min_edge,
        require_model_mlb=args.require_model_mlb,
        max_model_rank=args.max_model_rank,
        show_rejections=args.show_rejections,
        diagnostics=args.diagnostics,
        enforce_model_rows=args.prod_profile,
        min_model_rows=args.min_model_rows,
    )