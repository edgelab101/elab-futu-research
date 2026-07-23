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


    # ------ F5: version ------
    def test_version_string(self):
        """VERSION constant must be bumped to 1.2.0 (F5)."""
        self.assertEqual(FR.VERSION, "1.2.0")

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


    # ------ F1: evidence media mode ------

    def _make_detail(self, feed_id, text, has_image=False, is_repost=False):
        """Helper: build a minimal synthetic detail envelope."""
        module_data_entry: dict = {"data": {"text": text}}
        if has_image:
            module_data_entry["data"]["orgPic"] = {
                "url": f"https://img.example.com/{feed_id}.jpg",
                "width": 800,
                "height": 600,
            }
        detail: dict = {
            "feedCommon": {
                "feedId": feed_id,
                "timestamp": 1746748800,
                "feedType": 3,
            },
            "feedTitle": "",
            "authorInfo": {"userId": "99999", "nickName": "Test"},
            "moduleData": [module_data_entry],
            "count": {"browse": 1, "comment": 0, "share": 0},
        }
        if is_repost:
            detail["feedModel"] = {
                "original": {
                    "richTextItems": [{"type": 0, "text": "Original content"}],
                    "pictureItems": [],
                }
            }
        return {"code": 0, "data": {"data": detail}}

    def test_media_evidence_mode_keyword_match(self):
        """evidence mode: post with evidence keyword gets media job; without keyword gets skip record."""
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "out"
            uid = "99999"
            detail_dir = output / "raw" / "details" / uid
            detail_dir.mkdir(parents=True, exist_ok=True)

            # Post WITH evidence keyword and image
            env1 = self._make_detail("EVID-001", "今天订单成交，买入了$AAPL$。", has_image=True)
            (detail_dir / "EVID-001.json").write_text(json.dumps(env1), encoding="utf-8")

            # Post WITHOUT evidence keyword but has image
            env2 = self._make_detail("EVID-002", "市场行情一般，继续观望。", has_image=True)
            (detail_dir / "EVID-002.json").write_text(json.dumps(env2), encoding="utf-8")

            paths = [detail_dir / "EVID-001.json", detail_dir / "EVID-002.json"]

            with mock.patch.object(
                FR, "request_bytes",
                return_value=(b"\xff\xd8\xff" + b"\x00" * 100, {"content_type": "image/jpeg"}),
            ):
                results = FR.download_media(uid, paths, output, workers=1, media_mode="evidence")

        ok_records = [r for r in results if r.get("feed_id") == "EVID-001" and r.get("status") == "ok"]
        skip_records = [r for r in results if r.get("feed_id") == "EVID-002" and r.get("status") == "skipped"]

        self.assertTrue(len(ok_records) > 0, "post with evidence keyword must have ok download record")
        self.assertTrue(len(skip_records) > 0, "post without evidence keyword must have skip record")
        self.assertIn("mode=evidence", skip_records[0].get("skip_reason", ""),
                      "skip_reason must indicate evidence mode")
        self.assertIn("matched=False", skip_records[0].get("skip_reason", ""))

    def test_media_evidence_mode_repost_skipped(self):
        """evidence mode: repost posts are always skipped even if text matches keywords."""
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "out"
            uid = "99999"
            detail_dir = output / "raw" / "details" / uid
            detail_dir.mkdir(parents=True, exist_ok=True)

            # Repost WITH evidence keyword
            env = self._make_detail("EVID-RPOST", "订单成交，看这个转发。", has_image=True, is_repost=True)
            (detail_dir / "EVID-RPOST.json").write_text(json.dumps(env), encoding="utf-8")

            results = FR.download_media(uid, [detail_dir / "EVID-RPOST.json"], output, workers=1, media_mode="evidence")

        skip_records = [r for r in results if r.get("status") == "skipped"]
        self.assertTrue(len(skip_records) > 0, "repost must be skipped in evidence mode")
        self.assertIn("is_repost", skip_records[0].get("skip_reason", ""))

    def test_skip_media_alias_equals_none(self):
        """--skip-media backward-compat: resolves to media_mode='none' in archive."""
        uid = self.fixture["uid"]
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "out"
            archive_args = argparse.Namespace(
                profile=[uid],
                since=None,
                until=None,
                output=str(output),
                skip_media=True,   # old alias
                # no 'media' attribute → getattr default 'all' → alias kicks in
                detail_workers=2,
                media_workers=2,
                max_pages=20,
                refresh=False,
            )
            with mock.patch.object(FR, "request_json", side_effect=self.fake_request_json):
                crawl = FR.archive(archive_args)
        self.assertEqual(crawl.get("media_mode"), "none",
                         "--skip-media alias must resolve media_mode to 'none'")
        self.assertTrue(crawl.get("skip_media"),
                        "backward-compat skip_media field must be True when mode is none")

    def test_media_mode_explicit_none(self):
        """--media=none must set media_mode='none' in crawl audit."""
        uid = self.fixture["uid"]
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "out"
            archive_args = argparse.Namespace(
                profile=[uid],
                since=None,
                until=None,
                output=str(output),
                skip_media=False,
                media="none",
                detail_workers=2,
                media_workers=2,
                max_pages=20,
                refresh=False,
            )
            with mock.patch.object(FR, "request_json", side_effect=self.fake_request_json):
                crawl = FR.archive(archive_args)
        self.assertEqual(crawl.get("media_mode"), "none")

    # ------ F2: self-repost dedup and cross-blogger same-post ------

    def test_cross_blogger_same_feed_not_deduped(self):
        """Two bloggers having a post with the same feed_id must produce two separate records.

        The index key is (uid, feed_id) so different uids are different keys.
        This test walks the full archive() path — no algorithm copied into the test body.
        """
        uid_a = "22222222222222222222"  # must be numeric for parse_uid
        uid_b = "33333333333333333333"
        shared_feed_id = "CROSS-FEED-001"

        def fake_rj_cross(url, params=None, attempts=4):
            params = params or {}
            if url == FR.LIST_URL:
                stream_type = int(params.get("type", 0))
                load_type = int(params.get("load_list_type", 1))
                # Only return the shared feed in "all" stream (type 301), not in "columns" (302).
                # This ensures each uid sees the feed in exactly one stream → self_repost=False.
                if load_type == 2 and stream_type == 301:
                    return {
                        "result": 0,
                        "feed": [{"feed_comm": {"feed_id": shared_feed_id, "timestamp": 1746748800}}],
                        "has_more": 0, "more_mark": "", "sequence": "",
                    }
                return {"result": 0, "feed": [], "has_more": 0, "more_mark": "", "sequence": ""}
            if url == FR.DETAIL_URL:
                # Return a post attributed to the blogger whose uid is in the target_uid param
                # (Futu returns author info in authorInfo)
                target = str(params.get("feedId") or "")
                return {
                    "code": 0,
                    "data": {"data": {
                        "feedCommon": {"feedId": shared_feed_id, "timestamp": 1746748800, "feedType": 3,
                                       "dynamicDescription": {"stringSc": "发表了"}},
                        "feedTitle": "Cross-blogger post",
                        "authorInfo": {"userId": "SOME-AUTHOR", "nickName": "Author"},
                        "moduleData": [{"data": {"text": "Content."}}],
                        "count": {"browse": 1, "comment": 0, "share": 0},
                    }}
                }
            return {"code": 0}

        with tempfile.TemporaryDirectory() as tmp:
            archive_args = argparse.Namespace(
                profile=[uid_a, uid_b], since=None, until=None, output=tmp,
                skip_media=True, detail_workers=2, media_workers=2,
                max_pages=20, refresh=False,
            )
            with mock.patch.object(FR, "request_json", side_effect=fake_rj_cross):
                FR.archive(archive_args)
            posts = FR.read_jsonl(Path(tmp) / "archive" / "posts.jsonl")

        # Two different uids with same feed_id → two different index keys → two records
        records_with_feed = [p for p in posts if p.get("feed_id") == shared_feed_id]
        self.assertEqual(len(records_with_feed), 2,
                         "different uids with same feed_id must produce two separate records")
        # self_reposted machinery was removed in v1.2.0; the field must not reappear
        for rec in records_with_feed:
            self.assertNotIn("self_reposted", rec,
                             "self_reposted field was removed and must not reappear in archive output")

    def test_audit_uniqueness_cross_blogger_passes(self):
        """Audit normalized_feed_ids_unique must PASS for two bloggers sharing a feed_id.

        The audit checks (profile_uid, feed_id) pairs, not bare feed_ids.
        This test runs the full audit() path against a crafted posts.jsonl.
        """
        uid_a = "44444444444444444444"  # numeric for parse_uid (audit reads posts.jsonl directly)
        uid_b = "55555555555555555555"
        shared_feed_id = "AUD-CROSS-001"

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            # Create minimal crawl_audit.json that audit() needs
            crawl_audit = {
                "schema_version": "1.0",
                "status": "PASS",
                "visible_history_status": "complete_visible_history",
                "captured_at": "2026-07-23T00:00:00+00:00",
                "requested_since": None,
                "requested_until": None,
                "profiles": [
                    {"uid": uid_a, "profile_url": f"https://q.futunn.com/profile/{uid_a}"},
                    {"uid": uid_b, "profile_url": f"https://q.futunn.com/profile/{uid_b}"},
                ],
                "streams": [
                    {"profile_uid": uid_a, "stream": "all", "complete_for_request": True,
                     "terminal_reason": "has_more_zero"},
                    {"profile_uid": uid_a, "stream": "columns", "complete_for_request": True,
                     "terminal_reason": "has_more_zero"},
                    {"profile_uid": uid_b, "stream": "all", "complete_for_request": True,
                     "terminal_reason": "has_more_zero"},
                    {"profile_uid": uid_b, "stream": "columns", "complete_for_request": True,
                     "terminal_reason": "has_more_zero"},
                ],
                "detail_expected": 2,
                "detail_successes": 2,
                "detail_failures": [],
                "normalization_failures": [],
                "normalized_records": 2,
                "media_mode": "none",
                "skip_media": True,
                "posts_with_image_content": 0,
                "media_objects": 0,
                "media_failures": [],
                "notes": [],
            }
            (output / "qa").mkdir(parents=True, exist_ok=True)
            FR.atomic_write_json(output / "qa" / "crawl_audit.json", crawl_audit)

            # Two records with same feed_id but different profile_uid (cross-blogger)
            (output / "archive").mkdir(parents=True, exist_ok=True)
            for uid in (uid_a, uid_b):
                detail_dir = output / "raw" / "details" / uid
                detail_dir.mkdir(parents=True, exist_ok=True)
                detail_path = detail_dir / f"{shared_feed_id}.json"
                detail_path.write_text(
                    json.dumps({"code": 0, "data": {"data": {
                        "feedCommon": {"feedId": shared_feed_id}
                    }}}),
                    encoding="utf-8",
                )
            FR.write_jsonl(output / "archive" / "posts.jsonl", [
                {
                    "profile_uid": uid_a, "feed_id": shared_feed_id,
                    "is_repost": False, "stream_membership": ["all"],
                    "source": {"detail_path": str(
                        output / "raw" / "details" / uid_a / f"{shared_feed_id}.json"
                    )},
                },
                {
                    "profile_uid": uid_b, "feed_id": shared_feed_id,
                    "is_repost": False, "stream_membership": ["all"],
                    "source": {"detail_path": str(
                        output / "raw" / "details" / uid_b / f"{shared_feed_id}.json"
                    )},
                },
            ])

            result = FR.audit(argparse.Namespace(output=str(output)))

        uniqueness_check = next(
            (c for c in result["checks"] if c["name"] == "normalized_feed_ids_unique"), None
        )
        self.assertIsNotNone(uniqueness_check)
        self.assertTrue(
            uniqueness_check["passed"],
            "cross-blogger same feed_id must PASS uniqueness check "
            "(audit uses (profile_uid, feed_id) pairs)",
        )

    def test_empty_origin_shell_not_repost(self):
        """Origin dict with empty richTextItems and pictureItems must not classify post as repost."""
        empty_origin = {"richTextItems": [], "pictureItems": [], "url": "https://example.com"}
        self.assertFalse(
            FR._has_repost_content(empty_origin),
            "empty richTextItems+pictureItems must not be treated as repost content",
        )
        non_empty_origin = {"richTextItems": [{"text": "hello"}], "pictureItems": []}
        self.assertTrue(
            FR._has_repost_content(non_empty_origin),
            "non-empty richTextItems must be treated as repost content",
        )

    def test_skip_media_and_media_evidence_both_given_warns_stderr(self):
        """When --skip-media and --media=evidence are both given, --media wins and a warning is printed.

        Reviewer optional #3: verify the stderr warning path is exercised.
        """
        uid = self.fixture["uid"]

        def fake_rj(url, params=None, attempts=4):
            params = params or {}
            if url == FR.LIST_URL:
                load_type = int(params.get("load_list_type", 1))
                if load_type == 2:
                    return {
                        "result": 0, "feed": [], "has_more": 0,
                        "more_mark": "", "sequence": "",
                    }
                return {"result": 0, "feed": [], "has_more": 0, "more_mark": "", "sequence": ""}
            return {"code": 0}

        with tempfile.TemporaryDirectory() as tmp:
            archive_args = argparse.Namespace(
                profile=[uid], since=None, until=None, output=tmp,
                skip_media=True,   # backward-compat alias
                media="evidence",  # explicit --media wins
                detail_workers=2, media_workers=2,
                max_pages=20, refresh=False,
            )
            import sys
            stderr_capture = io.StringIO()
            with mock.patch.object(FR, "request_json", side_effect=fake_rj):
                with mock.patch("sys.stderr", stderr_capture):
                    crawl = FR.archive(archive_args)

        warning_text = stderr_capture.getvalue()
        self.assertIn("--skip-media", warning_text,
                      "stderr must mention --skip-media")
        self.assertIn("evidence", warning_text,
                      "stderr must mention the winning --media=evidence value")
        # --media wins: effective mode must be 'evidence', not 'none'
        self.assertEqual(crawl.get("media_mode"), "evidence",
                         "--media=evidence must win over --skip-media alias")

    # ------ F3: tripwire uses posts_with_image_content ------

    def test_tripwire_pure_text_blogger_no_false_alarm(self):
        """Tripwire must NOT fire when posts_with_image_content=0 (pure-text archive)."""
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "out"
            uid = self.fixture["uid"]
            # Crawl audit simulates a pure-text blogger run
            crawl_audit = {
                "schema_version": "1.0",
                "status": "PASS",
                "visible_history_status": "complete_visible_history",
                "captured_at": "2026-07-22T00:00:00+00:00",
                "requested_since": None,
                "requested_until": None,
                "profiles": [{"uid": uid, "profile_url": f"https://q.futunn.com/profile/{uid}"}],
                "streams": [
                    {"profile_uid": uid, "stream": "all", "complete_for_request": True,
                     "terminal_reason": "has_more_zero"},
                    {"profile_uid": uid, "stream": "columns", "complete_for_request": True,
                     "terminal_reason": "has_more_zero"},
                ],
                "detail_expected": 1,
                "detail_successes": 1,
                "detail_failures": [],
                "normalization_failures": [],
                "normalized_records": 1,
                "media_mode": "all",
                "skip_media": False,
                "posts_with_image_content": 0,  # <-- pure-text blogger
                "media_objects": 0,  # no media downloaded (no images to get)
                "media_failures": [],
                "notes": [],
            }
            (output / "qa").mkdir(parents=True, exist_ok=True)
            FR.atomic_write_json(output / "qa" / "crawl_audit.json", crawl_audit)
            # Also need a posts.jsonl for audit to read
            (output / "archive").mkdir(parents=True, exist_ok=True)
            FR.write_jsonl(output / "archive" / "posts.jsonl", [{
                "feed_id": "TEXT-001",
                "profile_uid": uid,
                "source": {"detail_path": str(output / "raw" / "details" / uid / "TEXT-001.json")},
            }])
            # Create dummy detail file so source trace check passes
            detail_dir = output / "raw" / "details" / uid
            detail_dir.mkdir(parents=True, exist_ok=True)
            (detail_dir / "TEXT-001.json").write_text(
                json.dumps({"code": 0, "data": {"data": {"feedCommon": {"feedId": "TEXT-001"}}}}),
                encoding="utf-8",
            )
            result = FR.audit(argparse.Namespace(output=str(output)))

        tripwire_check = next(
            (c for c in result["checks"] if c["name"] == "media_extraction_not_zero_jobs"), None
        )
        self.assertIsNotNone(tripwire_check)
        self.assertTrue(
            tripwire_check["passed"],
            "tripwire must PASS for pure-text archive (posts_with_image_content=0)",
        )
        self.assertIn("N/A", str(tripwire_check.get("detail", "")),
                      "tripwire detail must say N/A for zero-image archive")

    def test_tripwire_image_posts_zero_downloads_fires(self):
        """Tripwire must WARN when posts_with_image_content > 0 but media_objects=0."""
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "out"
            uid = self.fixture["uid"]
            crawl_audit = {
                "schema_version": "1.0",
                "status": "PASS",
                "visible_history_status": "complete_visible_history",
                "captured_at": "2026-07-22T00:00:00+00:00",
                "requested_since": None,
                "requested_until": None,
                "profiles": [{"uid": uid, "profile_url": f"https://q.futunn.com/profile/{uid}"}],
                "streams": [
                    {"profile_uid": uid, "stream": "all", "complete_for_request": True,
                     "terminal_reason": "has_more_zero"},
                    {"profile_uid": uid, "stream": "columns", "complete_for_request": True,
                     "terminal_reason": "has_more_zero"},
                ],
                "detail_expected": 1,
                "detail_successes": 1,
                "detail_failures": [],
                "normalization_failures": [],
                "normalized_records": 1,
                "media_mode": "all",
                "skip_media": False,
                "posts_with_image_content": 3,  # <-- has images in source
                "media_objects": 0,            # <-- but zero downloaded → regression
                "media_failures": [],
                "notes": [],
            }
            (output / "qa").mkdir(parents=True, exist_ok=True)
            FR.atomic_write_json(output / "qa" / "crawl_audit.json", crawl_audit)
            (output / "archive").mkdir(parents=True, exist_ok=True)
            FR.write_jsonl(output / "archive" / "posts.jsonl", [{
                "feed_id": "IMG-001",
                "profile_uid": uid,
                "source": {"detail_path": str(output / "raw" / "details" / uid / "IMG-001.json")},
            }])
            detail_dir = output / "raw" / "details" / uid
            detail_dir.mkdir(parents=True, exist_ok=True)
            (detail_dir / "IMG-001.json").write_text(
                json.dumps({"code": 0, "data": {"data": {"feedCommon": {"feedId": "IMG-001"}}}}),
                encoding="utf-8",
            )
            result = FR.audit(argparse.Namespace(output=str(output)))

        tripwire_check = next(
            (c for c in result["checks"] if c["name"] == "media_extraction_not_zero_jobs"), None
        )
        self.assertIsNotNone(tripwire_check)
        self.assertFalse(
            tripwire_check["passed"],
            "tripwire must WARN when image posts exist but media_objects=0",
        )

    def test_tripwire_none_mode_skipped(self):
        """Tripwire must PASS (info) when media_mode='none' regardless of post count."""
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "out"
            uid = self.fixture["uid"]
            crawl_audit = {
                "schema_version": "1.0",
                "status": "PASS",
                "visible_history_status": "complete_visible_history",
                "captured_at": "2026-07-22T00:00:00+00:00",
                "requested_since": None,
                "requested_until": None,
                "profiles": [{"uid": uid, "profile_url": f"https://q.futunn.com/profile/{uid}"}],
                "streams": [
                    {"profile_uid": uid, "stream": "all", "complete_for_request": True,
                     "terminal_reason": "has_more_zero"},
                    {"profile_uid": uid, "stream": "columns", "complete_for_request": True,
                     "terminal_reason": "has_more_zero"},
                ],
                "detail_expected": 4,
                "detail_successes": 4,
                "detail_failures": [],
                "normalization_failures": [],
                "normalized_records": 4,
                "media_mode": "none",
                "skip_media": True,
                "posts_with_image_content": 3,
                "media_objects": 0,
                "media_failures": [],
                "notes": [],
            }
            (output / "qa").mkdir(parents=True, exist_ok=True)
            FR.atomic_write_json(output / "qa" / "crawl_audit.json", crawl_audit)
            (output / "archive").mkdir(parents=True, exist_ok=True)
            FR.write_jsonl(output / "archive" / "posts.jsonl", [{
                "feed_id": "POST-001",
                "profile_uid": uid,
                "source": {"detail_path": str(output / "raw" / "details" / uid / "POST-001.json")},
            }])
            detail_dir = output / "raw" / "details" / uid
            detail_dir.mkdir(parents=True, exist_ok=True)
            (detail_dir / "POST-001.json").write_text(
                json.dumps({"code": 0, "data": {"data": {"feedCommon": {"feedId": "POST-001"}}}}),
                encoding="utf-8",
            )
            result = FR.audit(argparse.Namespace(output=str(output)))

        tripwire_check = next(
            (c for c in result["checks"] if c["name"] == "media_extraction_not_zero_jobs"), None
        )
        self.assertIsNotNone(tripwire_check)
        self.assertTrue(
            tripwire_check["passed"],
            "tripwire must PASS when media_mode=none (skip mode)",
        )
        self.assertIn("none", str(tripwire_check.get("detail", "")))

    # ------ F4: trailing tag block suppression ------

    def test_trailing_tags_three_or_more_downgraded(self):
        """Symbols in trailing block of >= 3 tags not mentioned in body must be downgraded."""
        # 3 trailing tags: TSLA, NVDA, AMD not in body → all trailing-only
        text = "今天市场不错，关注$AAPL$后续走势。\n$TSLA$ $NVDA$ $AMD$"
        trailing = FR._trailing_tag_symbols(text)
        self.assertIn("TSLA", trailing)
        self.assertIn("NVDA", trailing)
        self.assertIn("AMD", trailing)
        self.assertNotIn("AAPL", trailing, "AAPL mentioned in body must not be in trailing set")

    def test_trailing_tags_body_mention_excluded(self):
        """A symbol discussed in the body text must not be downgraded even if also in trailing block."""
        text = "我今天买入$NVDA$，看好其AI路径。\n$TSLA$ $NVDA$ $AMD$"
        trailing = FR._trailing_tag_symbols(text)
        self.assertNotIn("NVDA", trailing, "NVDA mentioned in body must NOT be trailing-only")
        # TSLA and AMD have no body mention
        self.assertIn("TSLA", trailing)
        self.assertIn("AMD", trailing)

    def test_trailing_tags_two_not_triggered(self):
        """Only 2 trailing tags must NOT trigger the block (threshold is >= 3)."""
        text = "关注市场动向。\n$TSLA$ $NVDA$"
        trailing = FR._trailing_tag_symbols(text)
        self.assertEqual(len(trailing), 0, "2-tag trailing block must not be triggered")

    def test_trailing_tags_pure_text_unaffected(self):
        """Text without any $SYMBOL$ pattern must return empty set."""
        text = "今天市场不错，继续持有苹果和特斯拉，等待机会。"
        trailing = FR._trailing_tag_symbols(text)
        self.assertEqual(len(trailing), 0)

    def test_trailing_tags_downgrade_in_prepare(self):
        """prepare() must assign evidence_level=D and action=none to trailing-tag-only symbols."""
        uid = self.fixture["uid"]
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
            # Inject a synthetic post with 4 trailing exposure tags (only AAPL in body)
            def patched_request_json(url, params=None, attempts=4):
                params = params or {}
                if url == FR.LIST_URL:
                    stream = str(params["type"])
                    page = "first" if int(params["load_list_type"]) == 2 else "next"
                    key = f"{stream}:{page}"
                    if key == "301:first":
                        return {
                            "result": 0,
                            "feed": [{"feed_comm": {"feed_id": "TRAIL-001", "timestamp": 1746748800}}],
                            "has_more": 0,
                            "more_mark": "",
                            "sequence": "",
                        }
                    # Remaining pages return empty
                    return {"result": 0, "feed": [], "has_more": 0}
                if url == FR.DETAIL_URL:
                    return {
                        "code": 0,
                        "data": {"data": {
                            "feedCommon": {
                                "feedId": "TRAIL-001",
                                "timestamp": 1746748800,
                                "feedType": 3,
                                "dynamicDescription": {"stringSc": "发表了"},
                            },
                            "feedTitle": "今天买入$AAPL$，看好其AI芯片路线",
                            "authorInfo": {"userId": uid, "nickName": "Test"},
                            "moduleData": [{"data": {
                                "text": "我今天买入了Apple，成本价合理，持仓约两成。\n$TSLA$ $NVDA$ $AMD$ $META$",
                            }}],
                            "count": {"browse": 1, "comment": 0, "share": 0},
                        }}
                    }
                raise AssertionError(f"Unexpected URL: {url}")

            with mock.patch.object(FR, "request_json", side_effect=patched_request_json):
                FR.archive(archive_args)
            FR.prepare(argparse.Namespace(output=str(output)))

            candidates = FR.read_jsonl(output / "analysis" / "candidates.jsonl")

        # Candidates for TSLA/NVDA/AMD/META (trailing tags only) must be D
        trailing_candidates = [
            c for c in candidates
            if c.get("trailing_tag_downgraded") is True
        ]
        non_trailing = [
            c for c in candidates
            if not c.get("trailing_tag_downgraded")
        ]
        self.assertTrue(len(trailing_candidates) >= 3,
                        "At least 3 trailing-tag symbols must be flagged and downgraded")
        for c in trailing_candidates:
            self.assertEqual(c["evidence_prelabel"], "D",
                             f"Trailing symbol {c.get('symbol_raw')} must be downgraded to D")
            self.assertEqual(c["action_prelabel"], "none",
                             f"Trailing symbol {c.get('symbol_raw')} must have action=none")
        # AAPL (in title body) must NOT be downgraded
        aapl_candidates = [c for c in candidates if c.get("symbol_raw") == "AAPL"]
        for c in aapl_candidates:
            self.assertFalse(c.get("trailing_tag_downgraded"),
                             "AAPL in body must NOT be trailing-downgraded")


if __name__ == "__main__":
    unittest.main()
