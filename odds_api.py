import os
from datetime import datetime, timezone, timedelta

import requests

try:
    import winreg  # Windows-only; used to read user env vars without shell restart.
except ImportError:  # pragma: no cover - non-Windows platforms
    winreg = None

SPORTS = ["baseball_mlb", "basketball_nba"]
REGION = "us"
MARKET = "h2h"  # moneyline
ODDS_FORMAT = "american"

# --------------------------------------------------------------------------- #
# The Rundown API - fallback when The Odds API quota is exhausted              #
# Sign up free (no credit card) at https://therundown.io/api                  #
# Set env var: THERUNDOWN_KEY                                                  #
# --------------------------------------------------------------------------- #
_RUNDOWN_BASE = "https://therundown.io/api/v2"
_RUNDOWN_RAPID_HOST = "therundown-therundown-v1.p.rapidapi.com"
_RUNDOWN_RAPID_BASE = f"https://{_RUNDOWN_RAPID_HOST}"

# sport_key -> The Rundown sport_id (MLB=3, NBA=4)
_RUNDOWN_SPORT_MAP = {
    "baseball_mlb": 3,
    "basketball_nba": 4,
}

# Module-level flag: set True once The Odds API signals quota exhaustion so
# subsequent calls in the same process skip straight to the fallback.
_odds_api_quota_exhausted = False

# Cached affiliate_id (str) -> book name, loaded once from /affiliates endpoint.
_rundown_affiliate_map: dict = {}


# --------------------------------------------------------------------------- #
# The Odds API helpers                                                         #
# --------------------------------------------------------------------------- #

def _get_api_key():
    return os.getenv("ODDS_API_KEY") or os.getenv("THE_ODDS_API_KEY")


def _mask_key(api_key):
    if not api_key:
        return "<missing>"
    if len(api_key) <= 4:
        return "*" * len(api_key)
    return f"{'*' * (len(api_key) - 4)}{api_key[-4:]}"


def _print_auth_error(sport, api_key):
    masked_key = _mask_key(api_key)
    print(
        f"Error fetching {sport}: 401 Unauthorized from The Odds API. "
        f"Configured key: {masked_key}."
    )
    print("Set ODDS_API_KEY or THE_ODDS_API_KEY to an active The Odds API key, then rerun.")


def _quota_exhausted_from_response(response) -> bool:
    if response.status_code == 429:
        return True
    if response.status_code == 401:
        try:
            body = response.json()
            msg = str(body.get("message", "")).lower()
            if "quota" in msg or "usage" in msg or "limit" in msg:
                return True
        except ValueError:
            pass
    remaining = response.headers.get("x-requests-remaining", "")
    try:
        if int(remaining) == 0:
            return True
    except (ValueError, TypeError):
        pass
    return False


def _request_json(url, params, sport, purpose):
    global _odds_api_quota_exhausted
    try:
        response = requests.get(url, params=params, timeout=20)
    except requests.RequestException as exc:
        print(f"Request error for {purpose} {sport}: {exc}")
        return None

    if _quota_exhausted_from_response(response):
        print(
            f"The Odds API quota exhausted (HTTP {response.status_code}) for {sport}. "
            "Switching to The Rundown fallback for remainder of this session."
        )
        _odds_api_quota_exhausted = True
        return None

    if response.status_code == 401:
        _print_auth_error(sport, params.get("apiKey"))
        return None

    if response.status_code != 200:
        print(f"Error fetching {purpose} {sport}: {response.status_code}")
        return None

    try:
        return response.json()
    except ValueError as exc:
        print(f"Invalid JSON returned for {purpose} {sport}: {exc}")
        return None


# --------------------------------------------------------------------------- #
# The Rundown API helpers                                                      #
# --------------------------------------------------------------------------- #

def _get_rundown_key():
    key = os.getenv("THERUNDOWN_KEY") or os.getenv("RUNDOWN_KEY")
    if key:
        return key

    if winreg is not None:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment") as env_key:
                reg_key, _ = winreg.QueryValueEx(env_key, "THERUNDOWN_KEY")
                if reg_key:
                    return reg_key
        except OSError:
            pass

    return None


