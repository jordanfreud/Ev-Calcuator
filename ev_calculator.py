from probability import american_to_decimal, kelly_criterion


def calculate_ev(true_prob: float, odds: float) -> float:
    """Expected value as a fraction (e.g., 0.05 = 5% EV)."""
    decimal_odds = american_to_decimal(odds)
    return (true_prob * decimal_odds) - 1


def calculate_kelly(true_prob: float, odds: float, fraction: float = 0.25, max_bet: float = 0.05) -> float:
    """Recommended bet size as fraction of bankroll."""
    return kelly_criterion(true_prob, odds, fraction, max_bet)
