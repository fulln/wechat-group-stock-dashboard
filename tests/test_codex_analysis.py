import unittest

from build_speaker_stock_dashboard import a_share_symbol
from codex_stock_analysis import normalize_analysis, normalize_security_fields


class CodexAnalysisTests(unittest.TestCase):
    def test_normalizes_contextual_mentions(self):
        raw = {
            "stocks": [{
                "name": "工业富联",
                "code": "601138",
                "market": "SH",
                "confidence": "medium",
                "note": "妇联在盘中语境中指工业富联",
                "contexts": [
                    {"time": "2026-07-17 10:00", "sender": "甲", "alias": "妇联", "signal": "中性", "text": "看看妇联"},
                    {"time": "10:01", "sender": "乙", "alias": "指代延续", "signal": "偏多", "text": "可以接一点"},
                ],
            }],
            "emotion": {
                "score": 1, "label": "谨慎偏多", "bullish_count": 1, "bearish_count": 0,
                "neutral_count": 1, "bullish_examples": [], "bearish_examples": [],
            },
            "sectors": [{"name": "算力", "stock_names": ["工业富联"]}],
            "market": {"count": 1, "summary": "震荡", "examples": []},
        }

        result = normalize_analysis(raw)

        self.assertEqual(result["analysis_method"], "codex_semantic_context_review")
        self.assertEqual(result["stocks"][0]["count"], 2)
        self.assertEqual(result["stocks"][0]["speakers"], 2)
        self.assertEqual(result["stocks"][0]["sentiment"]["label"], "偏多")
        self.assertEqual(result["stocks"][0]["contexts"][1]["signal_key"], "bullish")
        self.assertEqual(result["stocks"][0]["contexts"][0]["time"], "10:00")

    def test_daily_k_rejects_non_mainland_six_digit_codes(self):
        self.assertIsNone(a_share_symbol({"market": "KRX", "code": "000660"}))
        self.assertIsNone(a_share_symbol({"market": "韩国股市", "code": "000660.KS"}))
        self.assertEqual(a_share_symbol({"market": "SZSE", "code": "300418.SZ"}), "sz300418")
        self.assertEqual(a_share_symbol({"market": "SSE", "code": "688432.SH"}), "sh688432")

    def test_normalizes_codex_mainland_market_labels(self):
        self.assertEqual(
            normalize_security_fields({"name": "长电科技", "market": "沪市主板", "code": "600584.SH"}),
            {"name": "长电科技", "market": "SH", "code": "600584"},
        )
        self.assertEqual(
            normalize_security_fields({"name": "昆仑万维", "market": "创业板", "code": "300418.SZ"}),
            {"name": "昆仑万维", "market": "SZ", "code": "300418"},
        )
        korean = {"name": "SK海力士", "market": "KRX", "code": "000660"}
        self.assertEqual(normalize_security_fields(korean), korean)


if __name__ == "__main__":
    unittest.main()
