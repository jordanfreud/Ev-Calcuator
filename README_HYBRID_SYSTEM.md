# EV Betting Tool - Hybrid System Complete

## ✅ What You Now Have

A complete **hybrid edge detection system** that combines:

1. **Market Probability** (60%) — Sharp book consensus
2. **Model Probability** (30%) — Your friend's Discord predictions  
3. **Line Movement** (10%) — Sharp money signals

---

## 📋 System Components

### Core Files

| File | Purpose |
|------|---------|
| `main.py` | Main betting pipeline (finds EV opportunities) |
| `probability.py` | Hybrid blending logic |
| `model_input.py` | Loads friend's model predictions |
| `line_movement.py` | Tracks line movement signals |
| `discord_bot.py` | Auto-parses Discord predictions |
| `model_predictions.json` | Daily predictions (auto-updated) |

---

## 🚀 Running the System

### **Option A: Manual (Full Control)**

#### Step 1: Update predictions
```bash
python model_predictions_parser.py --add "SF BAL 1.11 4"
python model_predictions_parser.py --add "ARI PHI 0.96 6"
```

#### Step 2: Check what you added
```bash
python model_predictions_parser.py --show
```

#### Step 3: Run the betting pipeline
```bash
python main.py
```

---

### **Option B: Automated (Recommended)**

#### Step 1: Start the Discord bot in one window
```powershell
.\start_bot.ps1
```

(Or run `python discord_bot.py` if using Command Prompt)

You'll see:
```
✓ Bot logged in as [YourBotName]
✓ Watching channel ID: 1258141669723734078
✓ Ready to parse predictions
```

**Keep this window open in background.**

#### Step 2: In another window, run the pipeline daily
```bash
python main.py
```

---

## 📊 Example Workflow (Daily)

### **With Bot (Automated)**

```
9:00 AM  → Friend posts predictions to Discord
9:01 AM  → Bot auto-parses and updates model_predictions.json ✅
10:30 AM → You run: python main.py
10:32 AM → System outputs bets (market + model blend)
         → You manually place bets
5:00 PM  → Games finish, results auto-track in bet_log.jsonl
```

### **Without Bot (Manual)**

```
10:00 AM → Copy friend's picks from Discord manually
10:02 AM → python model_predictions_parser.py --add "SF BAL 1.11 4"
         → ... repeat for each game
10:30 AM → python main.py
         → Bets output
         → Place manually
5:00 PM  → Results auto-tracked
```

---

## 🎯 Key Features

### Hybrid Probability Blend

```python
your_prob = 0.6 * market_prob + 0.3 * model_prob + 0.2 * line_signal
```

**Output:**
```
SF vs BAL (baseball_mlb)
  Book: DraftKings
  Team: BAL
  Odds: -125
  EV: 3.42% [Model Rank: 4]  ← Shows model confidence
```

### Model Confidence Tracking

Predictions include `confidence` rank (1-15):
- **1-4** = Highest confidence picks
- **5-10** = Medium confidence
- **11-15** = Lower confidence

Track performance by confidence level to find your edge.

---

## 📈 Validation

Your system now automatically tracks:

- ✅ **CLV** (Closing Line Value) - Most important metric
- ✅ **ROI** - Return on investment per unit
- ✅ **Win Rate** - Percentage of winning bets
- ✅ **Model Performance** - Do certain ranks perform better?

All data stored in `bet_log.jsonl` (append-only log format).

---

## ⚙️ Setup Checklist

- [x] Created hybrid blending function
- [x] Created model input layer
- [x] Created line movement tracking
- [x] Integrated into main.py
- [x] Created model_predictions.json with sample data
- [x] Built Discord bot for auto-parsing
- [x] Created utility scripts (parser, starter)
- [x] Installed dependencies (discord.py, requests, numpy, tzdata)

---

## 🔧 Customization

### Adjust Blend Weights

In [probability.py](probability.py), modify `hybrid_probability()`:

```python
# Current: 60% market, 30% model, 10% line
blend_away = (0.6 * market_away) + (0.3 * model_away)

# To trust model more: 50% market, 40% model, 10% line
blend_away = (0.5 * market_away) + (0.4 * model_away)
```

### Adjust Run Diff Scaling

In [model_input.py](model_input.py):

```python
# Current scaling: 1.5
prob = 1 / (1 + math.exp(-run_diff / 1.5))

# Tighter curve (less extreme probabilities): 2.0
# Wider curve (more extreme probabilities): 1.0
```

### Adjust EV Floor

In [config.py](config.py):

```python
EV_FLOOR = -0.02  # Currently -2%
# Change to 0.00 for only positive EV bets
# Change to -0.05 for more aggressive bets
```

---

## 🚨 Troubleshooting

### No bets showing?

1. Check `model_predictions.json` has today's data
   ```bash
   python model_predictions_parser.py --show
   ```

2. Check market prob matches model prob (no disagreement = no EV)
   - Add sample data to test: `model_predictions.json`

3. Check EV_FLOOR isn't too high
   - Try lowering: `EV_FLOOR = -0.05`

### Bot not parsing predictions?

1. Check message format contains team codes + run differentials
2. Verify bot has permission to read the channel
3. Check bot token is correct (run `python discord_bot.py` manually with debug)

### Wrong team codes?

Use exactly 3 letters:
- ✅ `SF`, `BAL`, `MIN`
- ❌ `SFG`, `BALTIMORE`, `SF Giants`

---

## 💡 Next Steps

1. **Start the bot** (keep running in background):
   ```powershell
   .\start_bot.ps1
   ```

2. **Run a test** with today's picks:
   ```bash
   python main.py
   ```

3. **Monitor for 1-2 weeks**:
   - Track CLV (most important)
   - Note which model ranks perform best
   - Adjust blend weights if needed

4. **Validate results**:
   ```bash
   python main.py --report
   ```

---

## 📞 Summary

| Task | Command |
|------|---------|
| Add today's picks | `python model_predictions_parser.py --add "SF BAL 1.11 4"` |
| View today's picks | `python model_predictions_parser.py --show` |
| Run betting pipeline | `python main.py` |
| Auto-parse Discord | `.\start_bot.ps1` |
| Show performance | `python main.py --report` |

---

**You're now running a sophisticated hybrid edge detection system.** 

The key insight: You're no longer just mirroring the market. You're creating disagreement with it by incorporating an independent probability source (your friend's model). That disagreement = edge.

Track CLV religiously. That's your only real metric.