def _rundown_request(path, params=None):
    key = _get_rundown_key()
    if not key:
        return None
    headers = {"X-TheRundown-Key": key}
    url = f"{_RUNDOWN_BASE}{path}"
    req_params = dict(params or {})
    req_params["key"] = key
    try:
        response = requests.get(url, params=req_params, headers=headers, timeout=20)
    except requests.RequestException as exc:
        print(f"[Rundown] Request error {path}: {exc}")
        return None

    # If the key was issued via RapidAPI, direct Rundown endpoints can return 401.
    # Retry the same path against RapidAPI host before failing.
    if response.status_code == 401:
        rapid_headers = {
            "x-rapidapi-key": key,
            "x-rapidapi-host": _RUNDOWN_RAPID_HOST,
        }
        rapid_url = f"{_RUNDOWN_RAPID_BASE}{path}"
        try:
            response = requests.get(rapid_url, params=params, headers=rapid_headers, timeout=20)
        except requests.RequestException as exc:
            print(f"[Rundown] RapidAPI request error {path}: {exc}")
            return None

    if response.status_code != 200:
        print(f"[Rundown] Error {path}: HTTP {response.status_code}")
        return None
    try:
        return response.json()
    except ValueError as exc:
        print(f"[Rundown] Invalid JSON {path}: {exc}")
        return None


def _load_rundown_affiliates():
    global _rundown_affiliate_map
    if _rundown_affiliate_map:
        return
    data = _rundown_request("/affiliates")
    if not data:
        return
    for aff in data.get("affiliates", []):
        aff_id = str(aff.get("affiliate_id", ""))
        name = aff.get("affiliate_name", "") or aff.get("name", "")
        if aff_id and name:
            # normalize to lowercase with no spaces to match CANDIDATE_BOOKS style
            _rundown_affiliate_map[aff_id] = name.lower().replace(" ", "")


def _get_odds_rundown(sport_key: str, date_str: str) -> list:
    sport_id = _RUNDOWN_SPORT_MAP.get(sport_key)
    if not sport_id:
        return []
    _load_rundown_affiliates()
    data = _rundown_request(
        f"/sports/{sport_id}/events/{date_str}",
        params={"market_ids": "1", "main_line": "true", "offset": "300"},
    )
    if not data:
        return []

    events = []
    for event in data.get("events", []):
        event_id = event.get("event_id", "")
        event_date = event.get("event_date", "")

        teams = event.get("teams", [])
        home_team = ""
        away_team = ""
        for t in teams:
            full_name = f"{t.get('name', '')} {t.get('mascot', '')}".strip()
            if t.get("is_home"):
                home_team = full_name
            elif t.get("is_away"):
                away_team = full_name

        if not home_team or not away_team:
            continue

        bookmakers = []

        # V2 shape: markets[] -> participants[] -> lines[] -> prices{affiliate_id: {price,...}}
        moneyline = None
        for m in event.get("markets", []):
            if m.get("market_id") == 1:
                moneyline = m
                break

        if moneyline:
            affiliate_outcomes: dict = {}
            for participant in moneyline.get("participants", []):
                p_name = participant.get("name", "")
                for line in participant.get("lines", []):
                    for aff_id, price_info in line.get("prices", {}).items():
                        price = price_info.get("price")
                        if price is None:
                            continue
                        price_int = int(round(price))
                        if price_int == 0:
                            continue
                        if aff_id not in affiliate_outcomes:
                            affiliate_outcomes[aff_id] = []
                        affiliate_outcomes[aff_id].append({"name": p_name, "price": price_int})

            for aff_id, outcomes in affiliate_outcomes.items():
                if len(outcomes) < 2:
                    continue
                book_name = _rundown_affiliate_map.get(str(aff_id), f"book_{aff_id}")
                bookmakers.append({
                    "title": book_name,
                    "markets": [{"key": "h2h", "outcomes": outcomes}],
                })

        # V1 shape (common on RapidAPI): lines{affiliate_id: {moneyline:{...}, affiliate:{...}}}
        lines_obj = event.get("lines")
        if isinstance(lines_obj, dict):
            for aff_id, line_data in lines_obj.items():
                if not isinstance(line_data, dict):
                    continue
                moneyline_obj = line_data.get("moneyline") or {}
                away_price = moneyline_obj.get("moneyline_away")
                home_price = moneyline_obj.get("moneyline_home")
                if away_price is None or home_price is None:
                    continue
                away_price_int = int(round(away_price))
                home_price_int = int(round(home_price))
                if away_price_int == 0 or home_price_int == 0:
                    continue

                affiliate = line_data.get("affiliate") or {}
                if isinstance(affiliate, dict):
                    affiliate_name = affiliate.get("affiliate_name", "")
                else:
                    affiliate_name = str(affiliate)
                book_name = (
                    affiliate_name.lower().replace(" ", "")
                    if affiliate_name
                    else _rundown_affiliate_map.get(str(aff_id), f"book_{aff_id}")
                )

                bookmakers.append({
                    "title": book_name,
                    "markets": [{
                        "key": "h2h",
                        "outcomes": [
                            {"name": away_team, "price": away_price_int},
                            {"name": home_team, "price": home_price_int},
                        ],
                    }],
                })

        events.append({
            "id": event_id,
            "sport_key": sport_key,
            "commence_time": event_date,
            "home_team": home_team,
            "away_team": away_team,
            "bookmakers": bookmakers,
        })

    return events


