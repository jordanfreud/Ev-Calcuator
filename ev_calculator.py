def american_to_decimal(odds):
    if odds > 0:
        return (odds / 100) + 1
    else:
        return (100 / abs(odds)) + 1


def calculate_ev(true_prob, odds):
    decimal_odds = american_to_decimal(odds)
    return (true_prob * decimal_odds) - 1