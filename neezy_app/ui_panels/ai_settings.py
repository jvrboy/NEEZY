"""Ai settings panels for the NEEZY desktop window."""

from __future__ import annotations

import threading
import tkinter as tk
from tkinter import ttk

from neezy_backend.ai import (
    PROVIDERS,
    AIError,
    free_models,
)
from neezy_backend.config import AI_FALLBACK_PROVIDERS


class AiSettingsMixin:
    """Methods for the ai settings screen; mixed into App."""

    def _ai_provider_key(self):
        return self._provider_labels.get(self.ai_provider_var.get(), "openrouter")

    def _ai_settings_tab(self, notebook):
        _tab, left, right = self._settings_tab(notebook, "AI PROVIDERS")
        self._label(left, "BRING YOUR OWN KEY & AGENT CONFIG", 9, self.CYAN).pack(
            anchor="w", padx=16, pady=(12, 4)
        )
        self._check_row(left, "Enable AI answers in CHAT", self.ai_enabled_var)
        self._check_row(
            left,
            "Unlock custom / paid model names",
            self.extra_vars["ai_allow_custom_models"],
        )
        self._combo_row(
            left,
            "Provider",
            self.ai_provider_var,
            list(self._provider_labels),
            self._ai_provider_changed,
        )
        self._combo_row(
            left,
            "Fallback provider on error",
            self.extra_vars["ai_fallback_provider"],
            sorted(AI_FALLBACK_PROVIDERS),
        )
        self._label(left, "Model (free preset or custom)", 10, self.MUTED).pack(
            anchor="w", padx=16, pady=(5, 2)
        )
        self.ai_model_combo = ttk.Combobox(
            left,
            textvariable=self.ai_model_var,
            values=free_models(self.settings.ai_provider),
            state="normal" if self.settings.ai_allow_custom_models else "readonly",
        )
        self.ai_model_combo.pack(fill="x", padx=16, pady=(0, 3))
        self.ai_model_combo.bind(
            "<<ComboboxSelected>>", lambda _: self._settings_changed()
        )
        self.ai_model_combo.bind("<Return>", lambda _: self._settings_changed())
        self.ai_model_combo.bind("<FocusOut>", lambda _: self._settings_changed())
        self._entry_row(left, "Base URL (blank = provider default)", self.ai_base_var)
        self._spin_row(left, "Temperature x10", self.ai_temp_var, 0.0, 2.0, 0.1)
        self._spin_row(left, "Max reply tokens", self.ai_tokens_var, 64, 8192, 64)
        self._spin_row(left, "Timeout (seconds)", self.ai_timeout_var, 5.0, 300.0, 5.0)
        self._spin_row(
            left,
            "Conversation history turns",
            self.extra_vars["ai_chat_history_turns"],
            0,
            30,
            1,
        )
        self._spin_row(
            left,
            "Daily request cap (0 = unlimited)",
            self.extra_vars["ai_daily_request_cap"],
            0,
            5000,
            25,
        )
        self._entry_row(left, "System prompt (blank = built-in)", self.ai_system_var)
        self._check_row(
            left,
            "Cache identical AI prompts briefly",
            self.extra_vars["ai_cache_enabled"],
        )
        self._check_row(
            left,
            "Enable multi-step Agent tool planning in CHAT",
            self.extra_vars["agent_mode_enabled"],
        )
        self._check_row(
            left,
            "Include held-out backtest knowledge in AI context",
            self.use_knowledge_var,
        )
        self._check_row(
            left,
            "Include relevant local memory in provider prompts",
            self.use_memory_var,
        )

        self._label(right, "KEY POOL", 9, self.CYAN).pack(
            anchor="w", padx=16, pady=(12, 4)
        )
        self.ai_provider_help = self._label(
            right, "", 9, self.MUTED, justify="left", wraplength=330
        )
        self.ai_provider_help.pack(anchor="w", padx=16, pady=(0, 6))
        self.ai_keys_list = tk.Listbox(
            right,
            bg=self.PANEL2,
            fg=self.TEXT,
            relief="flat",
            height=6,
            selectbackground="#204467",
            font=("Courier", 9),
        )
        self.ai_keys_list.pack(fill="both", expand=True, padx=16, pady=(0, 6))
        row = tk.Frame(right, bg=self.PANEL)
        row.pack(fill="x", padx=16, pady=(0, 4))
        self.ai_key_entry = tk.Entry(
            row,
            show="*",
            bg=self.PANEL2,
            fg=self.TEXT,
            insertbackground=self.TEXT,
            relief="flat",
        )
        self.ai_key_entry.pack(side="left", fill="x", expand=True, ipady=4)
        self.ai_key_name = tk.Entry(
            row,
            width=12,
            bg=self.PANEL2,
            fg=self.TEXT,
            insertbackground=self.TEXT,
            relief="flat",
        )
        self.ai_key_name.pack(side="right", padx=(6, 0), ipady=4)
        self.ai_key_name.insert(0, "label")
        buttons = tk.Frame(right, bg=self.PANEL)
        buttons.pack(fill="x", padx=16, pady=(0, 4))
        for text, command in [
            ("Add key", self._ai_add_key),
            ("Remove", self._ai_remove_key),
            ("Reset", self._ai_reset_keys),
            ("Test", self._ai_test),
        ]:
            tk.Button(
                buttons,
                text=text,
                command=command,
                bg=self.PANEL2,
                fg=self.TEXT,
                relief="flat",
                padx=10,
                pady=5,
            ).pack(side="left", padx=(0, 6))
        self.ai_status = self._label(
            right,
            "Keys are stored only on this PC.",
            9,
            self.MUTED,
            justify="left",
            wraplength=330,
        )
        self.ai_status.pack(anchor="w", padx=16, pady=(0, 10))
        self._ai_provider_changed(save=False)

    def _ai_provider_changed(self, save=True):
        provider_key = self._ai_provider_key()
        spec = PROVIDERS[provider_key]
        models = free_models(provider_key)
        allow_custom = bool(self.extra_vars["ai_allow_custom_models"].get())
        if hasattr(self, "ai_model_combo"):
            self.ai_model_combo.config(
                values=models, state="normal" if allow_custom else "readonly"
            )
        if not allow_custom and self.ai_model_var.get() not in models:
            self.ai_model_var.set(models[0])
        if hasattr(self, "ai_provider_help"):
            mode_label = "custom or free models" if allow_custom else "free models"
            self.ai_provider_help.config(
                text=(
                    f"{spec.label} · {mode_label}\n"
                    f"Get a key: {spec.key_url}\n{spec.notes}"
                )
            )
        self._refresh_ai_keys()
        if save:
            self._settings_changed()

    def _refresh_ai_keys(self):
        if not hasattr(self, "ai_keys_list"):
            return
        provider_key = self._ai_provider_key()
        statuses = self.ai_keys.statuses(provider_key)
        self._ai_key_rows = [(provider_key, status.id) for status in statuses]
        self.ai_keys_list.delete(0, "end")
        if not statuses:
            self.ai_keys_list.insert(
                "end", "No keys yet - paste one below and press Add key"
            )
        for status in statuses:
            state = "ready" if status.usable() else "cooling"
            self.ai_keys_list.insert(
                "end",
                f"{status.label[:14]:<14} {status.hint:<16} "
                f"{state:<8} uses {status.uses}",
            )
        if hasattr(self, "ai_status"):
            usable = sum(1 for status in statuses if status.usable())
            self.ai_status.config(
                text=(
                    f"{len(statuses)} key(s) for {PROVIDERS[provider_key].label}; "
                    f"{usable} usable right now. Rotation is automatic when a key hits "
                    "its quota."
                ),
                fg=self.GREEN if usable else self.MUTED,
            )

    def _ai_add_key(self):
        provider_key = self._ai_provider_key()
        secret = self.ai_key_entry.get().strip()
        label = self.ai_key_name.get().strip()
        if label == "label":
            label = ""
        try:
            status = self.ai_keys.add(provider_key, secret, label)
        except ValueError as error:
            self.ai_status.config(text=str(error), fg=self.RED)
            return
        self.ai_key_entry.delete(0, "end")
        self._refresh_ai_keys()
        self.ai_status.config(
            text=f"Added {status.label} ({status.hint}).", fg=self.GREEN
        )

    def _ai_remove_key(self):
        selection = self.ai_keys_list.curselection()
        if not selection or selection[0] >= len(self._ai_key_rows):
            self.ai_status.config(text="Select a stored key first.", fg=self.RED)
            return
        provider_key, key_id = self._ai_key_rows[selection[0]]
        if self.ai_keys.remove(provider_key, key_id):
            self._refresh_ai_keys()
            self.ai_status.config(text="Key removed.", fg=self.GREEN)

    def _ai_reset_keys(self):
        changed = self.ai_keys.reset(self._ai_provider_key())
        self._refresh_ai_keys()
        self.ai_status.config(
            text=f"Cleared cooldowns on {changed} key(s).", fg=self.GREEN
        )

    def _ai_test(self):
        if self._ai_testing:
            return
        provider_key = self._ai_provider_key()
        if not self.ai_keys.secrets(provider_key):
            self.ai_status.config(
                text="Add at least one key for this provider first.", fg=self.RED
            )
            return
        self._ai_testing = True
        self.ai_status.config(text="Testing provider…", fg=self.MUTED)
        model = self.ai_model_var.get() or None
        base_url = self.ai_base_var.get().strip() or None
        settings = self.settings

        def work():
            try:
                result = self.ai_client.chat(
                    provider_key,
                    [{"role": "user", "content": "Reply with the single word OK."}],
                    model=model,
                    temperature=0.0,
                    max_tokens=16,
                    timeout=min(settings.ai_timeout, 30.0),
                    base_url=base_url,
                    system_prompt="You are a connectivity test. Reply OK.",
                )
                message = (
                    f"OK via {result.key_label} · {result.model} · "
                    f"{result.latency_ms} ms"
                )
                color = self.GREEN
            except (AIError, OSError, ValueError) as error:
                message, color = f"Test failed: {error}", self.RED
            self.after(0, lambda: self._finish_ai_test(message, color))

        threading.Thread(target=work, name="neezy-ai-test", daemon=True).start()

    def _finish_ai_test(self, message, color):
        self._ai_testing = False
        self._refresh_ai_keys()
        self.ai_status.config(text=message, fg=color)
