#!/usr/bin/env python3
"""Offline end-to-end tests with fictional Futu-shaped fixtures."""

from __future__ import annotations

import argparse
import importlib.util
import io
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
            self.assertEqual(len(posts), 4)
            self.assertEqual(sum(bool(row["is_column"]) for row in posts), 1)
            self.assertEqual(sum(bool(row["is_repost"]) for row in posts), 1)
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
            # Verify report footer credit and disclaimer are present in all report files
            for report_name in ("profile.md", "capability_matrix.md", "rule_cards.md"):
                report_text = (output / "reports" / report_name).read_text(encoding="utf-8")
                self.assertIn(
                    "elab-futu-research",
                    report_text,
                    msg=f"footer credit missing from {report_name}",
                )
                self.assertIn(
                    "不构成任何投资建议",
                    report_text,
                    msg=f"disclaimer missing from {report_name}",
                )

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


    def test_repost_attribution(self):
        """Repost posts must set is_repost=True and split own comment from original text."""
        uid = self.fixture["uid"]
        repost_detail = self.fixture["details"]["SYNTH-REPOST-001"]
        with tempfile.TemporaryDirectory() as temporary:
            detail_path = Path(temporary) / "SYNTH-REPOST-001.json"
            detail_path.write_text(
                json.dumps(repost_detail, ensure_ascii=False), encoding="utf-8"
            )
            record = FR.normalize_detail(
                detail_path,
                uid,
                ["all"],
                {},
                f"https://q.futunn.com/profile/{uid}",
            )
        # Core repost flag
        self.assertTrue(record["is_repost"], "Repost detection must set is_repost=True")
        self.assertFalse(record["is_original_author"])
        # Own comment is isolated in text
        self.assertIn(
            "虚构评论：看了一下，有参考价值。",
            record["text"],
            msg="Author's own comment must appear in text",
        )
        # Original post content in original_text, NOT in text
        self.assertIsNotNone(record["original_text"])
        self.assertIn(
            "虚构官方帖",
            record["original_text"],
            msg="Original post text must appear in original_text",
        )
        self.assertNotIn(
            "虚构官方帖",
            record["text"],
            msg="Original post text must NOT bleed into text field",
        )
        # Title uses own comment, not the original post content
        self.assertNotIn(
            "虚构官方帖",
            record["title"],
            msg="Title must not be derived from repost content",
        )


    def test_media_url_extraction(self):
        """extract_media_urls must handle nested orgPic/bigPic/thumbPic dict structure.

        Before v1.1.0 the function checked isinstance(child, str) for URL_MEDIA_KEYS;
        real Futu data wraps image URLs in {url, width, height} dicts so the old code
        produced zero jobs silently.
        """
        # ------------------------------------------------------------------
        # Case 1: full pictureItem with all three quality levels inside _original
        #   Expected: orgPic collected; bigPic skipped (priority); thumbPic skipped always
        # ------------------------------------------------------------------
        detail_full = {
            "moduleData": [
                {
                    "type": 1,
                    "_original": {
                        "stockIds": [],
                        "orgPic": {
                            "url": "https://img.example.com/photo-SYNTH.jpg",
                            "width": 1062,
                            "height": 1530,
                        },
                        "bigPic": {
                            "url": "https://img.example.com/photo-SYNTH.jpg/bigversion",
                            "width": 800,
                            "height": 600,
                        },
                        "thumbPic": {
                            "url": "https://img.example.com/photo-SYNTH.jpg/thumbversion",
                            "width": 200,
                            "height": 150,
                        },
                        "picDescription": "",
                    },
                }
            ]
        }
        urls_full = FR.extract_media_urls(detail_full)
        url_set_full = {item["url"] for item in urls_full}

        self.assertIn(
            "https://img.example.com/photo-SYNTH.jpg",
            url_set_full,
            msg="orgPic (original quality) must be collected from nested dict structure",
        )
        self.assertNotIn(
            "https://img.example.com/photo-SYNTH.jpg/bigversion",
            url_set_full,
            msg="bigPic must be excluded when orgPic is present (priority logic)",
        )
        self.assertNotIn(
            "https://img.example.com/photo-SYNTH.jpg/thumbversion",
            url_set_full,
            msg="thumbPic must never be collected regardless of availability",
        )

        # ------------------------------------------------------------------
        # Case 2: bigPic fallback — orgPic absent; bigPic must be collected
        # ------------------------------------------------------------------
        detail_no_orgpic = {
            "moduleData": [
                {
                    "type": 1,
                    "_original": {
                        "bigPic": {
                            "url": "https://img.example.com/fallback-SYNTH.jpg/bigversion",
                            "width": 800,
                            "height": 600,
                        },
                        "thumbPic": {
                            "url": "https://img.example.com/fallback-SYNTH.jpg/thumbversion",
                            "width": 200,
                            "height": 150,
                        },
                    },
                }
            ]
        }
        urls_fallback = FR.extract_media_urls(detail_no_orgpic)
        url_set_fallback = {item["url"] for item in urls_fallback}

        self.assertIn(
            "https://img.example.com/fallback-SYNTH.jpg/bigversion",
            url_set_fallback,
            msg="bigPic must be collected as fallback when orgPic is absent",
        )
        self.assertNotIn(
            "https://img.example.com/fallback-SYNTH.jpg/thumbversion",
            url_set_fallback,
            msg="thumbPic must not be collected even as last-resort fallback",
        )

        # ------------------------------------------------------------------
        # Case 3: dict-valued display / preview keys at module level
        #   Verifies the elif normalized in URL_MEDIA_KEYS and isinstance(child, dict) branch
        # ------------------------------------------------------------------
        detail_display = {
            "moduleData": [
                {
                    "type": 1,
                    "display": {
                        "url": "https://img.example.com/display-SYNTH.jpg",
                        "width": 392,
                        "height": 225,
                    },
                }
            ]
        }
        urls_display = FR.extract_media_urls(detail_display)
        url_set_display = {item["url"] for item in urls_display}

        self.assertIn(
            "https://img.example.com/display-SYNTH.jpg",
            url_set_display,
            msg="dict-valued display key must be collected via .url extraction",
        )


    # ------ F9: version ------
    def test_version_string(self):
        """VERSION constant must be bumped to 1.1.2 (F9)."""
        self.assertEqual(FR.VERSION, "1.1.2")

    # ------ F1: OSError in main exits 2 cleanly ------
    def test_output_file_path_exits_cleanly(self):
        """When --output points to an existing file, exit 2 with ERROR, no traceback (F1)."""
        with tempfile.NamedTemporaryFile() as tmp_file:
            with mock.patch("sys.stderr", new_callable=io.StringIO) as mock_err:
                result = FR.main(
                    ["archive", "--profile", "12345",
                     "--since", "2026-07-22",
                     "--output", tmp_file.name]
                )
            err_text = mock_err.getvalue()
        self.assertEqual(result, 2, "exit code must be 2 for OSError")
        self.assertIn("ERROR", err_text, "stderr must contain ERROR prefix")
        self.assertNotIn("Traceback", err_text, "raw traceback must not appear in stderr")

    # ------ F2: zero posts note ------
    def test_archive_zero_posts_note(self):
        """Archive with 0 posts must log a note suggesting UID verification (F2)."""
        uid = "99999999"
        _empty_audit = {
            "profile_uid": uid,
            "stream": "all",
            "feed_type": 301,
            "pages_saved": 1,
            "unique_feed_ids": 0,
            "terminal_reason": "has_more_zero",
            "complete_for_request": True,
            "pages": [],
            "errors": [],
        }
        _empty_audit2 = dict(_empty_audit, stream="columns", feed_type=302)
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "out"
            archive_args = argparse.Namespace(
                profile=[uid],
                since=None,
                until=None,
                output=str(output),
                skip_media=True,
                detail_workers=2,
                media_workers=2,
                max_pages=20,
                refresh=False,
            )
            with mock.patch.object(FR, "crawl_stream",
                                   side_effect=[({}, _empty_audit), ({}, _empty_audit2)]):
                with mock.patch("sys.stdout", new_callable=io.StringIO) as mock_out:
                    FR.archive(archive_args)
                stdout_text = mock_out.getvalue()
        self.assertIn("0 posts returned", stdout_text,
                      "zero-posts note must appear in stdout when posts==0")
        self.assertIn("verify the uid", stdout_text.lower(),
                      "note must suggest UID verification")

    # ------ F3: doctor PARTIAL without profile ------
    def test_doctor_partial_without_profile(self):
        """doctor without --profile must report PARTIAL status (F3)."""
        args = argparse.Namespace(output=None, profile=None)
        with mock.patch("sys.stdout", new_callable=io.StringIO):
            result = FR.doctor(args)
        self.assertEqual(result["status"], "PARTIAL",
                         "doctor without profile must return PARTIAL, not PASS")
        self.assertIn("note", result, "PARTIAL result must include a note field")

    # ------ F4: ZoneInfo fallback ------
    def test_zoneinfo_fallback(self):
        """_resolve_cn_tz must fall back to UTC+8 when ZoneInfo is unavailable (F4)."""
        import datetime as _dt
        # Setting sys.modules["zoneinfo"] = None causes ImportError on 'from zoneinfo import ...'
        with mock.patch.dict("sys.modules", {"zoneinfo": None}):
            tz = FR._resolve_cn_tz()
        dt = _dt.datetime(2025, 6, 15, 12, 0, tzinfo=tz)
        self.assertEqual(dt.utcoffset(), _dt.timedelta(hours=8),
                         "fallback timezone must be exactly UTC+8")

    # ------ F5: bare 5-digit HK code ------
    def test_hk_bare_5digit_symbol_mapping(self):
        """Bare 5-digit numeric symbol maps same as HK.-prefixed form (F5)."""
        # 5-digit bare HK code must equal HK.-prefixed mapping
        self.assertEqual(
            FR.yahoo_symbol("07709", {}),
            FR.yahoo_symbol("HK.07709", {}),
            "yahoo_symbol('07709') must equal yahoo_symbol('HK.07709')",
        )
        # 6-digit (A-share territory like SK Hynix) must not be treated as HK
        self.assertIsNone(
            FR.yahoo_symbol("000660", {}),
            "6-digit numeric must not be mapped as HK code",
        )
        # 3-digit must not trigger HK rule
        self.assertIsNone(
            FR.yahoo_symbol("700", {}),
            "3-digit numeric must not be mapped as HK code",
        )

    # ------ F6: footer brand ------
    def test_report_footer_edgelab_credit(self):
        """REPORT_FOOTER must include EdgeLab brand credit (F6)."""
        self.assertIn(
            "杰尼马（EdgeLab）",
            FR.REPORT_FOOTER,
            "REPORT_FOOTER must contain '杰尼马（EdgeLab）'",
        )

    # ------ F7: empty directory guidance ------
    def test_empty_dir_report_exits_cleanly(self):
        """report on empty dir must exit 2 with archive guidance (F7)."""
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch("sys.stderr", new_callable=io.StringIO) as mock_err:
                result = FR.main(["report", "--output", tmp])
            err_text = mock_err.getvalue()
        self.assertEqual(result, 2, "report on empty dir must exit 2")
        self.assertIn("archive", err_text.lower(),
                      "error message must mention 'archive'")

    def test_empty_dir_market_exits_cleanly(self):
        """market on empty dir must exit 2 mentioning both archive and prepare (F7)."""
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch("sys.stderr", new_callable=io.StringIO) as mock_err:
                result = FR.main(["market", "--output", tmp])
            err_text = mock_err.getvalue()
        self.assertEqual(result, 2, "market on empty dir must exit 2")
        self.assertIn("archive", err_text.lower(),
                      "error message must mention 'archive'")
        self.assertIn("prepare", err_text.lower(),
                      "error message must mention 'prepare' (candidates.jsonl is prepare output)")

    def test_empty_dir_audit_exits_cleanly(self):
        """audit on empty dir must exit 2 with archive guidance (F7)."""
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch("sys.stderr", new_callable=io.StringIO) as mock_err:
                result = FR.main(["audit", "--output", tmp])
            err_text = mock_err.getvalue()
        self.assertEqual(result, 2, "audit on empty dir must exit 2")
        self.assertIn("archive", err_text.lower(),
                      "error message must mention 'archive'")


if __name__ == "__main__":
    unittest.main()
