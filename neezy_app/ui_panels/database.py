"""Database panels for the NEEZY desktop window."""

from __future__ import annotations

import logging
import sqlite3
from tkinter import filedialog, messagebox

from neezy_backend.database import LocalDatabase

logger = logging.getLogger(__name__)


class DatabaseMixin:
    """Methods for the database screen; mixed into App."""

    def _open_database(self):
        try:
            return LocalDatabase(
                retention_days=self.settings.retention_days,
                store_candles=self.settings.store_candles,
            )
        except (OSError, sqlite3.Error) as error:
            logger.warning("Local database unavailable: %s", error)
            return None

    def _refresh_db_stats(self):
        if self.db is None:
            if hasattr(self, "db_stats_label"):
                self.db_stats_label.config(
                    text="Local database unavailable (check permissions)."
                )
            return
        try:
            stats = self.db.stats()
        except sqlite3.Error as error:
            self.db_stats_label.config(text=f"Database error: {error}")
            return
        counts = stats["counts"]
        self.db_stats_label.config(
            text=(
                f"{stats['path']}\n"
                f"{stats['size_mb']} MB · {stats['journal_mode']} journal\n"
                f"candles {counts['candles']} · signals {counts['signals']} · "
                f"snapshots {counts['snapshots']} · AI calls {counts['ai_calls']}"
            )
        )

    def _export_database(self):
        if self.db is None:
            self.settings_status.config(text="No local database to export", fg=self.RED)
            return
        destination = filedialog.asksaveasfilename(
            title="Export NEEZY database",
            defaultextension=".json",
            filetypes=[("JSON", "*.json"), ("All files", "*.*")],
        )
        if not destination:
            return
        try:
            counts = self.db.export_json(destination)
        except (OSError, sqlite3.Error) as error:
            logger.exception("Database export failed")
            messagebox.showerror("Export failed", str(error))
            return
        self.settings_status.config(
            text=f"Exported {sum(counts.values())} rows to {destination}", fg=self.GREEN
        )

    def _vacuum_db(self):
        if self.db is None:
            return
        try:
            self.db.vacuum()
        except sqlite3.Error as error:
            self.settings_status.config(text=f"Vacuum failed: {error}", fg=self.RED)
            return
        self._refresh_db_stats()
        self.settings_status.config(text="Database vacuumed", fg=self.GREEN)

    def _prune_db(self):
        if self.db is None:
            return
        try:
            removed = self.db.prune()
        except (sqlite3.Error, ValueError) as error:
            self.settings_status.config(text=f"Prune failed: {error}", fg=self.RED)
            return
        self._refresh_db_stats()
        self.settings_status.config(
            text="Pruned "
            + ", ".join(f"{key} {value}" for key, value in removed.items()),
            fg=self.GREEN,
        )
