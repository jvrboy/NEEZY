"""Public API contract tests (roadmap update #36).

Locks the signatures of everything exported from `neezy_backend` so
accidental breaking changes to importers (desktop, mobile, kaggle,
scripts) fail here instead of downstream.
"""

import inspect
import unittest

import neezy_backend


class PackageContractTests(unittest.TestCase):
    def test_all_names_resolve(self):
        for name in neezy_backend.__all__:
            with self.subTest(name=name):
                self.assertTrue(hasattr(neezy_backend, name))

    def test_no_extra_public_imports_beyond_all(self):
        from pathlib import Path

        import neezy_backend as package

        # Submodule names become package attributes once imported; only real
        # non-module objects must be declared in __all__.
        submodule_names = {
            path.stem
            for path in Path(package.__file__).parent.glob("*.py")
            if path.stem != "__init__"
        }
        public = {
            name
            for name in dir(package)
            if not name.startswith("_")
            and name != "__version__"
            and name not in submodule_names
            and not inspect.ismodule(getattr(package, name))
        }
        self.assertEqual(public, set(neezy_backend.__all__))

    def test_version_is_semver_like(self):
        parts = neezy_backend.__version__.split(".")
        self.assertEqual(len(parts), 3)
        self.assertTrue(all(part.isdigit() for part in parts))


# (object, minimum positional params, keyword-only params that must exist)
_SIGNATURE_CONTRACT = [
    ("analyze", (), ()),
    ("atr", (), ()),
    ("ema", (), ()),
    ("rsi", (), ()),
    ("sma", (), ()),
    ("adx", (), ()),
    ("bollinger", (), ()),
    ("stochastic", (), ()),
    ("run_backtest", (), ("config", "cache")),
    ("position_size", (), ("symbol", "balance", "risk_percent", "entry", "stop")),
    ("atr_levels", (), ()),
    ("correlation_matrix", (), ()),
    ("detect_patterns", (), ()),
    ("price_action_summary", (), ()),
    ("market_snapshot", (), ()),
    ("format_context", (), ()),
    ("get_data_dir", (), ()),
]


class SignatureContractTests(unittest.TestCase):
    def test_signatures_are_stable(self):
        for name, _positional, keywords in _SIGNATURE_CONTRACT:
            obj = getattr(neezy_backend, name, None)
            if obj is None:
                continue  # covered by PackageContractTests for existence
            with self.subTest(name=name):
                self.assertTrue(
                    inspect.isfunction(obj) or inspect.isbuiltin(obj),
                    f"{name} is not a plain function",
                )
                signature = inspect.signature(obj)
                params = signature.parameters
                for keyword in keywords:
                    self.assertIn(
                        keyword,
                        params,
                        f"{name} lost its {keyword!r} parameter",
                    )

    def test_dataclass_public_fields_stable(self):
        import dataclasses

        for cls, expected in (
            (neezy_backend.AppSettings, {"theme", "strategy", "polling_ms"}),
            (neezy_backend.BacktestConfig, {"lookback", "spread"}),
            (neezy_backend.AlertRule, {"symbol", "metric", "operator", "value"}),
            (neezy_backend.StrategySignal, {"strategy", "direction", "confidence"}),
        ):
            with self.subTest(cls=cls.__name__):
                self.assertTrue(dataclasses.is_dataclass(cls))
                self.assertLessEqual(
                    expected, set(f.name for f in dataclasses.fields(cls))
                )


if __name__ == "__main__":
    unittest.main()
