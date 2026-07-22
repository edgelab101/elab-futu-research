#!/usr/bin/env python3
"""Offline end-to-end tests with fictional Futu-shaped fixtures."""

from __future__ import annotations

import argparse
import importlib.util
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "elab-futu-research" / "scripts" / "futu_research.py"
FIXTURE = ROOT / "tests" / "fixtures" / "synthetic_api.json"
SPEC = importlib.util.spec_from_file_location("futu_research", SCRIPT)
assert SPEC and SPEC.loader
FR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(FR)


class PipelineTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))

    def fake_request_json(self, url, params=None, attempts=4):
        params = params or {}
        if url == FR.LIST_URL:
            stream = str(params["type"])
            page = "first" if int(params["load_list_type"]) == 2 else "next"
            return self.fixture["list_pages"][f"{stream}:{page}"]
        if url == FR.DETAIL_URL:
            return self.fixture["details"][str(params["feedId"])]
        raise AssertionError(f"Unexpected URL in offline test: {url}")

    @staticmethod
    def synthetic_bars():
        start = datetime(2024, 12, 1, tzinfo=timezone.utc)
        rows = []
        for index in range(260):
            stamp = start + timedelta(days=index)
            price = 80.0 + index * 0.2
            rows.append(
                {
                    "date": stamp.date().isoformat(),
                    "timestamp": int(stamp.timestamp()),
                    "open": price,
                    "high": price * 1.02,
                    "low": price * 0.98,
                    "close": price * 1.005,
                    "volume": 1000.0 + index,
                }
            )
        return rows

    def test_parse_uid(self):
        uid = self.fixture["uid"]
        self.assertEqual(FR.parse_uid(uid), uid)
        self.assertEqual(FR.parse_uid(f"https://q.futunn.com/profile/{uid}?lang=zh-cn"), uid)
        with self.assertRaises(FR.ResearchError):
            FR.parse_uid("not-a-profile")

    def test_offline_end_to_end(self):
        uid = self.fixture["uid"]
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "research-output"
            archive_args = argparse.Namespace(
                profile=[f"https://q.futunn.com/profile/{uid}"],
                since=None,
                until=None,
                output=str(output),
                skip_media=True,
                detail_workers=2,
                media_workers=2,
                max_pages=20,
                refresh=False,
            )
            with mock.patch.object(FR, "request_json", side_effect=self.fake_request_json):
                crawl = FR.archive(archive_args)
            self.assertEqual(crawl["status"], "PASS")
            self.assertEqual(crawl["visible_history_status"], "complete_visible_history")
            posts = FR.read_jsonl(output / "archive" / "posts.jsonl")
            self.assertEqual(len(posts), 3)
            self.assertEqual(sum(bool(row["is_column"]) for row in posts), 1)
            self.assertTrue(any("all" in row["stream_membership"] for row in posts))
            self.assertTrue(any("columns" in row["stream_membership"] for row in posts))

            summary = FR.prepare(argparse.Namespace(output=str(output)))
            self.assertGreaterEqual(summary["candidates"], 3)
            candidates = FR.read_jsonl(output / "analysis" / "candidates.jsonl")
            buy_candidate = next(
                row for row in candidates if row["feed_id"] == "SYNTH-POST-001"
            )
            self.assertEqual(buy_candidate["evidence_prelabel"], "B")
            self.assertEqual(buy_candidate["symbol_raw"], "US.ALPH")

            reviewed = {
                "schema_version": "1.0",
                "claim_id": "SYNTH-CLAIM-001",
                "candidate_id": buy_candidate["candidate_id"],
                "feed_id": buy_candidate["feed_id"],
                "author_uid": uid,
                "published_at": buy_candidate["published_at"],
                "symbol_raw": "US.ALPH",
                "direction": "bullish",
                "action": "buy",
                "horizon": "weeks",
                "evidence_level": "B",
                "evidence_span": buy_candidate["evidence_span"],
                "image_evidence_paths": [],
                "image_evidence_verified": False,
                "conditions": ["跌破计划线"],
                "invalidation": ["跌破计划线"],
                "sizing_rule": "不超过试验账户的一成",
                "risk_rule": "跌破计划线止损",
                "exit_rule": None,
                "confidence": "high",
                "ambiguities": [],
                "reviewer": "human",
                "reviewed_at": datetime.now(timezone.utc).isoformat(),
            }
            FR.write_jsonl(output / "analysis" / "claims.reviewed.jsonl", [reviewed])
            market_args = argparse.Namespace(output=str(output), refresh_market=False)
            with mock.patch.object(
                FR,
                "fetch_price_history",
                return_value=(self.synthetic_bars(), None, "synthetic"),
            ):
                market_summary = FR.market(market_args)
            self.assertEqual(market_summary["mode"], "reviewed")
            self.assertEqual(market_summary["rows_with_forward_20"], 1)

            report_summary = FR.report(argparse.Namespace(output=str(output)))
            self.assertEqual(report_summary["mode"], "reviewed")
            result = FR.audit(argparse.Namespace(output=str(output)))
            self.assertEqual(result["status"], "PASS")
            self.assertTrue(result["publication_gate"]["data_chain_passed"])
            self.assertTrue((output / "reports" / "profile.md").exists())
            self.assertTrue((output / "qa" / "adversarial_audit.json").exists())

    def test_market_time_freeze(self):
        bars = self.synthetic_bars()
        claim = {
            "claim_id": "SYNTH-TIME-001",
            "feed_id": "SYNTH-POST-001",
            "author_uid": self.fixture["uid"],
            "published_at": "2025-05-09T08:00:00+08:00",
            "symbol_raw": "US.ALPH",
            "direction": "bullish",
        }
        row = FR.compute_market_row(claim, "ALPH", bars)
        self.assertLess(row["context_cutoff"], "2025-05-09")
        self.assertGreater(row["evaluation_open_date"], "2025-05-09")
        self.assertIsNotNone(row["ret_20"])
        self.assertEqual(row["directional_ret_20"], row["ret_20"])
        bearish = dict(claim)
        bearish["claim_id"] = "SYNTH-TIME-002"
        bearish["direction"] = "bearish"
        bearish_row = FR.compute_market_row(bearish, "ALPH", bars)
        self.assertAlmostEqual(
            bearish_row["directional_ret_20"], -bearish_row["ret_20"]
        )
        self.assertGreaterEqual(bearish_row["mfe_20"], 0)
        self.assertLessEqual(bearish_row["mae_20"], 0)

    def test_conservative_prelabels_and_symbol_mapping(self):
        self.assertEqual(FR.yahoo_symbol("HK.00700", {}), "0700.HK")
        self.assertEqual(FR.yahoo_symbol("US.BRK.B", {}), "BRK-B")
        direction, _ = FR.detect_direction("我今天卖出一部分，锁定已有利润。", "sell")
        self.assertEqual(direction, "unclear")
        direction, _ = FR.detect_direction("我开空，因为估值偏高。", "short")
        self.assertEqual(direction, "bearish")
        adjusted = FR.benjamini_hochberg({"a": 0.01, "b": 0.04, "c": 0.20})
        self.assertLessEqual(adjusted["a"], adjusted["b"])
        self.assertLessEqual(adjusted["b"], adjusted["c"])
        eastmoney = {
            "data": {
                "klines": [
                    "2025-01-02,10.0,10.5,10.8,9.9,1000,0,0,0,0,0",
                    "2025-01-03,10.5,10.2,10.7,10.0,1100,0,0,0,0,0"
                ]
            }
        }
        bars = FR.parse_eastmoney_bars(eastmoney)
        self.assertEqual(len(bars), 2)
        self.assertEqual(bars[0]["open"], 10.0)
        self.assertEqual(bars[1]["close"], 10.2)


if __name__ == "__main__":
    unittest.main()
