"""
Discord bot that automatically parses MLB model predictions and updates model_predictions.json

The bot listens to a specific channel and extracts prediction data from messages,
converting them to the model_predictions.json format.

Usage:
    python discord_bot.py --token YOUR_TOKEN --channel 1258141669723734078
    
Or set environment variables:
    export DISCORD_BOT_TOKEN=your_token
    export DISCORD_CHANNEL_ID=1258141669723734078
    python discord_bot.py
"""

import discord
from discord.ext import commands
import os
import re
from io import BytesIO
from datetime import datetime, timezone
from model_input import load_model_predictions, save_model_predictions
from config import REPORT_TIMEZONE

try:
    from PIL import Image, ImageOps, ImageEnhance
    import pytesseract
    OCR_AVAILABLE = True
except ImportError:
    OCR_AVAILABLE = False


# Bot configuration
intents = discord.Intents.default()
# This bot parses channel message text, so message content intent is required.
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# Settings
CHANNEL_ID = int(os.getenv("DISCORD_CHANNEL_ID", "1258141669723734078"))
PREDICTION_MESSAGE_ID = None  # Will store the message ID of prediction posts
MLB_CODES = {
    "ARI", "ATL", "BAL", "BOS", "CHC", "CWS", "CIN", "CLE", "COL", "DET",
    "HOU", "KC", "LAA", "LAD", "MIA", "MIL", "MIN", "NYM", "NYY", "ATH",
    "PHI", "PIT", "SD", "SF", "SEA", "STL", "TB", "TEX", "TOR", "WSH",
}


def _configure_tesseract_path():
    if not OCR_AVAILABLE:
        return

    explicit = os.getenv("TESSERACT_CMD")
    if explicit:
        pytesseract.pytesseract.tesseract_cmd = explicit
        return

    candidates = [
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    ]
    for path in candidates:
        if os.path.exists(path):
            pytesseract.pytesseract.tesseract_cmd = path
            return


@bot.event
async def on_ready():
    """Bot startup."""
    print(f"✓ Bot logged in as {bot.user}")
    print(f"✓ Watching channel ID: {CHANNEL_ID}")
    print(f"✓ Ready to parse predictions")
    if OCR_AVAILABLE:
        _configure_tesseract_path()
        print("✓ OCR fallback available for image-only posts")
    else:
        print("⚠️ OCR fallback not available. Install pillow and pytesseract to parse image-only posts.")

    await _backfill_today_predictions()


@bot.event
async def on_message(message):
    """Listen for prediction messages and parse them."""
    
    # Ignore bot's own messages
    if message.author == bot.user:
        return
    
    # Only listen to the predictions channel
    if message.channel.id != CHANNEL_ID:
        return
    
    parsed = await _extract_predictions_from_message(message)
    if parsed:
        date_str = datetime.now(REPORT_TIMEZONE).date().isoformat()
        _save_predictions(parsed, date_str)
        print(f"✓ Updated {len(parsed)} predictions for {date_str}")
        try:
            await message.add_reaction("✅")
        except discord.HTTPException:
            pass
    
    await bot.process_commands(message)


def _contains_predictions(content: str) -> bool:
    """Check if message likely contains predictions."""
    # Look for team code patterns (3-letter codes typically)
    team_pattern = r'\b[A-Z]{2,3}\b'
    teams = re.findall(team_pattern, content)
    
    # Look for run differential patterns (+-X.XX)
    run_diff_pattern = r'[+-]\d+\.\d+'
    run_diffs = re.findall(run_diff_pattern, content)
    
    # If we find both teams and run differentials, likely predictions
    return len(teams) >= 2 and len(run_diffs) >= 1


def _parse_predictions(content: str) -> list:
    """
    Parse prediction table from Discord message.
    
    Expected format (from CLUTCH DAILY MLB MODEL):
    Game | Away | Home | Proj Run Diff | Model Rank
    1    | SF   | BAL  | 1.11          | 4
    2    | ARI  | PHI  | 0.96          | 6
    ...
    """
    predictions = []
    
    # Split by lines
    lines = content.split('\n')
    
    for line in lines:
        # Skip header rows and separators
        if any(skip in line.lower() for skip in ['game', 'lineups', 'away', 'home', 'rank', '---', '___']):
            continue
        
        # Try to extract: game_num | away | home | run_diff | confidence
        # Format can be flexible
        parts = [p.strip() for p in line.split('|')]
        
        if len(parts) >= 4:
            try:
                # Skip game number (first part is usually just a number)
                away = parts[1].upper().strip()
                home = parts[2].upper().strip()
                
                # Extract run differential
                run_diff_str = parts[3].strip().replace('+', '')
                run_diff = float(run_diff_str)
                
                # Extract confidence rank (usually last part)
                confidence = int(parts[-1].strip()) if len(parts) >= 5 else 15
                
                # Validate team codes (should be 2-3 letters)
                if 2 <= len(away) <= 3 and 2 <= len(home) <= 3:
                    pred = {
                        "away_team": away,
                        "home_team": home,
                        "run_diff": run_diff,
                        "confidence": confidence,
                        "projected_winner": "Home" if run_diff > 0 else "Away"
                    }
                    predictions.append(pred)
                    print(f"  ✓ {away} @ {home}: {run_diff:+.2f} (rank {confidence})")
            
            except (ValueError, IndexError) as e:
                # Skip lines that don't parse
                continue
    
    # OCR fallback path can still pass plain text without separators.
    if predictions:
        return predictions

    return _parse_predictions_loose(content)


