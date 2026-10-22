"""Local models panels for the NEEZY desktop window."""

from __future__ import annotations

import tkinter as tk
from tkinter import filedialog, ttk

from neezy_backend.local_llm import (
    LocalModelError,
)


class LocalModelsMixin:
    """Methods for the local models screen; mixed into App."""

    def _local_model_settings_tab(self, notebook):
        _tab, left, right = self._settings_tab(notebook, "LOCAL MODELS")
        self._label(left, "OFFLINE GENERATIVE MODEL", 9, self.CYAN).pack(
            anchor="w", padx=16, pady=(12, 4)
        )
        self._check_row(
            left, "Use selected local model for CHAT", self.local_llm_enabled_var
        )
        self._label(left, "Registered model", 10, self.MUTED).pack(
            anchor="w", padx=16, pady=(5, 2)
        )
        self.local_model_combo = ttk.Combobox(
            left,
            textvariable=self.local_llm_model_var,
            state="readonly",
            values=(),
        )
        self.local_model_combo.pack(fill="x", padx=16, pady=(0, 4))
        self.local_model_combo.bind(
            "<<ComboboxSelected>>", lambda _: self._settings_changed()
        )
        self._spin_row(
            left, "Context window (tokens)", self.local_llm_context_var, 128, 32768, 128
        )
        self._spin_row(
            left, "Maximum new tokens", self.local_llm_tokens_var, 1, 8192, 16
        )
        self._spin_row(left, "CPU threads", self.local_llm_threads_var, 1, 16, 1)
        self._spin_row(
            left, "Inference batch size", self.local_llm_batch_var, 1, 1024, 8
        )
        self._spin_row(
            left,
            "GPU offload layers (-1 = all, 0 = CPU)",
            self.extra_vars["local_llm_gpu_layers"],
            -1,
            128,
            1,
        )
        self._spin_row(
            left,
            "Top-p sampling cutoff",
            self.extra_vars["local_llm_top_p"],
            0.1,
            1.0,
            0.05,
        )
        self._spin_row(
            left,
            "Repetition penalty",
            self.extra_vars["local_llm_repeat_penalty"],
            1.0,
            2.0,
            0.05,
        )
        self._spin_row(
            left,
            "Transformers CPU RAM budget (MB)",
            self.local_llm_memory_var,
            256,
            262144,
            256,
        )
        self._check_row(
            left,
            "Enable Transformers CPU/SSD offload (requires accelerate)",
            self.local_llm_disk_offload_var,
        )
        self._check_row(
            left,
            "Verify SHA-256 checksum before loading weights",
            self.extra_vars["local_llm_verify_sha256"],
        )

        self._label(right, "IMPORT MODEL FILES", 9, self.CYAN).pack(
            anchor="w", padx=16, pady=(12, 4)
        )
        button_row = tk.Frame(right, bg=self.PANEL)
        button_row.pack(fill="x", padx=16, pady=(0, 8))
        for text, command in [
            ("Import GGUF", self._import_gguf_model),
            ("Import model folder", self._import_transformers_model),
        ]:
            tk.Button(
                button_row,
                text=text,
                command=command,
                bg=self.PANEL2,
                fg=self.TEXT,
                relief="flat",
                padx=10,
                pady=5,
            ).pack(side="left", padx=(0, 6))
        tk.Button(
            right,
            text="Remove selected model (keep files)",
            command=self._remove_local_model,
            bg=self.PANEL2,
            fg=self.TEXT,
            relief="flat",
            padx=10,
            pady=5,
        ).pack(anchor="w", padx=16, pady=(0, 8))
        self._spin_row(
            right,
            "Keep-alive timeout (minutes)",
            self.extra_vars["local_llm_keep_alive_minutes"],
            0,
            120,
            5,
        )
        self._spin_row(
            right,
            "Deterministic generation seed (-1 = random)",
            self.extra_vars["local_llm_seed"],
            -1,
            2147483647,
            1,
        )
        self.local_model_status = self._label(
            right,
            "Model registry ready.",
            9,
            self.MUTED,
            justify="left",
            wraplength=330,
        )
        self.local_model_status.pack(anchor="w", padx=16, pady=(6, 4))
        self.local_model_runtime_label = self._label(
            right,
            "Checking optional local runtimes…",
            9,
            self.MUTED,
            justify="left",
            wraplength=330,
        )
        self.local_model_runtime_label.pack(anchor="w", padx=16, pady=(0, 8))
        self._label(
            right,
            "Models are registered by path; NEEZY does not copy or download "
            "weights. Pick trusted model files only. Transformers runs with "
            "trust_remote_code disabled and local_files_only enabled.",
            9,
            self.MUTED,
            justify="left",
            wraplength=330,
        ).pack(anchor="w", padx=16, pady=(0, 10))
        self._refresh_local_models()
        runtimes = self._local_model_status_cache
        available = (
            ", ".join(name for name, ready in runtimes.items() if ready) or "none"
        )
        self.local_model_runtime_label.config(
            text=f"Installed optional runtimes: {available}.",
            fg=self.GREEN
            if runtimes.get("llama_cpp")
            or (runtimes.get("torch") and runtimes.get("transformers"))
            else self.MUTED,
        )

    def _refresh_local_models(self, selected_id=None):
        if not hasattr(self, "local_model_combo"):
            return
        try:
            models = self.local_model_registry.list_models()
        except LocalModelError as error:
            self.local_model_status.config(text=str(error), fg=self.RED)
            models = []
        self._local_model_labels = {}
        labels = []
        for model in models:
            size_gib = model.size_bytes / (1024**3)
            label = (
                f"{model.name} · {model.format} · {size_gib:.2f} GiB · {model.model_id}"
            )
            labels.append(label)
            self._local_model_labels[label] = model.model_id
        self.local_model_combo.configure(values=labels)
        preferred = selected_id or self.settings.local_llm_model_id
        selected_label = next(
            (
                label
                for label, model_id in self._local_model_labels.items()
                if model_id == preferred
            ),
            "",
        )
        self.local_llm_model_var.set(selected_label)
        self._local_model_selection_labels = labels

    def _import_gguf_model(self):
        path = filedialog.askopenfilename(
            title="Choose a local GGUF model",
            filetypes=[("GGUF model", "*.gguf"), ("All files", "*.*")],
        )
        if not path:
            return
        self._register_local_model(path)

    def _import_transformers_model(self):
        path = filedialog.askdirectory(title="Choose a Transformers model folder")
        if not path:
            return
        self._register_local_model(path)

    def _register_local_model(self, path):
        try:
            model = self.local_model_registry.register(path)
        except (LocalModelError, OSError, ValueError) as error:
            self.local_model_status.config(text=f"Import failed: {error}", fg=self.RED)
            return
        self._refresh_local_models(model.model_id)
        self._settings_changed()
        self.local_model_status.config(
            text=(
                f"Registered {model.name} · {model.format} · "
                f"{model.size_bytes / (1024**3):.2f} GiB. "
                "The original files were not copied."
            ),
            fg=self.GREEN,
        )

    def _remove_local_model(self):
        model_id = self._local_model_labels.get(self.local_llm_model_var.get())
        if not model_id:
            self.local_model_status.config(text="Select a model first.", fg=self.RED)
            return
        try:
            model = self.local_model_registry.remove(model_id)
        except LocalModelError as error:
            self.local_model_status.config(text=str(error), fg=self.RED)
            return
        if self.settings.local_llm_model_id == model_id:
            self.local_llm_model_var.set("")
        self._refresh_local_models()
        self._settings_changed()
        self.local_model_status.config(
            text=f"Removed {model.name} from the index; model files were kept.",
            fg=self.GREEN,
        )
