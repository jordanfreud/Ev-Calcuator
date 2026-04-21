from zoneinfo import ZoneInfo

# ─── Books ────────────────────────────────────────────────────────────────────
# Candidate books: these are the books you actually bet on.
CANDIDATE_BOOKS = {"caesars", "draftkings", "fanduel", "betonlineag"}

# Sharp book weights for reference probability construction.
# Higher weight = more influence on "true" probability. Pinnacle is the gold standard.
SHARP_BOOK_WEIGHTS = {
    "pinnacle": 3.0,
    "circa": 2.5,
    "betcris": 2.0,
    "bookmaker": 2.0,
    "bovada": 1.5,
    "betrivers": 1.0,
    "unibet": 1.0,
    "pointsbet": 0.8,
    "betmgm": 0.8,
    "wynnbet": 0.8,
    "superbook": 1.5,
}
DEFAULT_SHARP_WEIGHT = 1.0

# Use non-candidate books for fair probability when available.
MIN_REFERENCE_BOOKS = 2
MIN_TOTAL_BOOKS_PER_GAME = 3

# ─── EV Thresholds ───────────────────────────────────────────────────────────
EV_FLOOR = -0.01  # Show down to -1.0% EV
MAX_LOOKAHEAD_HOURS = 72

# ─── Hybrid Blend Tuning ─────────────────────────────────────────────────────
MARKET_WEIGHT = 0.60
MODEL_WEIGHT = 0.30
LINE_WEIGHT = 0.10

# ─── Calibration ─────────────────────────────────────────────────────────────
# Static fallback shrink. Used only when insufficient graded history exists.
# Set to 0.0 to disable shrink entirely (recommended once you have 100+ graded picks).
CALIBRATION_SHRINK = 0.03

# Dynamic calibration: if you have N+ graded picks, compute shrink from Brier score.
# Well-calibrated models (Brier < 0.22) get shrink = 0.
DYNAMIC_CALIBRATION_ENABLED = True
DYNAMIC_CALIBRATION_MIN_PICKS = 50

# ─── Risk Controls ───────────────────────────────────────────────────────────
MIN_PROBABILITY_EDGE = None  # Default disabled; use CLI or prod profile to enforce
EXTREME_PLUS_MONEY = 600  # Odds above this require stronger confidence
MAX_MODEL_RANK_FOR_EXTREME = 5
MIN_MODEL_COVERAGE = 0.50  # Alert if matched MLB model coverage drops below 50%
MIN_MODEL_ROWS_FOR_DATE = 1  # Minimum model rows required for strict production mode

# ─── Stale Line Detection ────────────────────────────────────────────────────
# Flag picks where the line hasn't updated in this many hours.
STALE_LINE_THRESHOLD_HOURS = 2.0

# ─── Kelly Criterion ─────────────────────────────────────────────────────────
# Fraction of full Kelly to use (0.25 = quarter Kelly, conservative and standard).
KELLY_FRACTION = 0.25
KELLY_MAX_BET_FRACTION = 0.05  # Never risk more than 5% of bankroll on one bet.

# ─── MLB Model Filter ────────────────────────────────────────────────────────
REQUIRE_MODEL_FOR_MLB = False
MAX_MODEL_RANK = None  # e.g. 8 to allow only rank <= 8, None disables

# ─── Reporting ────────────────────────────────────────────────────────────────
REPORT_TIMEZONE = ZoneInfo("America/Chicago")

LOG_PATH = "bet_log.jsonl"
LINE_HISTORY_PATH = "line_history.json"
PASTED_OUTPUT_PATH = "pasted_outputs.txt"

# ─── Production Profile ──────────────────────────────────────────────────────
PROD_MIN_EDGE = 0.015  # 1.5 percentage points
PROD_REQUIRE_MODEL_MLB = True
PROD_MAX_MODEL_RANK = 8
