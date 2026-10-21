"""Guards for the Kaggle notebook shipped in ``kaggle/``.

The notebook is a deliverable in its own right, so it is kept parseable and every code
cell is compiled here. That catches notebook-only breakage (a cell that no longer
parses, or a missing install mode) before it reaches a Kaggle session, where debugging
a failed first cell is much noisier.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KAGGLE_DIR = ROOT / "kaggle"
NOTEBOOK_PATH = KAGGLE_DIR / "NEEZY_on_Kaggle.ipynb"
METADATA_PATH = KAGGLE_DIR / "kernel-metadata.json"


def load_notebook() -> dict:
    return json.loads(NOTEBOOK_PATH.read_text(encoding="utf-8"))


def code_cells(notebook: dict) -> list[str]:
    """Return every code cell as one source string, in notebook order."""
    sources: list[str] = []
    for cell in notebook.get("cells", []):
        if cell.get("cell_type") != "code":
            continue
        source = cell.get("source", "")
        sources.append("".join(source) if isinstance(source, list) else str(source))
    return sources


class KaggleNotebookTests(unittest.TestCase):
    def test_files_are_present(self) -> None:
        self.assertTrue(NOTEBOOK_PATH.is_file(), NOTEBOOK_PATH)
        self.assertTrue(METADATA_PATH.is_file(), METADATA_PATH)

    def test_notebook_structure(self) -> None:
        notebook = load_notebook()
        self.assertEqual(notebook["nbformat"], 4)
        kinds = {cell["cell_type"] for cell in notebook["cells"]}
        self.assertTrue(kinds <= {"code", "markdown"}, kinds)
        self.assertGreaterEqual(len(code_cells(notebook)), 5)

    def test_code_cells_compile(self) -> None:
        for index, source in enumerate(code_cells(load_notebook())):
            with self.subTest(cell=index):
                compile(source, f"{NOTEBOOK_PATH.name}:cell-{index}", "exec")

    def test_install_modes_are_documented_in_nb(self) -> None:
        joined = "\n".join(code_cells(load_notebook()))
        for marker in ("INSTALL_SOURCE", "git+https://github.com/", "NEEZY_HOME"):
            self.assertIn(marker, joined)

    def test_metadata_matches_notebook(self) -> None:
        metadata = json.loads(METADATA_PATH.read_text(encoding="utf-8"))
        self.assertEqual(metadata["code_file"], NOTEBOOK_PATH.name)
        self.assertEqual(metadata["language"], "python")
        self.assertEqual(metadata["kernel_type"], "notebook")
        self.assertFalse(metadata["enable_gpu"])


if __name__ == "__main__":
    unittest.main()
