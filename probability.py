import statistics
from typing import List, Tuple, Dict, Optional


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def american_to_prob(odds: float) -> float:
    if odds > 0:
        return 100 / (odds + 100)
    else:
        return -odds / (-odds + 100)


def american_to_decimal(odds: float) -> float:
    if odds > 0:
        return (odds / 100) + 1
    else:
        return (100 / abs(odds)) + 1


def remove_vig(prob1: float, prob2: float) -> Tuple[float, float]:
    total = prob1 + prob2
    if total == 0:
        return 0.5, 0.5
    return prob1 / total, prob2 / total


def calculate_vig(prob1: float, prob2: float) -> float:
    return (prob1 + prob2) - 1


def kelly_criterion(true_prob: float, odds: float, fraction: float = 0.25, max_bet: float = 0.05) -> float:
    """
    Fractional Kelly criterion for optimal bet sizing.

    Args:
        true_prob: Your estimated true win probability.
        odds: American odds for the bet.
        fraction: Kelly fraction (0.25 = quarter Kelly, conservative).
        max_bet: Maximum fraction of bankroll to risk.

    Returns:
        Recommended bet size as fraction of bankroll (0.0 if no edge).
    """
    decimal_odds = american_to_decimal(odds)
    b = decimal_odds - 1  # net profit per unit wagered
    q = 1 - true_prob

    if b <= 0:
        return 0.0

    # Full Kelly: (bp - q) / b
    full_kelly = (b * true_prob - q) / b

    if full_kelly <= 0:
        return 0.0

    sized = full_kelly * fraction
    return min(sized, max_bet)


def sharp_probability(
    prob_pairs: List[Tuple[float, float]],
    odds_list: List[Tuple[float, float]],
    sharp_weights: Optional[List[float]] = None,
) -> Optional[Tuple[float, float]]:
    """
    Construct consensus "true" probability from multiple books.

    Uses a 3-layer blend:
      1. Median (outlier-resistant baseline)
      2. Sharp-weighted average (books with lower vig AND higher sharpness get more say)
      3. Best-price signal (the best available odds imply the floor probability)

    Args:
        prob_pairs: [(p_home, p_away), ...] AFTER vig removal per book.
        odds_list: [(odds_home, odds_away), ...] raw American odds per book.
        sharp_weights: Optional per-book sharpness multiplier (e.g., Pinnacle=3.0).
    """
    if len(prob_pairs) < 2:
        return None

    if sharp_weights is None:
        sharp_weights = [1.0] * len(prob_pairs)

    # --- Layer 1: Median ---
    probs1 = [p1 for p1, _ in prob_pairs]
    probs2 = [p2 for _, p2 in prob_pairs]

    median1 = statistics.median(probs1)
    median2 = statistics.median(probs2)

    # --- Layer 2: Sharp-weighted + low-vig weighted ---
    weights = []
    weighted_probs1 = []
    weighted_probs2 = []

    for i, ((p1, p2), (odds1, odds2)) in enumerate(zip(prob_pairs, odds_list)):
        raw_p1 = american_to_prob(odds1)
        raw_p2 = american_to_prob(odds2)
        vig = calculate_vig(raw_p1, raw_p2)
        if vig <= 0:
            continue
        # Combined weight: inverse vig * sharpness multiplier
        weight = (1 / vig) * sharp_weights[i]
        weights.append(weight)
        weighted_probs1.append(p1 * weight)
        weighted_probs2.append(p2 * weight)

    if not weights:
        return median1, median2

    total_weight = sum(weights)
    weighted1 = sum(weighted_probs1) / total_weight
    weighted2 = sum(weighted_probs2) / total_weight

    # --- Layer 3: Best price signal ---
    best_odds1 = max(o[0] for o in odds_list)
    best_odds2 = max(o[1] for o in odds_list)

    best_prob1 = american_to_prob(best_odds1)
    best_prob2 = american_to_prob(best_odds2)

    # --- Final blend ---
    sharp1 = (0.5 * weighted1) + (0.3 * median1) + (0.2 * best_prob1)
    sharp2 = (0.5 * weighted2) + (0.3 * median2) + (0.2 * best_prob2)

    return remove_vig(sharp1, sharp2)


def calibrated_hybrid_probability(
    market_prob_pair: Tuple[float, float],
    model_prob_pair: Optional[Tuple[float, float]] = None,
    line_signal: float = 0.0,
    market_weight: float = 0.60,
    model_weight: float = 0.30,
    line_weight: float = 0.10,
    calibration_shrink: float = 0.03,
) -> Tuple[Tuple[float, float], Dict[str, float]]:
    """
    Calibrated blend for production use with directional line signal.

    The line_signal is now SIGNED:
      - Positive: market moved toward away team (away got stronger)
      - Negative: market moved toward home team (home got stronger)
      - Zero: no meaningful movement

    The boost is applied in the DIRECTION of movement, not blindly toward
    the stronger side of the blend. This prevents boosting the wrong side
    when the market disagrees with your model.

    Returns:
        final_probs: (away, home)
        components: dict with base and line impact for explainability
    """
    market_away, market_home = market_prob_pair

    if model_prob_pair is None:
        base_away, base_home = market_away, market_home
    else:
        model_away, model_home = model_prob_pair
        base_away = (market_weight * market_away) + (model_weight * model_away)
        base_home = (market_weight * market_home) + (model_weight * model_home)
        total = base_away + base_home
        if total > 0:
            base_away, base_home = base_away / total, base_home / total

    # Directional line movement boost.
    # Positive signal = away strengthened, negative = home strengthened.
    boost = line_weight * _clamp01(abs(line_signal))
    final_away, final_home = base_away, base_home

    if boost > 0 and line_signal != 0.0:
        if line_signal > 0:
            # Market moved toward away — boost away
            final_away = _clamp01(final_away + boost)
            final_home = 1.0 - final_away
        else:
            # Market moved toward home — boost home
            final_home = _clamp01(final_home + boost)
            final_away = 1.0 - final_home

    # Calibration shrink toward 0.5 for stability.
    # A well-calibrated bettor should set this to 0.
    s = _clamp01(calibration_shrink)
    if s > 0:
        final_away = ((1.0 - s) * final_away) + (s * 0.5)
        final_home = 1.0 - final_away

    return (final_away, final_home), {
        "base_blend_away": base_away,
        "base_blend_home": base_home,
        "line_boost": boost,
        "line_direction": "away" if line_signal > 0 else ("home" if line_signal < 0 else "none"),
        "calibration_shrink": s,
    }
