"""
Helper utility to parse model predictions from Discord table and save to JSON.

Usage:
1. Export Discord table to CSV or manually input picks
2. Run this script with --date to update today's picks
3. Specify each pick as: away_team home_team run_diff confidence

Example:
    python model_predictions_parser.py --date 2026-04-12 --add "SF BAL 1.11 4"
"""

import argparse
from datetime import datetime
from model_input import load_model_predictions, save_model_predictions


def add_prediction(date_str, away_team, home_team, run_diff, confidence, odds_away=None, odds_home=None):
    """Add a single prediction to the model predictions file."""
    predictions = load_model_predictions()
    
    if date_str not in predictions:
        predictions[date_str] = []
    
    # Check if this matchup already exists
    for pred in predictions[date_str]:
        if pred["away_team"].upper() == away_team.upper() and pred["home_team"].upper() == home_team.upper():
            # Update existing
            pred["run_diff"] = run_diff
            pred["confidence"] = confidence
            if odds_away:
                pred["away_odds"] = odds_away
            if odds_home:
                pred["home_odds"] = odds_home
            save_model_predictions(predictions)
            print(f"✓ Updated: {away_team} @ {home_team} (run_diff: {run_diff}, confidence: {confidence})")
            return
    
    # Add new
    new_pred = {
        "away_team": away_team.upper(),
        "home_team": home_team.upper(),
        "run_diff": run_diff,
        "confidence": int(confidence),
        "projected_winner": "Home" if run_diff > 0 else "Away"
    }
    
    if odds_away:
        new_pred["away_odds"] = odds_away
    if odds_home:
        new_pred["home_odds"] = odds_home
    
    predictions[date_str].append(new_pred)
    save_model_predictions(predictions)
    print(f"✓ Added: {away_team} @ {home_team} (run_diff: {run_diff}, confidence: {confidence})")


def show_predictions(date_str):
    """Show all predictions for a date."""
    predictions = load_model_predictions()
    
    if date_str not in predictions:
        print(f"No predictions for {date_str}")
        return
    
    day_preds = predictions[date_str]
    print(f"\n===== Predictions for {date_str} =====\n")
    
    for i, pred in enumerate(day_preds, 1):
        away = pred.get("away_team")
        home = pred.get("home_team")
        run_diff = pred.get("run_diff")
        conf = pred.get("confidence")
        print(f"{i:2d}. {away:3s} @ {home:3s} | Run Diff: {run_diff:+.2f} | Rank: {conf:2d}")
    
    print(f"\nTotal: {len(day_preds)} games\n")


def parse_from_csv(date_str, csv_content):
    """Parse predictions from CSV format (simpler alternative)."""
    lines = csv_content.strip().split("\n")
    count = 0
    
    for line in lines:
        parts = line.split(",")
        if len(parts) < 4:
            continue
        
        try:
            away = parts[0].strip().upper()
            home = parts[1].strip().upper()
            run_diff = float(parts[2].strip())
            confidence = int(parts[3].strip())
            
            add_prediction(date_str, away, home, run_diff, confidence)
            count += 1
        except (ValueError, IndexError):
            print(f"✗ Skipped invalid line: {line}")
    
    print(f"\nSuccessfully parsed {count} predictions")


def copy_predictions(from_date, to_date, overwrite=False):
    """Copy all predictions from one date to another."""
    predictions = load_model_predictions()

    if from_date not in predictions:
        print(f"No predictions found for source date: {from_date}")
        return

    source = predictions[from_date]
    if to_date in predictions and predictions[to_date] and not overwrite:
        print(
            f"Target date {to_date} already has {len(predictions[to_date])} picks. "
            "Use --overwrite when copying if you want to replace them."
        )
        return

    copied = []
    for row in source:
        copied.append(dict(row))

    predictions[to_date] = copied
    save_model_predictions(predictions)
    print(f"Copied {len(copied)} predictions from {from_date} to {to_date}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Update model predictions from Discord")
    parser.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"), help="Date (YYYY-MM-DD)")
    parser.add_argument("--add", help="Add single pick: 'SF BAL 1.11 4'")
    parser.add_argument("--show", action="store_true", help="Show predictions for date")
    parser.add_argument("--csv", help="Parse from CSV: 'SF,BAL,1.11,4\\nARI,PHI,0.96,6'")
    parser.add_argument("--copy-from-date", help="Copy all picks from source date into --date")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite target date when used with --copy-from-date")
    
    args = parser.parse_args()
    
    if args.show:
        show_predictions(args.date)
    
    elif args.add:
        parts = args.add.split()
        if len(parts) >= 4:
            away, home, run_diff, confidence = parts[0], parts[1], float(parts[2]), int(parts[3])
            add_prediction(args.date, away, home, run_diff, confidence)
        else:
            print("Error: Expected format: 'SF BAL 1.11 4'")
    
    elif args.csv:
        parse_from_csv(args.date, args.csv)

    elif args.copy_from_date:
        copy_predictions(args.copy_from_date, args.date, overwrite=args.overwrite)
    
    else:
        show_predictions(args.date)
