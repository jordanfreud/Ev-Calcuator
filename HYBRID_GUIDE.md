# Hybrid Edge Detection System

Your ev-betting-tool now uses a **hybrid probability blend** that combines three signals:

## 🎯 The Hybrid Blend

```
Your Probability = 60% Market + 30% Model + Line Movement Signal
```

### Sources

1. **Market Probability (60%)** — Consensus from sharp books (DraftKings, FanDuel, etc.)
2. **Model Probability (30%)** — External model (friend's Discord predictions converted to probabilities)
3. **Line Movement (10%)** — Confidence boost when sharp money moves odds

## 📊 Model Input Format

Edit `model_predictions.json` to add your friend's daily picks:

```json
{
  "2026-04-12": [
    {
      "away_team": "SF",
      "home_team": "BAL",
      "run_diff": 1.11,
      "confidence": 4
    }
  ]
}
```

**Fields:**
- `away_team` / `home_team` — 3-letter team codes
- `run_diff` — Projected run differential (positive = home advantage)
- `confidence` — Model rank (1 = highest confidence, 15 = lowest)

## 🔧 Managing Model Predictions

### Quick Add (Single Pick)
```bash
python model_predictions_parser.py --add "SF BAL 1.11 4"
```

### View Today's Picks
```bash
python model_predictions_parser.py --show
```

### Batch Add from Discord Table
Copy the table from Discord and paste:
```bash
python model_predictions_parser.py --csv "SF,BAL,1.11,4
ARI,PHI,0.96,6
MIN,TOR,1.39,2"
```

### Specific Date
```bash
python model_predictions_parser.py --show --date 2026-04-14
```

## 🚀 Running the Pipeline

```bash
python main.py
```

### What You'll See

Bets now include model confidence ranking:

```
SF vs BAL (baseball_mlb)
  Book: DraftKings
  Team: BAL
  Odds: -125
  Book Lines: DraftKings: BAL -125 | SF +110
  EV: 3.42% [Model Rank: 4]
```

The model rank shows **how confident your friend's model is** in this pick (lower is better).

## 📈 Expected Impact

**Before (Market Only):**
- Your prob ≈ Market prob
- EV ≈ 0
- Almost no bets

**After (Hybrid):**
- Your prob ≠ Market prob
- EV = real edges
- Bets appear when model disagrees with market

## 🔍 What's Being Tracked

Your bet log now includes:
- `model_source` — Where the probability came from
- `model_rank` — Confidence level for each bet

This lets you validate:
- Do high-confidence picks (rank 1-5) perform better?
- What's your CLV across different confidence tiers?

## ⚠️ Important Notes

1. **Update Daily** — Add today's picks before running main.py
2. **Team Codes** — Use official 3-letter codes (SF, BAL, MIN, etc.)
3. **Run Diff Scaling** — The default logistic uses 1.5 scaling. Adjust if needed in `model_input.py`
4. **Validate Results** — Track CLV and ROI per confidence level to find the sweet spot

## 📋 Example Daily Workflow

```bash
# 1. Update today's picks (10:30 AM)
python model_predictions_parser.py --add "SF BAL 1.11 4"
python model_predictions_parser.py --add "ARI PHI 0.96 6"
python model_predictions_parser.py --add "MIN TOR 1.39 2"

# 2. Run the pipeline
python main.py

# 3. Review output
# (Manually place bets)

# 4. Grade at end of day (already handles this)
# Results automatically tracked in bet_log.jsonl
```
