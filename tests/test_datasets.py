import unittest

from neezy_backend import datasets
from neezy_backend.insights import insight_line, knowledge_brief, playbook_entry


class DatasetTests(unittest.TestCase):
    def test_every_shipped_dataset_is_valid_json(self) -> None:
        for name in datasets.list_datasets():
            with self.subTest(name):
                self.assertIsInstance(datasets.load_dataset(name), dict)

    def test_market_knowledge_has_indicators(self) -> None:
        self.assertIn("RSI", datasets.indicator_names())

    def test_playbook_lists_named_strategies(self) -> None:
        entry = playbook_entry("SUPERTREND")
        self.assertIsNotNone(entry)
        self.assertEqual(entry["name"], "SUPERTREND")
        self.assertIn("best_regime", entry)

    def test_weights_cover_the_study_symbols(self) -> None:
        document = datasets.model_weights()
        self.assertGreater(len(document.get("symbols", {})), 50)

    def test_weight_for_unknown_symbol_is_none(self) -> None:
        self.assertIsNone(datasets.weight_for("NOT_A_SYMBOL"))

    def test_insight_line_carries_the_caveat(self) -> None:
        document = datasets.model_weights()
        symbol = next(iter(document["symbols"]))
        line = insight_line(symbol)
        self.assertIsNotNone(line)
        self.assertIn("not a forecast", line)

    def test_insight_line_unknown_symbol_is_none(self) -> None:
        self.assertIsNone(insight_line("NOT_A_SYMBOL"))

    def test_rejects_path_traversal(self) -> None:
        with self.assertRaises(ValueError):
            datasets.dataset_path("../knowledge.json")

    def test_summary_reports_inventory(self) -> None:
        summary = datasets.dataset_summary()
        self.assertIn("market_knowledge.json", summary["datasets"])
        self.assertGreater(summary["weighted_symbols"], 0)

    def test_cache_clear_reloads(self) -> None:
        datasets.load_dataset(datasets.MARKET_KNOWLEDGE)
        datasets.clear_cache()
        self.assertIn(
            "RSI", datasets.indicator_names()
        )

    def test_knowledge_brief_lists_strategies(self) -> None:
        brief = knowledge_brief()
        self.assertIn("SUPERTREND", brief["strategies"])
        self.assertGreater(brief["weighted_symbols"], 0)


if __name__ == "__main__":
    unittest.main()
