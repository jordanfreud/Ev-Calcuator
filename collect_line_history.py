import argparse
import time
from datetime import datetime, timezone

from odds_api import get_odds
from main import _extract_home_away_prices, _normalize_book_name
from config import CANDIDATE_BOOKS
from line_movement import record_line_snapshot


def collect_once():
    data = get_odds()
    count = 0

    for game in data:
        event_id = game.get("id")
        home_team = game.get("home_team")
        away_team = game.get("away_team")
        if not event_id or not home_team or not away_team:
            continue

        for bookmaker in game.get("bookmakers", []):
            markets = bookmaker.get("markets")
            if not markets:
                continue

            outcomes = markets[0].get("outcomes", [])
            prices = _extract_home_away_prices(outcomes, home_team, away_team)
            if not prices:
                continue

            normalized = _normalize_book_name(bookmaker.get("title"))
            if normalized not in CANDIDATE_BOOKS:
                continue

            odds_home, odds_away = prices
            record_line_snapshot(event_id, bookmaker.get("title"), odds_away, odds_home)
            count += 1

    ts = datetime.now(timezone.utc).isoformat()
    print(f"[{ts}] snapshots recorded: {count}")


def main():
    parser = argparse.ArgumentParser(description="Collect odds snapshots to build line-movement signal")
    parser.add_argument("--interval-seconds", type=int, default=300, help="Polling interval in seconds")
    parser.add_argument("--iterations", type=int, default=0, help="0 means run forever")
    args = parser.parse_args()

    runs = 0
    while True:
        collect_once()
        runs += 1

        if args.iterations > 0 and runs >= args.iterations:
            break

        time.sleep(args.interval_seconds)


if __name__ == "__main__":
    main()
