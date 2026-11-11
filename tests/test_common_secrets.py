"""readers/common.py の秘密走査ロジックの単体テスト（2回目・3回目差し戻し対応）。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from readers import common  # noqa: E402


class NamingConventionExclusionTest(unittest.TestCase):
    """SPEC 5-5: sk-系の形だけ、先頭部分を除いた残りが英小文字・数字・ハイフンだけで
    ハイフンが2つ以上なら、命名の決まり・名前の例として除く（3回目差し戻しで sk-系限定に修正）。
    """

    def test_naming_convention_like_key_not_counted(self):
        text = "key_alias = sk-litellm-yujiro-claude-code-2026-05"
        self.assertEqual(common.scan_text_for_secrets(text), {})

    def test_naming_convention_like_key_not_counted_multiple_examples(self):
        text = "\n".join(
            [
                "sk-litellm-keke-baa-thumbnail-2026-05",
                "sk-litellm-take-den-sho-ml-2026-05",
                "sk-litellm-chamu-baa-script-2026-05",
            ]
        )
        self.assertEqual(common.scan_text_for_secrets(text), {})

    def test_mixed_case_real_looking_key_still_counted(self):
        """本物のキーは大文字・小文字・数字が混ざった長い文字列なので、これまでどおり数える。"""
        text = "openai_key = sk-FAKEJAPANESEFOLDERKEY7890ABCDEF"
        result = common.scan_text_for_secrets(text)
        self.assertEqual(result.get("openai_or_anthropic"), 1)

    def test_single_hyphen_not_excluded_by_this_rule(self):
        """ハイフンが1つだけなら、この除外ルールの対象ではない（他のルールで判断）。"""
        self.assertFalse(common.is_naming_convention_like("sk-ab1234567890cd"))

    def test_sk_prefix_naming_convention_excluded(self):
        self.assertTrue(common.is_naming_convention_like("sk-abc-123-xyz"))

    def test_sk_ant_prefix_naming_convention_excluded(self):
        self.assertTrue(common.is_naming_convention_like("sk-ant-team-prod-2026"))

    def test_sk_prefix_with_uppercase_remainder_not_excluded(self):
        self.assertFalse(common.is_naming_convention_like("sk-Abc-123-xyz"))

    def test_non_sk_value_never_excluded_by_this_rule(self):
        """finding #3（3回目）: この除外は sk-系だけに使う。他の形には使わない。"""
        self.assertFalse(common.is_naming_convention_like("abc-123-xyz"))

    def test_named_secret_scanner_also_excludes_sk_naming_convention(self):
        text = 'SECRET_TOKEN = "sk-litellm-team-prod-2026-05"'
        self.assertEqual(common.scan_text_for_named_secrets(text), {})


class SkOnlyScopeRegressionTest(unittest.TestCase):
    """finding #3 の再現テスト: Slack 等の本物のトークンを、sk-系用の除外が誤って除いていないか。"""

    def test_slack_lowercase_digit_hyphen_token_is_counted(self):
        """小文字・数字・ハイフンだけの Slack 形の見本トークンが、数えられること。"""
        text = "slack_token = xoxb-123456789012-abcdefghij-klmnopqrstuv0123"
        result = common.scan_text_for_secrets(text)
        self.assertEqual(result.get("slack_token"), 1)

    def test_github_lowercase_digit_token_is_counted(self):
        text = "gh_token = ghp_abcdefghij0123456789"
        result = common.scan_text_for_secrets(text)
        self.assertEqual(result.get("github_token"), 1)

    def test_aws_key_is_counted(self):
        text = "aws_key = AKIAABCDEFGHIJKLMNOP"
        result = common.scan_text_for_secrets(text)
        self.assertEqual(result.get("aws_access_key"), 1)

    def test_google_aiza_lowercase_digit_hyphen_is_counted(self):
        text = "google_key = AIza-abc-123-def-ghijklmnop-qrstuvwx"
        result = common.scan_text_for_secrets(text)
        self.assertEqual(result.get("google_aiza"), 1)

    def test_sk_prefixed_still_excluded_when_naming_convention(self):
        """対照: sk-系は引き続き除外対象（回帰確認）。"""
        text = "sk_value = sk-litellm-team-prod-2026-05"
        result = common.scan_text_for_secrets(text)
        self.assertNotIn("openai_or_anthropic", result)


if __name__ == "__main__":
    unittest.main()