def _get_scores_rundown() -> dict:
    scores_by_id = {}
    today = datetime.now(timezone.utc).date()
    for sport_key, sport_id in _RUNDOWN_SPORT_MAP.items():
        for day_offset in range(4):
            date_str = (today - timedelta(days=day_offset)).isoformat()
            data = _rundown_request(
                f"/sports/{sport_id}/events/{date_str}",
                params={"market_ids": "1", "main_line": "true", "offset": "300"},
            )
            if not data:
                continue
            for event in data.get("events", []):
                event_id = event.get("event_id", "")
                if not event_id:
                    continue
                score_obj = event.get("score", {})
                status = score_obj.get("event_status", "")
                completed = "final" in status.lower() or status in ("STATUS_FINAL", "STATUS_FULL_TIME")

                teams = event.get("teams", [])
                home_team = ""
                away_team = ""
                for t in teams:
                    full_name = f"{t.get('name', '')} {t.get('mascot', '')}".strip()
                    if t.get("is_home"):
                        home_team = full_name
                    elif t.get("is_away"):
                        away_team = full_name

                score_entries = []
                if home_team and score_obj.get("score_home") is not None:
                    score_entries.append({"name": home_team, "score": str(score_obj["score_home"])})
                if away_team and score_obj.get("score_away") is not None:
                    score_entries.append({"name": away_team, "score": str(score_obj["score_away"])})

                scores_by_id[event_id] = {
                    "id": event_id,
                    "sport_key": sport_key,
                    "home_team": home_team,
                    "away_team": away_team,
                    "completed": completed,
                    "scores": score_entries if completed else [],
                }
    return scores_by_id


# --------------------------------------------------------------------------- #
# Public API (unchanged signatures)                                            #
# --------------------------------------------------------------------------- #

def get_odds():
    global _odds_api_quota_exhausted
    all_games = []
    api_key = _get_api_key()

    if not _odds_api_quota_exhausted and api_key:
        for sport in SPORTS:
            url = f"https://api.the-odds-api.com/v4/sports/{sport}/odds"
            params = {
                "apiKey": api_key,
                "regions": REGION,
                "markets": MARKET,
                "oddsFormat": ODDS_FORMAT,
            }
            data = _request_json(url, params, sport, "odds")
            if data is None:
                if _odds_api_quota_exhausted:
                    break  # fall through to fallback
                continue
            for game in data:
                game["sport_key"] = sport
            all_games.extend(data)

        if not _odds_api_quota_exhausted:
            return all_games
    elif not api_key:
        print("No Odds API key configured. Set ODDS_API_KEY or THE_ODDS_API_KEY, then rerun.")

    # --- Fallback: The Rundown API ---
    if not _get_rundown_key():
        print(
            "The Rundown fallback unavailable: set THERUNDOWN_KEY environment variable. "
            "Sign up free (no credit card) at https://therundown.io/api"
        )
        return all_games

    print("[Rundown] Using fallback provider for odds.")
    today = datetime.now(timezone.utc).date()
    for sport in SPORTS:
        for day_offset in range(3):
            date_str = (today + timedelta(days=day_offset)).isoformat()
            all_games.extend(_get_odds_rundown(sport, date_str))

    return all_games


def get_scores(days_from=3):
    """Fetch score snapshots for supported sports keyed by event id."""
    global _odds_api_quota_exhausted
    scores_by_id = {}
    api_key = _get_api_key()

    if not _odds_api_quota_exhausted and api_key:
        for sport in SPORTS:
            url = f"https://api.the-odds-api.com/v4/sports/{sport}/scores"
            params = {
                "apiKey": api_key,
                "daysFrom": days_from,
            }
            data = _request_json(url, params, sport, "scores for")
            if data is None:
                if _odds_api_quota_exhausted:
                    break
                continue
            for game in data:
                game["sport_key"] = sport
                game_id = game.get("id")
                if game_id:
                    scores_by_id[game_id] = game

        if not _odds_api_quota_exhausted:
            return scores_by_id

    # --- Fallback: The Rundown API ---
    if not _get_rundown_key():
        print(
            "The Rundown fallback unavailable: set THERUNDOWN_KEY environment variable. "
            "Sign up free (no credit card) at https://therundown.io/api"
        )
        return scores_by_id

    print("[Rundown] Using fallback provider for scores.")
    return _get_scores_rundown()