def _parse_predictions_loose(content: str) -> list:
    """Parse OCR-like text by heuristics (team codes + run diff + rank)."""
    predictions = []
    seen = set()

    lines = [ln.strip().upper() for ln in content.splitlines() if ln.strip()]
    for line in lines:
        tokens = re.findall(r"[A-Z]{2,3}|[+-]?\d+\.\d+|\d+", line)
        if not tokens:
            continue

        teams = [t for t in tokens if t in MLB_CODES]
        run_diffs = [t for t in tokens if re.fullmatch(r"[+-]?\d+\.\d+", t)]
        ranks = [t for t in tokens if re.fullmatch(r"\d+", t)]

        if len(teams) < 2 or not run_diffs or not ranks:
            continue

        away, home = teams[0], teams[1]

        try:
            run_diff = float(run_diffs[-1])
            confidence = int(ranks[-1])
        except ValueError:
            continue

        if not (1 <= confidence <= 30):
            continue
        if not (-10.0 <= run_diff <= 10.0):
            continue

        key = (away, home)
        if key in seen:
            continue
        seen.add(key)

        predictions.append(
            {
                "away_team": away,
                "home_team": home,
                "run_diff": run_diff,
                "confidence": confidence,
                "projected_winner": "Home" if run_diff > 0 else "Away",
            }
        )

    return predictions


def _preprocess_for_ocr(image: Image.Image) -> Image.Image:
    gray = ImageOps.grayscale(image)
    upscaled = gray.resize((gray.width * 2, gray.height * 2))
    contrast = ImageEnhance.Contrast(upscaled).enhance(1.8)
    return contrast


async def _parse_predictions_from_attachments(attachments) -> list:
    if not OCR_AVAILABLE:
        print("⚠️ OCR dependencies missing: pip install pillow pytesseract")
        return []

    all_predictions = []
    seen = set()

    for attachment in attachments:
        name = (attachment.filename or "").lower()
        content_type = (attachment.content_type or "").lower()
        if not (
            name.endswith((".png", ".jpg", ".jpeg", ".webp"))
            or content_type.startswith("image/")
        ):
            continue

        try:
            raw = await attachment.read()
            image = Image.open(BytesIO(raw))
            processed = _preprocess_for_ocr(image)
            text = pytesseract.image_to_string(processed, config="--psm 6")
        except Exception as ex:
            print(f"⚠️ OCR failed for attachment {attachment.filename}: {ex}")
            continue

        parsed = _parse_predictions_loose(text)
        for row in parsed:
            key = (row["away_team"], row["home_team"])
            if key in seen:
                continue
            seen.add(key)
            all_predictions.append(row)

    return all_predictions


def _message_text(message) -> str:
    text_blobs = [message.content or ""]
    for embed in message.embeds:
        if embed.title:
            text_blobs.append(embed.title)
        if embed.description:
            text_blobs.append(embed.description)
        if embed.fields:
            for field in embed.fields:
                if field.name:
                    text_blobs.append(field.name)
                if field.value:
                    text_blobs.append(field.value)
    return "\n".join(t for t in text_blobs if t)


async def _extract_predictions_from_message(message) -> list:
    combined_text = _message_text(message)
    if _contains_predictions(combined_text):
        print(f"\n📊 Parsing predictions from {message.author}...")
        predictions = _parse_predictions(combined_text)
        if predictions:
            return predictions

    if message.attachments:
        predictions = await _parse_predictions_from_attachments(message.attachments)
        if predictions:
            return predictions

    return []


async def _backfill_today_predictions():
    today_str = datetime.now(REPORT_TIMEZONE).date().isoformat()
    existing = load_model_predictions().get(today_str, [])
    if existing:
        print(f"✓ Existing predictions already present for {today_str}; skipping backfill")
        return

    try:
        channel = bot.get_channel(CHANNEL_ID)
        if channel is None:
            channel = await bot.fetch_channel(CHANNEL_ID)
    except Exception as ex:
        print(f"⚠️ Could not access channel for backfill: {ex}")
        return

    try:
        async for message in channel.history(limit=25):
            message_date = message.created_at.astimezone(REPORT_TIMEZONE).date().isoformat()
            if message_date != today_str:
                continue

            predictions = await _extract_predictions_from_message(message)
            if predictions:
                _save_predictions(predictions, today_str)
                print(f"✓ Backfilled {len(predictions)} predictions for {today_str} from message {message.id}")
                return
    except Exception as ex:
        print(f"⚠️ Backfill failed: {ex}")


def _save_predictions(predictions: list, date_str: str):
    """Save predictions to model_predictions.json."""
    existing = load_model_predictions()
    
    # Merge with existing (update for the day)
    if date_str not in existing:
        existing[date_str] = []
    
    # Remove duplicates by team matchup
    existing_matchups = {
        (p["away_team"].upper(), p["home_team"].upper()): p 
        for p in existing[date_str]
    }
    
    # Add/update new predictions
    for pred in predictions:
        key = (pred["away_team"].upper(), pred["home_team"].upper())
        existing_matchups[key] = pred
    
    # Convert back to list
    existing[date_str] = list(existing_matchups.values())
    
    # Save
    save_model_predictions(existing)


def main():
    """Start the bot."""
    token = os.getenv("DISCORD_BOT_TOKEN")
    
    if not token:
        print("Error: DISCORD_BOT_TOKEN environment variable not set")
        print("\nSet it with:")
        print("  Windows: set DISCORD_BOT_TOKEN=your_token")
        print("  MacOS/Linux: export DISCORD_BOT_TOKEN=your_token")
        return
    
    print("🚀 Starting Discord bot...")
    print(f"   Channel ID: {CHANNEL_ID}")
    print("\n(Ctrl+C to stop)")
    
    try:
        bot.run(token)
    except discord.errors.LoginFailure:
        print("✗ Login failed. Check your bot token.")
    except KeyboardInterrupt:
        print("\n✓ Bot stopped")


if __name__ == "__main__":
    main()
