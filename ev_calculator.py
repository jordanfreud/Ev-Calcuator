def american_to_decimal(odds: float) -> float:
    if odds > 0:
        return (odds / 100) + 1
    else:
        return (100 / abs(odds)) + 1


def calculate_ev(true_prob: float, odds: float) -> float:
    decimal_odds = american_to_decimal(odds)
    return (true_prob * decimal_odds) - 1
