# Discord Bot Setup & Running Guide

## 🤖 What This Bot Does

- **Listens** to your Discord predictions channel 24/7
- **Parses** your friend's daily model predictions automatically
- **Updates** `model_predictions.json` in real-time
- **Reacts** with ✅ when predictions are successfully captured

## ⚙️ Setup (One-Time)

### 1. Install discord.py

```bash
pip install discord.py
```

### 2. Set Environment Variables

**Windows (PowerShell):**
```powershell
$env:DISCORD_BOT_TOKEN = "YOUR_BOT_TOKEN"
$env:DISCORD_CHANNEL_ID = "1258141669723734078"
```

**Windows (Command Prompt):**
```cmd
set DISCORD_BOT_TOKEN=YOUR_BOT_TOKEN
set DISCORD_CHANNEL_ID=1258141669723734078
```

**Mac/Linux:**
```bash
export DISCORD_BOT_TOKEN="YOUR_BOT_TOKEN"
export DISCORD_CHANNEL_ID="1258141669723734078"
```

### 3. Invite Bot to Server

1. Go to Discord Developer Portal
2. Your app → OAuth2 → URL Generator
3. Select scopes: `bot`
4. Select permissions: `View Channels`, `Read Messages`, `Add Reactions`
5. Copy generated URL and paste in browser
6. Authorize bot to your server

---

## 🚀 Running the Bot

### Option A: Manual (for testing)

```bash
python discord_bot.py
```

You'll see:
```
✓ Bot logged in as [YourBotName]
✓ Watching channel ID: 1258141669723734078
✓ Ready to parse predictions
```

### Option B: Auto-Start on Startup (Windows)

Create a batch file `start_bot.bat`:

```batch
@echo off
cd C:\Users\jorda\ev-betting-tool
set DISCORD_BOT_TOKEN=YOUR_BOT_TOKEN
set DISCORD_CHANNEL_ID=1258141669723734078
python discord_bot.py
pause
```

Double-click to start, or add to Task Scheduler for auto-launch.

---

## 📊 Workflow

1. **Start bot** in background:
   ```bash
   python discord_bot.py
   ```

2. **Friend posts predictions** → Bot auto-parses → ✅ reaction appears

3. **Run main betting pipeline:**
   ```bash
   python main.py
   ```

4. Predictions from Discord are automatically integrated into EV calculations

---

## 🔍 How Parsing Works

The bot looks for messages containing:
- **Team codes** (3-letter: SF, BAL, MIN, etc.)
- **Run differentials** (±X.XX format)
- **Confidence ranks** (1-15)

Example it will parse:

```
SF  | BAL  | 1.11  | 4
ARI | PHI  | 0.96  | 6
MIN | TOR  | 1.39  | 2
```

→ Saves to `model_predictions.json` with today's date

---

## ⚠️ Troubleshooting

**"LoginFailure" error:**
- Check bot token is correct
- Make sure bot is invited to server

**Bot not responding:**
- Check DISCORD_CHANNEL_ID is correct
- Verify bot has "Read Messages" permission

**Predictions not parsing:**
- Make sure message contains team codes AND run differentials
- Check format is similar to Discord table

---

## 💡 Pro Tips

1. **Keep bot running** in a terminal window while betting
2. **Check reactions** in Discord to confirm parsing worked
3. **Validate** model_predictions.json is updating:
   ```bash
   python model_predictions_parser.py --show
   ```

4. **Multiple bots** can run on same machine if needed

---

## 🔐 Security

- **Never share bot token** publicly
- Keep it in environment variables, not in code
- If compromised, regenerate in Developer Portal immediately
