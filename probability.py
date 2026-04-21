
import numpy as np


def _clamp01(value):
    return max(0.0, min(1.0, value))

def american_to_prob(odds):
    if odds > 0:
        return 100 / (odds + 100)
    else:
        return -odds / (-odds + 100)

def remove_vig(prob1, prob2):
    total = prob1 + prob2
    if total == 0:
        return 0.5, 0.5
    return prob1 / total, prob2 / total

def calculate_vig(prob1, prob2):
    return (prob1 + prob2) - 1

def sharp_probability(prob_pairs, odds_list):
    """
    prob_pairs: [(p1, p2), (p1, p2), ...] AFTER vig removal
    odds_list: [(odds1, odds2), ...]
    """
    if len(prob_pairs) < 2:
        return None, None

    # --- Layer 1: Median ---
    probs1 = [p1 for p1, _ in prob_pairs]
    probs2 = [p2 for _, p2 in prob_pairs]

    median1 = np.median(probs1)
    median2 = np.median(probs2)

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
        weighted_probs1.append(p1)
        weighted_probs2.append(p2)

    if not weights:
        return median1, median2

    weighted1 = np.average(weighted_probs1, weights=weights)
    weighted2 = np.average(weighted_probs2, weights=weights)

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


def hybrid_probability(market_prob_pair, model_prob_pair=None, line_signal=0.0):
    """
    Blend market probability with model prediction and line movement signal.
    
    The hybrid approach combines three sources:
    - 60% Market probability (consensus from sharp books)
    - 30% Model probability (external model like friend's discord picks)
    - 10% Line movement bonus (confidence from sharp money movement)
    
    Args:
        market_prob_pair: (prob_away, prob_home) from sharp_probability()
        model_prob_pair: (prob_away, prob_home) or None if not available
        line_signal: Confidence boost from line movement (0.0 to 0.05)
    
    Returns:
        (final_prob_away, final_prob_home) normalized to sum to 1.0
    """
    market_away, market_home = market_prob_pair
    
    # If no model available, just use market
    if model_prob_pair is None:
        return market_away, market_home
    
    model_away, model_home = model_prob_pair
    
    # Base blend: 60% market + 30% model
    blend_away = (0.6 * market_away) + (0.3 * model_away)
    blend_home = (0.6 * market_home) + (0.3 * model_home)
    
    # Normalize blend
    total = blend_away + blend_home
    if total > 0:
        blend_away /= total
        blend_home /= total
    
    # Apply line signal as confidence boost
    # If line moved in agreement with model, boost that side
    if line_signal > 0:
        # Boost the stronger side by up to 10% of the signal
        line_boost = 0.1 * line_signal
        if blend_away > blend_home:
            blend_away = min(1.0, blend_away + line_boost)
            blend_home = 1.0 - blend_away
        else:
            blend_home = min(1.0, blend_home + line_boost)
            blend_away = 1.0 - blend_home
    
    # Final normalization
    total = blend_away + blend_home
    if total > 0:
        blend_away /= total
        blend_home /= total
    
    return blend_away, blend_home


def calibrated_hybrid_probability(
    market_prob_pair,
    model_prob_pair=None,
    line_signal=0.0,
    market_weight=0.60,
    model_weight=0.30,
    line_weight=0.10,
    calibration_shrink=0.05,
):
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