import statistics
from typing import List, Tuple, Dict, Optional, Any

def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))

def american_to_prob(odds: float) -> float:
    if odds > 0:
        return 100 / (odds + 100)
    else:
        return -odds / (-odds + 100)

def remove_vig(prob1: float, prob2: float) -> Tuple[float, float]:
    total = prob1 + prob2
    if total == 0:
        return 0.5, 0.5
    return prob1 / total, prob2 / total

def calculate_vig(prob1: float, prob2: float) -> float:
    return (prob1 + prob2) - 1

def sharp_probability(prob_pairs: List[Tuple[float, float]], odds_list: List[Tuple[float, float]]) -> Optional[Tuple[float, float]]:
    """
    prob_pairs: [(p1, p2), (p1, p2), ...] AFTER vig removal
    odds_list: [(odds1, odds2), ...]
    """
    if len(prob_pairs) < 2:
        return None

    # --- Layer 1: Median ---
    probs1 = [p1 for p1, _ in prob_pairs]
    probs2 = [p2 for _, p2 in prob_pairs]

    median1 = statistics.median(probs1)
    median2 = statistics.median(probs2)

    # --- Layer 2: Low-vig weighted ---
    weights = []
    weighted_probs1 = []
    weighted_probs2 = []

    for (p1, p2), (odds1, odds2) in zip(prob_pairs, odds_list):
        raw_p1 = american_to_prob(odds1)
        raw_p2 = american_to_prob(odds2)
        vig = calculate_vig(raw_p1, raw_p2)
        if vig <= 0:
            continue
        weight = 1 / vig
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

    # normalize again just to be safe
    return remove_vig(sharp1, sharp2)

def calibrated_hybrid_probability(
    market_prob_pair: Tuple[float, float],
    model_prob_pair: Optional[Tuple[float, float]] = None,
    line_signal: float = 0.0,
    market_weight: float = 0.60,
    model_weight: float = 0.30,
    line_weight: float = 0.10,
    calibration_shrink: float = 0.05,
) -> Tuple[Tuple[float, float], Dict[str, float]]:
    """
    Calibrated blend for production use.

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

    # Line movement nudges toward stronger side of base blend.
    boost = line_weight * _clamp01(line_signal)
    final_away, final_home = base_away, base_home
    if boost > 0:
        if final_away >= final_home:
            final_away = _clamp01(final_away + boost)
            final_home = 1.0 - final_away
        else:
            final_home = _clamp01(final_home + boost)
            final_away = 1.0 - final_home

    # Calibration shrink toward 0.5 for predictability.
    s = _clamp01(calibration_shrink)
    final_away = ((1.0 - s) * final_away) + (s * 0.5)
    final_home = 1.0 - final_away

    return (final_away, final_home), {
        "base_blend_away": base_away,
        "base_blend_home": base_home,
        "line_boost": boost,
        "calibration_shrink": s,
    }
