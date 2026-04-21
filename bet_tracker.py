import json
import math
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, List

from config import LINE_HISTORY_PATH, LOG_PATH, PASTED_OUTPUT_PATH, REPORT_TIMEZONE
from odds_api import get_scores


@dataclass
class Summary:
    picks: int = 0
    graded: int = 0
    pending: int = 0
    wins: int = 0
    losses: int = 0
    pushes: int = 0
    units: float = 0.0
    total_ev: float = 0.0

    def as_dict(self):
        graded_non_push = self.wins + self.losses
        win_rate = (self.wins / graded_non_push * 100) if graded_non_push else 0.0
        roi = (self.units / self.graded * 100) if self.graded else 0.0
        avg_ev = (self.total_ev / self.picks * 100) if self.picks else 0.0
        return {
            "picks": self.picks,
            "graded": self.graded,
            "pending": self.pending,
            "wins": self.wins,
            "losses": self.losses,
            "pushes": self.pushes,
            "win_rate_pct": round(win_rate, 2),
            "units": round(self.units, 3),
            "roi_pct": round(roi, 2),
            "avg_ev_pct": round(avg_ev, 2),
        }


def _now_utc_iso():
    return datetime.now(timezone.utc).isoformat()


def _read_log() -> List[dict]:
    if not os.path.exists(LOG_PATH):
        return []

    rows = []
    with open(LOG_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def _write_log(rows: List[dict]):
    with open(LOG_PATH, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")


def append_new_picks(picks: List[dict]):
    existing = _read_log()
    existing_keys = {
        (
            row.get("event_id"),
            row.get("sport"),
            row.get("book"),
            row.get("team"),
            row.get("odds"),
        )
        for row in existing
        if row.get("record_type") == "pick"
    }

    new_rows = []
    for pick in picks:
        key = (
            pick.get("event_id"),
            pick.get("sport"),
            pick.get("book"),
            pick.get("team"),
            pick.get("odds"),
        )
        if key in existing_keys:
            continue
        record = {
            "record_type": "pick",
            "created_at": _now_utc_iso(),
            **pick,
            "graded": False,
            "result": None,
            "units": None,
            "graded_at": None,
        }
        new_rows.append(record)

    if new_rows:
        existing.extend(new_rows)
        _write_log(existing)

    return len(new_rows)


def _parse_pasted_entries(text: str) -> List[dict]:
    entries = []
    game_pattern = re.compile(r"^(?P<game>.+) \((?P<sport>[a-z_]+)\)$")
    team_pattern = re.compile(r"^\s*Team:\s*(?P<team>.+)$")
    odds_pattern = re.compile(r"^\s*Odds:\s*(?P<odds>[+-]?\d+)$")
    ev_pattern = re.compile(r"^\s*EV:\s*(?P<ev>-?\d+(?:\.\d+)?)%$")

    current = {}
    for raw_line in text.splitlines():
        line = raw_line.strip("\n")
        game_match = game_pattern.match(line.strip())
        if game_match:
            current = {
                "game": game_match.group("game"),
                "sport": game_match.group("sport"),
            }
            continue

        team_match = team_pattern.match(line)
        if team_match and current:
            current["team"] = team_match.group("team")
            continue

        odds_match = odds_pattern.match(line)
        if odds_match and current:
            current["odds"] = int(odds_match.group("odds"))
            continue

        ev_match = ev_pattern.match(line)
        if ev_match and current and "team" in current and "odds" in current:
            entries.append(
                {
                    "record_type": "provisional_pick",
                    "created_at": _now_utc_iso(),
                    "sport": current["sport"],
                    "game": current["game"],
                    "team": current["team"],
                    "odds": current["odds"],
                    "ev": float(ev_match.group("ev")) / 100.0,
                    "book": "unknown",
                    "event_id": None,
                    "commence_time": None,
                    "graded": False,
                    "result": None,
                    "units": None,
                    "graded_at": None,
                    "confidence": "low",
                }
            )
            current = {}

    return entries


def import_provisional_from_file(path=PASTED_OUTPUT_PATH):
    if not os.path.exists(path):
        return 0

    with open(path, "r", encoding="utf-8") as f:
        entries = _parse_pasted_entries(f.read())

    if not entries:
        return 0

    rows = _read_log()
    existing_keys = {
        (r.get("record_type"), r.get("sport"), r.get("game"), r.get("team"), r.get("odds"), r.get("ev"))
        for r in rows
    }

    created = 0
    for entry in entries:
        key = (
            entry.get("record_type"),
            entry.get("sport"),
            entry.get("game"),
            entry.get("team"),
            entry.get("odds"),
            entry.get("ev"),
        )
        if key in existing_keys:
            continue
        rows.append(entry)
        created += 1

    if created:
        _write_log(rows)

    return created


def _american_to_decimal(odds: int) -> float:
    if odds > 0:
        return (odds / 100.0) + 1.0
    return (100.0 / abs(odds)) + 1.0


def _american_to_prob(odds: int) -> float:
    if odds > 0:
        return 100.0 / (odds + 100.0)
    return -odds / (-odds + 100.0)


def calculate_clv_from_odds(open_odds: int, close_odds: int) -> float:
    """CLV in implied-probability points. Positive means you beat close."""
    return _american_to_prob(close_odds) - _american_to_prob(open_odds)


def _load_line_history() -> Dict:
    if not os.path.exists(LINE_HISTORY_PATH):
        return {}
    try:
        with open(LINE_HISTORY_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}


def _closing_odds_for_row(row: dict, line_history: Dict):
    event_id = row.get("event_id")
    book = row.get("book")
    game = row.get("game") or ""
    team = row.get("team")
    if not event_id or not book or " vs " not in game or not team:
        return None

    away_team, home_team = game.split(" vs ", 1)
    event_books = line_history.get(event_id, {})
    history = event_books.get(book, [])
    if not history:
        return None

    close = history[-1]
    close_away = close.get("away_odds")
    close_home = close.get("home_odds")
    if close_away is None or close_home is None:
        return None

    return close_home if team == home_team else close_away


def _winner_from_scores(score_rows: List[dict]):
    if not score_rows or len(score_rows) != 2:
        return None
    name1, score1 = score_rows[0].get("name"), score_rows[0].get("score")
    name2, score2 = score_rows[1].get("name"), score_rows[1].get("score")
    if name1 is None or name2 is None or score1 is None or score2 is None:
        return None
    try:
        score1 = int(score1)
        score2 = int(score2)
    except ValueError:
        return None

    if score1 == score2:
        return "push"
    return name1 if score1 > score2 else name2


def grade_pending_picks():
    rows = _read_log()
    if not rows:
        return 0

    scores_by_id = get_scores(days_from=3)
    line_history = _load_line_history()
    graded_count = 0

    for row in rows:
        if row.get("record_type") not in {"pick", "provisional_pick"} or row.get("graded"):
            continue

        # Grade only picks that were positive-EV at selection time.
        try:
            if float(row.get("ev", 0.0)) <= 0.0:
                continue
        except (TypeError, ValueError):
            continue

        event_id = row.get("event_id")

        game = scores_by_id.get(event_id) if event_id else None
        if game is None and row.get("record_type") == "provisional_pick":
            # Fuzzy match by sport + exact game string (away vs home)
            for score_game in scores_by_id.values():
                if score_game.get("sport_key") != row.get("sport"):
                    continue
                score_game_str = f"{score_game.get('away_team')} vs {score_game.get('home_team')}"
                if score_game_str == row.get("game"):
                    game = score_game
                    break

        if not game or not game.get("completed"):
            continue

        winner = _winner_from_scores(game.get("scores"))
        if winner is None:
            continue

        if winner == "push":
            result = "push"
            units = 0.0
        elif winner == row.get("team"):
            result = "win"
            units = _american_to_decimal(int(row["odds"])) - 1.0
        else:
            result = "loss"
            units = -1.0

        row["graded"] = True
        row["result"] = result
        row["units"] = units
        row["graded_at"] = _now_utc_iso()

        # Attach CLV when line history is available.
        try:
            placed_odds = int(row.get("odds"))
            close_odds = _closing_odds_for_row(row, line_history)
            if close_odds is not None:
                row["closing_odds"] = int(close_odds)
                row["clv"] = round(calculate_clv_from_odds(placed_odds, int(close_odds)), 4)
        except (TypeError, ValueError):
            pass

        if row.get("record_type") == "provisional_pick":
            row["confidence"] = "medium"
        graded_count += 1

    _write_log(rows)
    return graded_count


def _parse_dt(iso_str: str) -> datetime:
    return datetime.fromisoformat(iso_str)


def _in_yesterday_local(created_at: str) -> bool:
    dt = _parse_dt(created_at).astimezone(REPORT_TIMEZONE)
    now_local = datetime.now(REPORT_TIMEZONE)
    yesterday = (now_local - timedelta(days=1)).date()
    return dt.date() == yesterday


def _in_current_week_local(created_at: str) -> bool:
    dt = _parse_dt(created_at).astimezone(REPORT_TIMEZONE)
    now_local = datetime.now(REPORT_TIMEZONE)
    start_of_week = (now_local - timedelta(days=now_local.weekday())).date()
    end_of_week = start_of_week + timedelta(days=6)
    return start_of_week <= dt.date() <= end_of_week


def _summarize(rows: List[dict]) -> Dict[str, float]:
    summary = Summary()
    for row in rows:
        if row.get("record_type") not in {"pick", "provisional_pick"}:
            continue
        summary.picks += 1
        summary.total_ev += float(row.get("ev", 0.0))
        if row.get("graded"):
            summary.graded += 1
            result = row.get("result")
            if result == "win":
                summary.wins += 1
            elif result == "loss":
                summary.losses += 1
            elif result == "push":
                summary.pushes += 1
            summary.units += float(row.get("units") or 0.0)
        else:
            summary.pending += 1
    return summary.as_dict()


def performance_report() -> Dict[str, Dict[str, float]]:
    rows = _read_log()

    all_time = rows
    weekly = [r for r in rows if r.get("record_type") == "pick" and _in_current_week_local(r.get("created_at"))]
    yesterday = [r for r in rows if r.get("record_type") == "pick" and _in_yesterday_local(r.get("created_at"))]

    return {
        "all_time": _summarize(all_time),
        "weekly": _summarize(weekly),
        "yesterday": _summarize(yesterday),
    }


def _bucket_edge(prob_edge: float) -> str:
    if prob_edge is None:
        return "unknown"
    if prob_edge < 0.01:
        return "<1pp"
    if prob_edge < 0.02:
        return "1-2pp"
    if prob_edge < 0.04:
        return "2-4pp"
    return ">=4pp"


def _bucket_model_rank(rank):
    if rank is None:
        return "none"
    try:
        r = int(rank)
    except (TypeError, ValueError):
        return "none"
    if r <= 3:
        return "1-3"
    if r <= 6:
        return "4-6"
    if r <= 10:
        return "7-10"
    return "11+"


def performance_diagnostics() -> Dict[str, dict]:
    rows = _read_log()
    picks = [r for r in rows if r.get("record_type") == "pick"]
    graded = [r for r in picks if r.get("graded") and r.get("result") in {"win", "loss"}]

    by_sport = {}
    for row in graded:
        sport = row.get("sport", "unknown")
        by_sport.setdefault(
            sport,
            {"count": 0, "brier_sum": 0.0, "logloss_sum": 0.0, "units": 0.0, "graded": 0},
        )

        y = 1.0 if row.get("result") == "win" else 0.0
        p = row.get("final_prob")
        if p is None:
            p = row.get("true_prob")
        if p is None:
            p = row.get("implied_prob", 0.5)

        try:
            p = float(p)
        except (TypeError, ValueError):
            p = 0.5

        p = max(1e-6, min(1 - 1e-6, p))
        brier = (p - y) ** 2
        logloss = -(y * math.log(p) + (1 - y) * math.log(1 - p))

        by_sport[sport]["count"] += 1
        by_sport[sport]["brier_sum"] += brier
        by_sport[sport]["logloss_sum"] += logloss
        by_sport[sport]["units"] += float(row.get("units") or 0.0)
        by_sport[sport]["graded"] += 1

    sport_metrics = {}
    for sport, s in by_sport.items():
        c = max(1, s["count"])
        sport_metrics[sport] = {
            "graded": s["graded"],
            "avg_brier": round(s["brier_sum"] / c, 4),
            "avg_logloss": round(s["logloss_sum"] / c, 4),
            "units": round(s["units"], 3),
            "roi_pct": round((s["units"] / s["graded"] * 100.0) if s["graded"] else 0.0, 2),
        }

    edge_buckets = {}
    rank_buckets = {}
    for row in graded:
        edge_bucket = _bucket_edge(row.get("probability_edge"))
        rank_bucket = _bucket_model_rank(row.get("model_rank"))
        for buckets, key in ((edge_buckets, edge_bucket), (rank_buckets, rank_bucket)):
            buckets.setdefault(key, {"graded": 0, "units": 0.0})
            buckets[key]["graded"] += 1
            buckets[key]["units"] += float(row.get("units") or 0.0)

    def _finalize_bucket(src):
        out = {}
        for key, val in src.items():
            g = val["graded"]
            u = val["units"]
            out[key] = {
                "graded": g,
                "units": round(u, 3),
                "roi_pct": round((u / g * 100.0) if g else 0.0, 2),
            }
        return out

    clv_rows = [r for r in picks if r.get("clv") is not None]
    avg_clv = None
    if clv_rows:
        avg_clv = round(sum(float(r.get("clv") or 0.0) for r in clv_rows) / len(clv_rows), 4)

    return {
        "sports": sport_metrics,
        "roi_by_edge_bucket": _finalize_bucket(edge_buckets),
        "roi_by_model_rank_bucket": _finalize_bucket(rank_buckets),
        "clv": {
            "available": len(clv_rows),
            "total_picks": len(picks),
            "avg_clv": avg_clv,
        },
    }


def format_diagnostics_report(diag: Dict[str, dict]) -> str:
    lines = []
    lines.append("Sports")
    lines.append("sport                 graded  brier   logloss  units    roi%")
    for sport, row in sorted(diag.get("sports", {}).items()):
        lines.append(
            f"{sport:20s} {row.get('graded', 0):6d}  {row.get('avg_brier', 0):6.4f}  "
            f"{row.get('avg_logloss', 0):7.4f}  {row.get('units', 0):7.3f}  {row.get('roi_pct', 0):6.2f}"
        )

    lines.append("")
    lines.append("ROI by Edge Bucket")
    lines.append("bucket     graded  units    roi%")
    for bucket, row in sorted(diag.get("roi_by_edge_bucket", {}).items()):
        lines.append(
            f"{bucket:9s} {row.get('graded', 0):6d}  {row.get('units', 0):7.3f}  {row.get('roi_pct', 0):6.2f}"
        )

    lines.append("")
    lines.append("ROI by Model Rank Bucket")
    lines.append("bucket     graded  units    roi%")
    for bucket, row in sorted(diag.get("roi_by_model_rank_bucket", {}).items()):
        lines.append(
            f"{bucket:9s} {row.get('graded', 0):6d}  {row.get('units', 0):7.3f}  {row.get('roi_pct', 0):6.2f}"
        )

    clv = diag.get("clv", {})
    lines.append("")
    lines.append(
        f"CLV: available={clv.get('available', 0)} / total={clv.get('total_picks', 0)} | "
        f"avg_clv={clv.get('avg_clv')}"
    )

    return "\n".join(lines)


def ingest_provisional_lines(lines: List[str]):
    """Store pasted console lines as provisional picks for manual review/scoring."""
    if not lines:
        return 0

    rows = _read_log()
    created = 0
    for line in lines:
        line = line.strip()
        if not line:
            continue
        rows.append(
            {
                "record_type": "provisional_note",
                "created_at": _now_utc_iso(),
                "line": line,
                "confidence": "low",
            }
        )
        created += 1

    _write_log(rows)
    return created
