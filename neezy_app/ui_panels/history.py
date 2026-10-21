"""History panels for the NEEZY desktop window."""

from __future__ import annotations

import logging
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox

logger = logging.getLogger(__name__)


class HistoryMixin:
    """Methods for the history screen; mixed into App."""

    def _history_page(self):
        page = self.pages["HISTORY"]
        bar = tk.Frame(page, bg=self.BG)
        bar.pack(fill="x", pady=(5, 12))
        self._label(bar, "Signal history", 16).pack(side="left")
        tk.Button(
            bar,
            text="Export CSV",
            command=self._export_history,
            bg=self.PANEL2,
            fg=self.TEXT,
            relief="flat",
            padx=14,
            pady=7,
        ).pack(side="right")
        self.hist_canvas = tk.Canvas(page, bg=self.BG, highlightthickness=0)
        self.hist_frame = tk.Frame(self.hist_canvas, bg=self.BG)
        self.hist_canvas.pack(fill="both", expand=True)
        self.hist_window_id = self.hist_canvas.create_window(
            (0, 0),
            window=self.hist_frame,
            anchor="nw",
        )
        self.hist_frame.bind(
            "<Configure>",
            lambda _event, c=self.hist_canvas, f=self.hist_frame: c.configure(
                scrollregion=c.bbox("all")
            ),
        )
        self.hist_canvas.bind(
            "<Resize>",
            lambda event, c=self.hist_canvas, i=self.hist_window_id: c.itemconfigure(
                i, width=event.width - 4
            ),
        )

    def _render_history(self):
        if not hasattr(self, "hist"):
            return
        self._render_confluence_history()

    def _export_history(self):
        destination = filedialog.asksaveasfilename(
            title="Export signal history",
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv")],
            initialfile="neezy-signal-history.csv",
        )
        if not destination:
            return
        try:
            count = self.history_store.export_csv(Path(destination))
            self.settings_status.config(text=f"Exported {count} records", fg=self.GREEN)
            messagebox.showinfo(
                "History exported", f"Exported {count} signal-history records."
            )
        except OSError as error:
            logger.exception("Could not export signal history")
            messagebox.showerror("Export failed", str(error))

    def _clear_history(self):
        try:
            self.history_store.clear()
            self.history.clear()
            self._render_history()
            self.settings_status.config(
                text="Local signal history cleared", fg=self.GREEN
            )
        except OSError as error:
            logger.exception("Could not clear signal history")
            self.settings_status.config(
                text=f"History clear failed: {error}", fg=self.RED
            )
