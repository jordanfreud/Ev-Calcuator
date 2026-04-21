from zoneinfo import ZoneInfo

CANDIDATE_BOOKS = {"caesars", "draftkings", "fanduel", "betonlineag"}

# Use non-candidate books for fair probability when available.
MIN_REFERENCE_BOOKS = 2
MIN_TOTAL_BOOKS_PER_GAME = 3

EV_FLOOR = -0.01  # Show down to -1.0% EV
MAX_LOOKAHEAD_HOURS = 72

# Hybrid blend tuning
MARKET_WEIGHT = 0.60
MODEL_WEIGHT = 0.30
LINE_WEIGHT = 0.10

# Probability calibration: pull extreme probabilities toward 0.5 for stability.
# 0.0 means no calibration. Typical range: 0.03 - 0.08
CALIBRATION_SHRINK = 0.05

# Risk controls
MIN_PROBABILITY_EDGE = None  # Default disabled; use CLI or prod profile to enforce
EXTREME_PLUS_MONEY = 600  # Odds above this require stronger confidence
MAX_MODEL_RANK_FOR_EXTREME = 5
MIN_MODEL_COVERAGE = 0.50  # Alert if matched MLB model coverage drops below 50%
MIN_MODEL_ROWS_FOR_DATE = 1  # Minimum model rows required for strict production mode

# Optional strict MLB filter
REQUIRE_MODEL_FOR_MLB = False
MAX_MODEL_RANK = None  # e.g. 8 to allow only rank <= 8, None disables

REPORT_TIMEZONE = ZoneInfo("America/Chicago")

LOG_PATH = "bet_log.jsonl"
LINE_HISTORY_PATH = "line_history.json"

# Placeholder for optional manual import of historical console output.
PASTED_OUTPUT_PATH = "pasted_outputs.txt"

# One-flag production profile defaults
PROD_MIN_EDGE = 0.015  # 1.5 percentage points
PROD_REQUIRE_MODEL_MLB = True
PROD_MAX_MODEL_RANK = 8
