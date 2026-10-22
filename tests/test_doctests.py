"""Doctest gate for the math modules (roadmap update #67).

Runs the doctests embedded in quant.py and risk.py docstrings so examples
can never rot silently.
"""

import doctest
import unittest

from neezy_backend import quant, risk


def load_tests(loader, tests, pattern):
    for module in (quant, risk):
        tests.addTests(doctest.DocTestSuite(module))
    return tests


class DoctestPresenceTests(unittest.TestCase):
    def test_math_modules_have_examples(self):
        """The gate itself is checked: at least one example per module."""
        for module in (quant, risk):
            examples = 0
            for obj in vars(module).values():
                if callable(obj) and getattr(obj, "__doc__", None):
                    examples += obj.__doc__.count(">>>")
            with self.subTest(module=module.__name__):
                self.assertGreater(examples, 0)


if __name__ == "__main__":
    unittest.main()
