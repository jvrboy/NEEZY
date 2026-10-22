"""Schema stability tests for exporters (roadmap update #59).

The CSV header and JSON keys are a public contract for downstream tools;
they must not drift silently.
"""

import json
import unittest

from neezy_backend.exporters import (
    SIGNAL_CSV_FIELDS,
    export_bundle,
    risk_report_to_json,
    signals_to_csv,
)


def _signal(**overrides) -> dict:
    base = {
        "symbol": "frxEURUSD",
        "direction": "BUY",
        "entry": 1.1,
        "stop": 1.09,
        "target": 1.12,
        "score": 62,
        "regime": "Trending",
        "timeframe": "5m",
        "created_at": "2026-10-22T09:00:00+00:00",
    }
    base.update(overrides)
    return base


class ExporterSchemaTests(unittest.TestCase):
    def test_csv_header_matches_documented_schema(self):
        header = signals_to_csv([]).splitlines()[0]
        self.assertEqual(
            header,
            ",".join(SIGNAL_CSV_FIELDS),
            "CSV header drifted from SIGNAL_CSV_FIELDS",
        )

    def test_csv_row_contains_every_field_column(self):
        csv_text = signals_to_csv([_signal(extra_field="ignored")])
        lines = csv_text.splitlines()
        self.assertEqual(len(lines), 2)
        self.assertEqual(len(lines[0].split(",")), len(SIGNAL_CSV_FIELDS))
        self.assertEqual(len(lines[1].split(",")), len(SIGNAL_CSV_FIELDS))
        self.assertNotIn("ignored", csv_text)

    def test_missing_keys_render_as_empty_cells(self):
        csv_text = signals_to_csv([{"symbol": "R_100"}])
        cells = csv_text.splitlines()[1].split(",")
        for field, value in zip(SIGNAL_CSV_FIELDS, cells, strict=True):
            self.assertEqual(value, "" if field != "symbol" else "R_100")

    def test_risk_json_has_stable_top_level_keys(self):
        report = {
            "samples": 100,
            "ewma_vol": 0.01,
            "sharpe": 1.5,
            "nested": {"a": 1},
        }
        parsed = json.loads(risk_report_to_json(report))
        self.assertEqual(sorted(parsed), sorted(report))
        # Sorted keys keep diffs stable.
        rendered = risk_report_to_json(report)
        self.assertLess(rendered.index('"ewma_vol"'), rendered.index('"sharpe"'))

    def test_export_bundle_writes_both_files(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as directory:
            paths = export_bundle(
                directory, [_signal()], {"samples": 10, "sharpe": None}
            )
            self.assertEqual(
                [p.name for p in paths], ["signals.csv", "risk_report.json"]
            )
            csv_text = Path(paths[0]).read_text(encoding="utf-8")
            self.assertTrue(csv_text.endswith("\n"))
            parsed = json.loads(Path(paths[1]).read_text(encoding="utf-8"))
            self.assertIn("samples", parsed)


if __name__ == "__main__":
    unittest.main()
