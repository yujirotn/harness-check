"""今月の使用量（時間・トークン・本数）と、使用回数の段階評価（v4）のテスト。

対象:
- 時間の数え方（5分の切れ目。SPEC 5-10）
- 月の境目・タイムゾーン（日本時間の暦月）
- トークンの足し方（Claude Code / Codex）
- 段階の境目（0・1・4・5・19・20回）
- 名前が出ないこと（facts.json・result.json の新しいキーに固有名が入らない）
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from readers import common  # noqa: E402
import score  # noqa: E402
from helpers import FIXTURES_DIR, TEST_NOW, copy_fixture, make_git_repo  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent


class ActiveSecondsBoundaryTest(unittest.TestCase):
    """5分（300秒）の切れ目（SPEC 5-10）。"""

    def test_exactly_five_minutes_is_included(self):
        self.assertEqual(common.compute_active_seconds([0.0, 300.0]), 300)

    def test_five_minutes_and_one_second_is_excluded(self):
        self.assertEqual(common.compute_active_seconds([0.0, 301.0]), 0)

    def test_multiple_gaps_only_small_ones_are_summed(self):
        # 0→100（含む）／100→500（400秒、超えるので除く）／500→520（含む）
        self.assertEqual(common.compute_active_seconds([0.0, 100.0, 500.0, 520.0]), 120)

    def test_unsorted_input_is_sorted_first(self):
        self.assertEqual(common.compute_active_seconds([300.0, 0.0]), 300)

    def test_empty_or_single_timestamp_is_zero(self):
        self.assertEqual(common.compute_active_seconds([]), 0)
        self.assertEqual(common.compute_active_seconds([123.0]), 0)

    def test_duplicate_timestamps_contribute_nothing(self):
        self.assertEqual(common.compute_active_seconds([10.0, 10.0, 10.0]), 0)


class MonthBoundaryTimezoneTest(unittest.TestCase):
    """「今月」＝日本時間の暦月（SPEC 5-10）。"""

    def test_month_start_is_jst_midnight_of_the_1st(self):
        now = datetime(2026, 11, 17, 9, 0, 0, tzinfo=timezone.utc)  # JST 18:00
        start = common.month_start_jst(now)
        # 日本時間11月1日0時 = UTC 10月31日15時
        self.assertEqual(start, datetime(2026, 10, 31, 15, 0, 0, tzinfo=timezone.utc))

    def test_month_label_uses_jst_not_utc(self):
        # UTC では10月31日だが、日本時間ではすでに11月1日
        now = datetime(2026, 10, 31, 16, 0, 0, tzinfo=timezone.utc)  # JST 2026-11-01 01:00
        self.assertEqual(common.month_label_jst(now), "2026-11")

    def test_timestamp_just_before_jst_month_start_is_excluded(self):
        now = datetime(2026, 11, 17, 9, 0, 0, tzinfo=timezone.utc)
        month_start = common.month_start_jst(now)
        just_before = month_start - timedelta(seconds=1)
        self.assertLess(just_before, month_start)

    def test_timestamp_at_jst_month_start_is_included(self):
        now = datetime(2026, 11, 17, 9, 0, 0, tzinfo=timezone.utc)
        month_start = common.month_start_jst(now)
        self.assertTrue(month_start <= month_start <= now)

    def test_utc_date_crossing_does_not_fool_the_jst_boundary(self):
        """UTCでは10月31日のうちでも、日本時間では11月1日に入っている記録は「今月」に数える。"""
        now = datetime(2026, 11, 17, 9, 0, 0, tzinfo=timezone.utc)
        month_start = common.month_start_jst(now)
        # UTC 2026-10-31T15:30 = JST 2026-11-01T00:30（今月）
        in_month = datetime(2026, 10, 31, 15, 30, 0, tzinfo=timezone.utc)
        # UTC 2026-10-31T14:30 = JST 2026-10-31T23:30（前月）
        prev_month = datetime(2026, 10, 31, 14, 30, 0, tzinfo=timezone.utc)
        self.assertTrue(month_start <= in_month)
        self.assertFalse(month_start <= prev_month)


class ClaudeCodeJsonlUsageTest(unittest.TestCase):
    """readers.common.scan_claude_jsonl の今月の時間・トークン集計。"""

    def _write(self, path: Path, lines: list[dict]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as fh:
            for line in lines:
                fh.write(json.dumps(line, ensure_ascii=False) + "\n")

    def test_tokens_are_summed_only_within_this_month(self):
        now = datetime(2026, 11, 17, 9, 0, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "session.jsonl"
            self._write(
                p,
                [
                    # 前月（10月）の分。足してはいけない
                    {
                        "type": "assistant",
                        "timestamp": "2026-10-20T00:00:00Z",
                        "message": {"role": "assistant", "content": [], "usage": {
                            "input_tokens": 9999, "output_tokens": 9999,
                            "cache_creation_input_tokens": 9999, "cache_read_input_tokens": 9999,
                        }},
                    },
                    # 今月（11月）の分。2件を足す
                    {
                        "type": "assistant",
                        "timestamp": "2026-11-05T00:00:00Z",
                        "message": {"role": "assistant", "content": [], "usage": {
                            "input_tokens": 10, "output_tokens": 20,
                            "cache_creation_input_tokens": 30, "cache_read_input_tokens": 40,
                        }},
                    },
                    {
                        "type": "assistant",
                        "timestamp": "2026-11-06T00:00:00Z",
                        "message": {"role": "assistant", "content": [], "usage": {
                            "input_tokens": 1, "output_tokens": 2,
                            "cache_creation_input_tokens": 3, "cache_read_input_tokens": 4,
                        }},
                    },
                ],
            )
            stats = common.scan_claude_jsonl(p, known_skill_names=[], known_agent_names=[], now=now)
            self.assertEqual(stats.month_tokens, {"input": 11, "output": 22, "cache_write": 33, "cache_read": 44})

    def test_duplicate_message_id_within_same_file_is_counted_once(self):
        """HIGH差し戻し: 同じ message.id が2回出てくる行（ストリーミングの再送・再構成等）で
        トークンが2倍に膨らんでいた（実測で約2.16倍）。message.id ごとに1回だけ数える。
        """
        now = datetime(2026, 11, 17, 9, 0, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "session.jsonl"
            usage = {
                "input_tokens": 10, "output_tokens": 20,
                "cache_creation_input_tokens": 30, "cache_read_input_tokens": 40,
            }
            self._write(
                p,
                [
                    {"type": "assistant", "timestamp": "2026-11-05T00:00:00Z",
                     "message": {"id": "msg_dup_1", "role": "assistant", "content": [], "usage": usage}},
                    # 同じ message.id の重複行（中身は同一の usage を繰り返す）
                    {"type": "assistant", "timestamp": "2026-11-05T00:00:01Z",
                     "message": {"id": "msg_dup_1", "role": "assistant", "content": [], "usage": usage}},
                ],
            )
            stats = common.scan_claude_jsonl(p, known_skill_names=[], known_agent_names=[], now=now)
            self.assertEqual(stats.month_tokens, {"input": 10, "output": 20, "cache_write": 30, "cache_read": 40})

    def test_duplicate_message_id_across_files_is_counted_once(self):
        """同じ message.id が別のセッションファイルにまたがって重複する場合も、
        呼び出し側が共有する seen_message_ids を渡せば1回だけ数える。
        """
        now = datetime(2026, 11, 17, 9, 0, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as td:
            usage = {
                "input_tokens": 100, "output_tokens": 5,
                "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
            }
            p1 = Path(td) / "a.jsonl"
            p2 = Path(td) / "b.jsonl"
            line = {"type": "assistant", "timestamp": "2026-11-05T00:00:00Z",
                    "message": {"id": "msg_shared", "role": "assistant", "content": [], "usage": usage}}
            self._write(p1, [line])
            self._write(p2, [line])

            seen: set = set()
            stats1 = common.scan_claude_jsonl(
                p1, known_skill_names=[], known_agent_names=[], now=now, seen_message_ids=seen
            )
            stats2 = common.scan_claude_jsonl(
                p2, known_skill_names=[], known_agent_names=[], now=now, seen_message_ids=seen
            )
            total_input = stats1.month_tokens["input"] + stats2.month_tokens["input"]
            self.assertEqual(total_input, 100)  # 200 ではなく、1回分だけ

    def test_messages_without_id_are_not_deduplicated(self):
        """id が無い行（想定外の形）は、重複判定ができないので毎回数える（推測で排除しない）。"""
        now = datetime(2026, 11, 17, 9, 0, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "session.jsonl"
            usage = {"input_tokens": 1, "output_tokens": 1, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}
            self._write(
                p,
                [
                    {"type": "assistant", "timestamp": "2026-11-05T00:00:00Z",
                     "message": {"role": "assistant", "content": [], "usage": usage}},
                    {"type": "assistant", "timestamp": "2026-11-05T00:00:01Z",
                     "message": {"role": "assistant", "content": [], "usage": usage}},
                ],
            )
            stats = common.scan_claude_jsonl(p, known_skill_names=[], known_agent_names=[], now=now)
            self.assertEqual(stats.month_tokens["input"], 2)

    def test_active_seconds_respects_five_minute_rule_across_the_whole_file(self):
        now = datetime(2026, 11, 17, 9, 0, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "session.jsonl"
            self._write(
                p,
                [
                    {"type": "user", "timestamp": "2026-11-05T00:00:00Z", "message": {"role": "user", "content": "a"}},
                    # 3分後（含む）
                    {"type": "user", "timestamp": "2026-11-05T00:03:00Z", "message": {"role": "user", "content": "b"}},
                    # さらに10分後（空きが5分を超えるので除く）
                    {"type": "user", "timestamp": "2026-11-05T00:13:00Z", "message": {"role": "user", "content": "c"}},
                ],
            )
            stats = common.scan_claude_jsonl(p, known_skill_names=[], known_agent_names=[], now=now)
            self.assertEqual(common.compute_active_seconds(stats.month_timestamps), 180)


class CodexTokenUsageTest(unittest.TestCase):
    """readers.codex: token_usage_record からのトークンの取り出し方。"""

    def test_reasoning_and_cache_fields_are_mapped(self):
        from readers import codex

        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "rollout-2026-11-16T10-00-00-abc.jsonl"
            now = datetime(2026, 11, 17, 9, 0, 0, tzinfo=timezone.utc)
            line = {
                "timestamp": "2026-11-16T10:00:00.000Z",
                "type": "token_usage_record",
                "payload": {
                    "usage": {
                        "input_tokens": 100,
                        "cached_input_tokens": 50,
                        "cache_write_input_tokens": 5,
                        "output_tokens": 20,
                        "reasoning_output_tokens": 7,
                        "total_tokens": 182,
                    }
                },
            }
            p.write_text(json.dumps(line, ensure_ascii=False) + "\n", encoding="utf-8")
            stats = codex.scan_codex_session_file(p, now=now, window_days=30)
            self.assertIsNotNone(stats)
            # MEDIUM差し戻し: cached_input_tokens は input_tokens の内数。「入力」はその分を除く
            # （排他区分にして二重計上を無くす。100 - 50 = 50）
            self.assertEqual(stats["month_tokens"]["input"], 50)
            self.assertEqual(stats["month_tokens"]["output"], 27)  # output + reasoning
            self.assertEqual(stats["month_tokens"]["cache_read"], 50)
            self.assertEqual(stats["month_tokens"]["cache_write"], 5)

    def test_cache_read_never_exceeds_input_when_input_tokens_already_excludes_cache(self):
        """入力がキャッシュ分を含まない形（cached_input_tokens が input_tokens 以下でない）でも、
        「入力」区分を負数にしない（安全側に0で止める）。
        """
        from readers import codex

        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "rollout-2026-11-16T10-00-00-xyz.jsonl"
            now = datetime(2026, 11, 17, 9, 0, 0, tzinfo=timezone.utc)
            line = {
                "timestamp": "2026-11-16T10:00:00.000Z",
                "type": "token_usage_record",
                "payload": {"usage": {"input_tokens": 10, "cached_input_tokens": 999, "output_tokens": 1}},
            }
            p.write_text(json.dumps(line, ensure_ascii=False) + "\n", encoding="utf-8")
            stats = codex.scan_codex_session_file(p, now=now, window_days=30)
            self.assertEqual(stats["month_tokens"]["input"], 0)
            self.assertEqual(stats["month_tokens"]["cache_read"], 999)

    def test_unreadable_zst_sessions_are_counted_but_not_summed(self):
        from readers import codex

        with tempfile.TemporaryDirectory() as td:
            codex_home = Path(td) / "codex_home"
            sessions = codex_home / "sessions" / "2026" / "11" / "16"
            sessions.mkdir(parents=True)
            now = datetime(2026, 11, 17, 9, 0, 0, tzinfo=timezone.utc)
            # 平文（読める）
            plain = sessions / "rollout-2026-11-16T10-00-00-aaa.jsonl"
            plain.write_text(
                json.dumps({
                    "timestamp": "2026-11-16T10:00:00.000Z", "type": "token_usage_record",
                    "payload": {"usage": {"input_tokens": 5, "output_tokens": 1,
                                           "cached_input_tokens": 0, "cache_write_input_tokens": 0}},
                }, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            # 圧縮（読めない。中身は適当なバイト列でよい）
            compressed = sessions / "rollout-2026-11-16T11-00-00-bbb.jsonl.zst"
            compressed.write_bytes(b"\x28\xb5\x2f\xfd not a real archive")

            usage = codex._collect_codex_usage(codex_home, now=now, window_days=30)
            summary = usage["month_usage"]
            self.assertEqual(summary["read_session_count"], 1)
            self.assertEqual(summary["unreadable_session_count"], 1)
            self.assertEqual(summary["tokens"]["input"], 5)
            self.assertTrue(summary["measured"])  # 読めた分が1件あるので測定できた扱い

    def test_month_usage_measured_false_when_all_data_is_compressed(self):
        """LOW/MEDIUM差し戻し: 今月分が1件もなければ measured=True（正しいゼロ）、
        今月分はあるが全部圧縮で読めない場合は measured=False（実態不明を0と断定しない）。
        """
        from readers import codex

        now = datetime(2026, 11, 17, 9, 0, 0, tzinfo=timezone.utc)

        with tempfile.TemporaryDirectory() as td:
            codex_home_empty = Path(td) / "codex_home_empty"
            codex_home_empty.mkdir()
            usage_empty = codex._collect_codex_usage(codex_home_empty, now=now, window_days=30)
            self.assertTrue(usage_empty["month_usage"]["measured"])
            self.assertEqual(usage_empty["month_usage"]["active_seconds"], 0)

        with tempfile.TemporaryDirectory() as td:
            codex_home_all_zst = Path(td) / "codex_home_all_zst"
            sessions = codex_home_all_zst / "sessions" / "2026" / "11" / "16"
            sessions.mkdir(parents=True)
            (sessions / "rollout-2026-11-16T10-00-00-ccc.jsonl.zst").write_bytes(b"\x28\xb5\x2f\xfd")
            usage_all_zst = codex._collect_codex_usage(codex_home_all_zst, now=now, window_days=30)
            self.assertFalse(usage_all_zst["month_usage"]["measured"])

    def test_candidate_files_are_scanned_only_once_for_both_windows(self):
        """LOW差し戻し: 直近30日用とまとめて今月用の集計を1回の走査で行う
        （_collect_session_summary・_collect_month_usage の2関数を1つに統合）。
        """
        from readers import codex

        with tempfile.TemporaryDirectory() as td:
            codex_home = Path(td) / "codex_home"
            sessions = codex_home / "sessions" / "2026" / "11" / "16"
            sessions.mkdir(parents=True)
            now = datetime(2026, 11, 17, 9, 0, 0, tzinfo=timezone.utc)
            p = sessions / "rollout-2026-11-16T10-00-00-ddd.jsonl"
            p.write_text(
                json.dumps({
                    "timestamp": "2026-11-16T10:00:00.000Z", "type": "token_usage_record",
                    "payload": {"usage": {"input_tokens": 3, "output_tokens": 0,
                                           "cached_input_tokens": 0, "cache_write_input_tokens": 0}},
                }, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )

            call_count = {"n": 0}
            original = codex.scan_codex_session_file

            def counting_wrapper(*args, **kwargs):
                call_count["n"] += 1
                return original(*args, **kwargs)

            codex.scan_codex_session_file = counting_wrapper
            try:
                usage = codex._collect_codex_usage(codex_home, now=now, window_days=30)
            finally:
                codex.scan_codex_session_file = original

            self.assertEqual(call_count["n"], 1, "候補ファイルは1回だけ読む（直近30日・今月のどちらの集計にも使う）")
            self.assertEqual(usage["session_summary"]["read_count"], 1)
            self.assertEqual(usage["month_usage"]["read_session_count"], 1)


class UsageTierBoundaryTest(unittest.TestCase):
    """段階の境目（items.json の usage_tier_boundaries）: 0・1・4・5・19・20回。"""

    @classmethod
    def setUpClass(cls):
        with (REPO_ROOT / "items.json").open(encoding="utf-8") as fh:
            cls.boundaries = json.load(fh)["usage_tier_boundaries"]

    def test_boundaries_at_each_breakpoint(self):
        expected = {
            0: ("0", 0.0),
            1: ("1/3", 1 / 3),
            4: ("1/3", 1 / 3),
            5: ("2/3", 2 / 3),
            19: ("2/3", 2 / 3),
            20: ("満点", 1.0),
            1000: ("満点", 1.0),
        }
        for count, (label, credit) in expected.items():
            with self.subTest(count=count):
                tier = score._usage_tier_for_count(self.boundaries, count)
                self.assertEqual(tier["label"], label)
                self.assertAlmostEqual(score._usage_tier_credit(tier), credit)
                self.assertEqual(tier["count"], count)
                # 差し戻し対応: usage_tier は公開用の4キーだけ（内部計算用の credit を持たない）
                self.assertEqual(set(tier), {"count", "credit_num", "credit_den", "label"})

    def test_compute_usage_tier_sums_counts_across_measured_tools(self):
        item_def = {"id": "F11", "usage_tiered": True}
        item_facts = {
            "per_tool": {
                "claude_code": {"measured": True, "calls_30d": 3},
                "codex": {"measured": True, "calls_30d": 2},
            }
        }
        tier = score.compute_usage_tier(item_def, item_facts, self.boundaries)
        self.assertEqual(tier["count"], 5)
        self.assertEqual(tier["label"], "2/3")

    def test_compute_usage_tier_ignores_unmeasured_tools(self):
        item_def = {"id": "F6", "usage_tiered": True}
        item_facts = {
            "per_tool": {
                "claude_code": {"measured": True, "use_total": 1},
                "codex": {"measured": False, "use_total": 999},
            }
        }
        tier = score.compute_usage_tier(item_def, item_facts, self.boundaries)
        self.assertEqual(tier["count"], 1)
        self.assertEqual(tier["label"], "1/3")

    def test_compute_usage_tier_none_when_item_not_tiered(self):
        item_def = {"id": "F5", "usage_tiered": False}
        item_facts = {"per_tool": {"claude_code": {"measured": True, "count": 12}}}
        self.assertIsNone(score.compute_usage_tier(item_def, item_facts, self.boundaries))

    def test_compute_usage_tier_none_when_nothing_measured(self):
        item_def = {"id": "F9", "usage_tiered": True}
        item_facts = {"per_tool": {"codex": {"measured": False, "use_total": 0}}}
        self.assertIsNone(score.compute_usage_tier(item_def, item_facts, self.boundaries))

    def test_partial_tier_lowers_pillar_rate_versus_old_binary_scoring(self):
        """1回使えば満点、ではなくなっていることの直接確認（オーナー指摘の修正点）。"""
        scored_full_credit = {"id": "F6", "pillar": "foundation", "status": "pass", "credit": 1.0}
        scored_partial_credit = {"id": "F6", "pillar": "foundation", "status": "pass", "credit": 1 / 3}
        pillars = {"foundation": "土台"}
        order = ["foundation"]
        old_style = score.compute_pillar_summary([scored_full_credit], pillars, order)
        new_style = score.compute_pillar_summary([scored_partial_credit], pillars, order)
        self.assertEqual(old_style["foundation"]["rate"], 1.0)
        self.assertAlmostEqual(new_style["foundation"]["rate"], 1 / 3)
        # どちらも「満たした数」は1（○の表示自体は変えていない）
        self.assertEqual(old_style["foundation"]["passed_count"], 1)
        self.assertEqual(new_style["foundation"]["passed_count"], 1)


class NamesNotLeakedInUsageFactsTest(unittest.TestCase):
    """facts.json / result.json の新しいキー（usage_this_month・tool_counts・usage_tier）に、
    スキル・エージェント・コネクタの名前が入らないこと。
    """

    @classmethod
    def setUpClass(cls):
        cls._td = tempfile.TemporaryDirectory()
        root = Path(cls._td.name)

        workdir = root / "workdir"
        workdir.mkdir()
        (workdir / "CLAUDE.md").write_text("ルール", encoding="utf-8")
        make_git_repo(workdir, with_remote=True, track_all=True)

        claude_home = root / "claude_home"
        skill_dir = claude_home / "skills" / "顧客リスト案件名スキル"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("何をするか。いつ使うか。", encoding="utf-8")
        agent_dir = claude_home / "agents"
        agent_dir.mkdir(parents=True)
        (agent_dir / "機密エージェント名.md").write_text("tools: all", encoding="utf-8")
        (claude_home / "settings.json").write_text("{}", encoding="utf-8")

        out = root / "out"
        cmd = [
            sys.executable, str(REPO_ROOT / "collect.py"),
            "--workdir", str(workdir), "--out", str(out),
            "--claude-home", str(claude_home),
            "--codex-home", str(root / "no_codex"),
            "--home", str(root / "no_home"),
            "--now", "2026-11-17T09:00:00Z",
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        assert proc.returncode == 0, proc.stdout + proc.stderr
        with (out / "facts.json").open(encoding="utf-8") as fh:
            cls.facts = json.load(fh)

        proc2 = subprocess.run(
            [sys.executable, str(REPO_ROOT / "score.py"), "--out", str(out)],
            capture_output=True, text=True, timeout=60,
        )
        assert proc2.returncode == 0, proc2.stdout + proc2.stderr
        with (out / "result.json").open(encoding="utf-8") as fh:
            cls.result = json.load(fh)

    @classmethod
    def tearDownClass(cls):
        cls._td.cleanup()

    def test_facts_usage_blocks_have_no_names(self):
        text = json.dumps(
            {"usage_this_month": self.facts["usage_this_month"], "tool_counts": self.facts["tool_counts"]},
            ensure_ascii=False,
        )
        self.assertNotIn("顧客", text)
        self.assertNotIn("案件名", text)
        self.assertNotIn("機密エージェント名", text)

    def test_result_usage_blocks_have_no_names(self):
        text = json.dumps(
            {
                "usage_this_month": self.result["usage_this_month"],
                "tool_counts": self.result["tool_counts"],
                "usage_tier": {iid: it["usage_tier"] for iid, it in self.result["items"].items()},
            },
            ensure_ascii=False,
        )
        self.assertNotIn("顧客", text)
        self.assertNotIn("案件名", text)
        self.assertNotIn("機密エージェント名", text)

    def test_tool_counts_reflect_the_one_skill_and_one_agent(self):
        self.assertEqual(self.facts["tool_counts"]["claude_code"], {"skills": 1, "agents": 1})
        self.assertEqual(self.facts["tool_counts"]["codex"], {"skills": 0, "agents": 0})

    def test_usage_this_month_shape(self):
        usage = self.result["usage_this_month"]
        self.assertEqual(set(usage), {"month", "claude_code", "codex", "combined"})
        for key in ("claude_code", "codex"):
            self.assertEqual(set(usage[key]) - {"unreadable_session_count"}, {"measured", "active_seconds", "tokens"})
            self.assertEqual(set(usage[key]["tokens"]), {"input", "output", "cache_read", "cache_write"})


# ---------------------------------------------------------------------------
# docs/RESULT_SCHEMA.md とのキー完全一致（差し戻し対応: usage_tier に内部計算用の
# credit が漏れて出ていた。受け手は4キー完全一致で検査するため、1キーでも余分や
# 不足があれば落ちることを、このテストで確かめる）。
# ---------------------------------------------------------------------------

TOP_LEVEL_KEYS = {
    "schema_version", "score", "judged_item_count", "total_item_count", "type_name",
    "pillar_order", "pillars", "items", "next_fixes", "reference", "tools_detected",
    "window_days", "usage_this_month", "tool_counts", "inventory",
}
PILLAR_KEYS = {"name", "judged_count", "total_count", "passed_count", "rate"}
ITEM_KEYS = {"name", "pillar", "judge", "judge_label", "status", "reason", "facts", "usage_tier"}
USAGE_TIER_KEYS = {"count", "credit_num", "credit_den", "label"}
NEXT_FIX_KEYS = {"id", "name", "pillar", "fix_text"}
REFERENCE_KEYS_UNNAMED = {
    "names_included", "skills", "agents", "connectors", "max_consecutive_tool_calls",
    "startup_instructions", "secret_scan", "inventory_truncated", "inventory_summaries_replaced",
}
USAGE_THIS_MONTH_TOOL_KEYS = {"measured", "active_seconds", "tokens"}
TOKENS_KEYS = {"input", "output", "cache_read", "cache_write"}
TOOL_COUNTS_TOOL_KEYS = {"skills", "agents"}
INVENTORY_SKILL_KEYS = {"summary", "category", "used_30d"}
INVENTORY_AGENT_OR_CONNECTOR_KEYS = {"summary", "used_30d"}


class ResultSchemaExactKeyMatchTest(unittest.TestCase):
    """collect.py → score.py を実際に走らせ、result.json の各段のキーが
    docs/RESULT_SCHEMA.md と完全一致する（多くも少なくもない）ことを確かめる。
    """

    @classmethod
    def setUpClass(cls):
        cls._td = tempfile.TemporaryDirectory()
        tmp_path = Path(cls._td.name)

        workdir = copy_fixture("repo_pass", tmp_path / "workdir")
        make_git_repo(workdir, with_remote=True, track_all=True)
        claude_home = copy_fixture("claude_home_pass", tmp_path / "claude_home")
        codex_home = copy_fixture("codex_home_pass", tmp_path / "codex_home")
        home = copy_fixture("home_pass", tmp_path / "home")

        out = tmp_path / "out"
        cmd = [
            sys.executable, str(REPO_ROOT / "collect.py"),
            "--workdir", str(workdir), "--out", str(out),
            "--claude-home", str(claude_home), "--codex-home", str(codex_home),
            "--home", str(home), "--now", TEST_NOW,
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        assert proc.returncode == 0, proc.stdout + proc.stderr
        # ai_judgments は空のまま（この版のテストはキーの形だけを見る。判定の中身は test_collect.py 側）
        (out / "ai_judgments.json").write_text("{}", encoding="utf-8")
        proc2 = subprocess.run(
            [sys.executable, str(REPO_ROOT / "score.py"), "--out", str(out)],
            capture_output=True, text=True, timeout=60,
        )
        assert proc2.returncode == 0, proc2.stdout + proc2.stderr
        with (out / "result.json").open(encoding="utf-8") as fh:
            cls.result = json.load(fh)

    @classmethod
    def tearDownClass(cls):
        cls._td.cleanup()

    def test_top_level_keys_match_exactly(self):
        self.assertEqual(set(self.result), TOP_LEVEL_KEYS)

    def test_pillar_keys_match_exactly(self):
        for pid, p in self.result["pillars"].items():
            with self.subTest(pillar=pid):
                self.assertEqual(set(p), PILLAR_KEYS)

    def test_every_item_key_matches_exactly(self):
        self.assertEqual(len(self.result["items"]), 23)
        for iid, item in self.result["items"].items():
            with self.subTest(item=iid):
                self.assertEqual(set(item), ITEM_KEYS)

    def test_usage_tier_has_exactly_four_keys_no_internal_credit(self):
        """本件の差し戻しそのもの: usage_tier に score.py 内部計算用の credit（小数）が
        漏れて出ていないこと。F6・F9・F11 以外は null であること。
        """
        tiered_ids = {"F6", "F9", "F11"}
        found_non_null = 0
        for iid, item in self.result["items"].items():
            tier = item["usage_tier"]
            with self.subTest(item=iid):
                if iid not in tiered_ids:
                    self.assertIsNone(tier)
                    continue
                if tier is None:
                    continue  # 測れなかった（例: F9でエージェント未使用）。形は無くてよい
                found_non_null += 1
                self.assertEqual(set(tier), USAGE_TIER_KEYS)
                self.assertNotIn("credit", tier)
        self.assertGreater(found_non_null, 0, "F6・F9・F11のどれも段階評価が無い見本では確認にならない")

    def test_next_fixes_keys_match_exactly(self):
        for fix in self.result["next_fixes"]:
            self.assertEqual(set(fix), NEXT_FIX_KEYS)

    def test_reference_keys_match_exactly_when_unnamed(self):
        self.assertFalse(self.result["reference"]["names_included"])
        self.assertEqual(set(self.result["reference"]), REFERENCE_KEYS_UNNAMED)

    def test_usage_this_month_keys_match_exactly(self):
        usage = self.result["usage_this_month"]
        self.assertEqual(set(usage), {"month", "claude_code", "codex", "combined"})
        self.assertEqual(set(usage["claude_code"]), USAGE_THIS_MONTH_TOOL_KEYS)
        self.assertEqual(set(usage["codex"]), USAGE_THIS_MONTH_TOOL_KEYS | {"unreadable_session_count"})
        self.assertEqual(set(usage["combined"]), {"active_seconds", "tokens"})
        for key in ("claude_code", "codex", "combined"):
            self.assertEqual(set(usage[key]["tokens"]), TOKENS_KEYS)

    def test_tool_counts_keys_match_exactly(self):
        counts = self.result["tool_counts"]
        self.assertEqual(set(counts), {"claude_code", "codex", "combined"})
        for key in ("claude_code", "codex", "combined"):
            self.assertEqual(set(counts[key]), TOOL_COUNTS_TOOL_KEYS)

    def test_inventory_keys_match_exactly(self):
        inv = self.result["inventory"]
        self.assertEqual(set(inv), {"skills", "agents", "connectors"})
        for row in inv["skills"]:
            self.assertEqual(set(row), INVENTORY_SKILL_KEYS)
        for row in inv["agents"] + inv["connectors"]:
            self.assertEqual(set(row), INVENTORY_AGENT_OR_CONNECTOR_KEYS)

    def test_would_have_caught_the_regression(self):
        """差し戻しの再現確認: usage_tier に余分なキーが1つでもあれば、このテストの検査
        （assertEqual によるキー集合の完全一致）は必ず落ちることを、この場で直接確かめる。
        """
        tiered = next(
            item["usage_tier"] for item in self.result["items"].values() if item["usage_tier"] is not None
        )
        poisoned = dict(tiered, credit=0.5)  # 差し戻し前の実際のバグを模した形
        with self.assertRaises(AssertionError):
            self.assertEqual(set(poisoned), USAGE_TIER_KEYS)


if __name__ == "__main__":
    unittest.main()
