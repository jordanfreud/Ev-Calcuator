import unittest
from datetime import datetime, timedelta, timezone

from config import MAX_LOOKAHEAD_HOURS
from main import _is_real_matchup, _normalize_book_name, _pick_best_per_game
from probability import calibrated_hybrid_probability
from bet_tracker import calculate_clv_from_odds, format_diagnostics_report


class PipelineTests(unittest.TestCase):
    def _base_game(self):
        start = datetime.now(timezone.utc) + timedelta(hours=2)
        return {
            "id": "evt_1",
            "commence_time": start.isoformat().replace("+00:00", "Z"),
            "bookmakers": [{"title": "A"}, {"title": "B"}, {"title": "C"}],
        }

    def test_normalize_book_name(self):
        self.assertEqual(_normalize_book_name("Draft Kings"), "draftkings")
        self.assertEqual(_normalize_book_name("FanDuel"), "fanduel")
        self.assertEqual(_normalize_book_name("Caesars (US)"), "caesarsus")

    def test_real_matchup_valid(self):
        self.assertTrue(_is_real_matchup(self._base_game()))

    def test_real_matchup_requires_id(self):
        game = self._base_game()
        game["id"] = None
        self.assertFalse(_is_real_matchup(game))

    def test_real_matchup_lookahead_filter(self):
        game = self._base_game()
        far_start = datetime.now(timezone.utc) + timedelta(hours=MAX_LOOKAHEAD_HOURS + 1)
        game["commence_time"] = far_start.isoformat().replace("+00:00", "Z")
        self.assertFalse(_is_real_matchup(game))

    def test_real_matchup_min_books(self):
        game = self._base_game()
        game["bookmakers"] = [{"title": "A"}, {"title": "B"}]
        self.assertFalse(_is_real_matchup(game))

    def test_one_pick_per_game_keeps_max_ev(self):
        picks = [
            {"event_id": "e1", "ev": 0.01, "team": "A"},
            {"event_id": "e1", "ev": 0.04, "team": "B"},
            {"event_id": "e2", "ev": 0.03, "team": "C"},
        ]
        result = _pick_best_per_game(picks)
        by_event = {r["event_id"]: r for r in result}
        self.assertEqual(len(result), 2)
        self.assertEqual(by_event["e1"]["team"], "B")
        self.assertEqual(by_event["e2"]["team"], "C")

    def test_calibrated_hybrid_probability_uses_model_when_available(self):
        (away, home), comps = calibrated_hybrid_probability(
            market_prob_pair=(0.45, 0.55),
            model_prob_pair=(0.60, 0.40),
            line_signal=0.05,
            market_weight=0.6,
            model_weight=0.3,
            line_weight=0.1,
            calibration_shrink=0.0,
        )
        self.assertAlmostEqual(away + home, 1.0, places=6)
        self.assertGreater(away, 0.50)
        self.assertGreater(comps["line_boost"], 0)

    def test_calibrated_hybrid_shrink_reduces_extremes(self):
        (away_no_shrink, _), _ = calibrated_hybrid_probability(
            market_prob_pair=(0.9, 0.1),
            model_prob_pair=None,
            line_signal=0.0,
            calibration_shrink=0.0,
        )
        (away_shrink, _), _ = calibrated_hybrid_probability(
            market_prob_pair=(0.9, 0.1),
            model_prob_pair=None,
            line_signal=0.0,
            calibration_shrink=0.1,
        )
        self.assertLess(away_shrink, away_no_shrink)
        self.assertGreater(away_shrink, 0.5)

    def test_clv_from_odds_positive_when_beating_close(self):
        # Example: bet +200, closes +170 -> better entry than close
        clv = calculate_clv_from_odds(200, 170)
        self.assertGreater(clv, 0)

    def test_format_diagnostics_report_has_sections(self):
        diag = {
            "sports": {"baseball_mlb": {"graded": 1, "avg_brier": 0.2, "avg_logloss": 0.5, "units": 1.0, "roi_pct": 100.0}},
            "roi_by_edge_bucket": {"1-2pp": {"graded": 2, "units": 0.5, "roi_pct": 25.0}},
            "roi_by_model_rank_bucket": {"1-3": {"graded": 2, "units": 0.2, "roi_pct": 10.0}},
            "clv": {"available": 1, "total_picks": 2, "avg_clv": 0.01},
        }
        out = format_diagnostics_report(diag)
        self.assertIn("Sports", out)
        self.assertIn("ROI by Edge Bucket", out)
        self.assertIn("CLV:", out)


if __name__ == "__main__":
    unittest.main()
