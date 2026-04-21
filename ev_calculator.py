from typing import Dict, Optional

from probability import american_to_decimal, kelly_criterion


def calculate_ev(true_prob: float, odds: float) -> float:
    """Expected value as a fraction (e.g., 0.05 = 5% EV)."""
    decimal_odds = american_to_decimal(odds)
    return (true_prob * decimal_odds) - 1


def calculate_kelly(
    true_prob: float,
    odds: float,
    fraction: float = 0.25,
    max_bet: float = 0.05,
    max_drawdown: Optional[float] = None,
) -> Dict[str, float]:
    """
    Recommended bet sizing using keeks library Kelly variants.

    Returns dict with:
      - fractional_kelly: Quarter-Kelly sizing
      - drawdown_kelly: Drawdown-adjusted sizing
      - recommended: The more conservative of the two
    """
    return kelly_criterion(true_prob, odds, fraction, max_bet, max_drawdown)
