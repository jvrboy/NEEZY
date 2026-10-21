"""Liquid-glass widget kit for the NEEZY desktop UI.

Pure Tkinter (no PIL, no extra dependencies): frosted glass panels with a
specular highlight and slow sheen sweep, pill buttons with hover glow and a
press ripple, pulsing status dots, animated gradient backdrops and easing
helpers. Every widget takes theme tokens as arguments so it follows whatever
palette the enterprise layer has active.
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from typing import Any

FRAME_MS = 16


# --------------------------------------------------------------- motion math
def clamp01(value: float) -> float:
    """Clamp to the [0, 1] interval."""
    return max(0.0, min(1.0, value))


def lerp(start: float, end: float, t: float) -> float:
    """Linear interpolation between two numbers."""
    return start + (end - start) * clamp01(t)


def ease_out_cubic(t: float) -> float:
    """Fast start, gentle landing."""
    t = clamp01(t)
    return 1 - (1 - t) ** 3


def ease_out_back(t: float, overshoot: float = 1.70158) -> float:
    """Springy overshoot landing, good for pop-in effects."""
    t = clamp01(t)
    scaled = t - 1
    return 1 + (overshoot + 1) * scaled**3 + overshoot * scaled**2


def ease_in_out_sine(t: float) -> float:
    """Symmetric smooth ease for ambience loops."""
    t = clamp01(t)
    return -(math.cos(math.pi * t) - 1) / 2


def mix_hex_color(first: str, second: str, t: float) -> str:
    """Blend two #rrggbb colours; result is a valid #rrggbb string."""
    def channels(color: str) -> tuple[int, int, int]:
        color = color.lstrip("#")
        if len(color) == 3:
            color = "".join(ch * 2 for ch in color)
        if len(color) != 6:
            raise ValueError(f"Unsupported colour: {color!r}")
        return (
            int(color[0:2], 16),
            int(color[2:4], 16),
            int(color[4:6], 16),
        )

    a, b = channels(first), channels(second)
    blended = (round(lerp(a[0], b[0], t)), round(lerp(a[1], b[1], t)), round(lerp(a[2], b[2], t)))
    return "#{:02x}{:02x}{:02x}".format(*blended)


def _with_alpha(color: str, alpha: float) -> str:
    """Blend a colour toward black (Tk has no per-item alpha for shapes)."""
    return mix_hex_color(color, "#000000", clamp01(alpha))


class Animator:
    """Drives a 0 -> 1 progression with an easing curve over real frames.

    Uses ``widget.after`` so it never blocks the Tk event loop; ``stop()`
    cancels cleanly and repeated ``start()`` calls restart from zero.
    """

    def __init__(
        self,
        widget: tk.Misc,
        duration_ms: int = 240,
        easing: Callable[[float], float] = ease_out_cubic,
        on_frame: Callable[[float], None] | None = None,
        on_done: Callable[[], None] | None = None,
    ) -> None:
        self.widget = widget
        self.duration_ms = max(1, duration_ms)
        self.easing = easing
        self.on_frame = on_frame
        self.on_done = on_done
        self._job: str | None = None
        self._start: int | None = None

    def _tick(self) -> None:
        if self._start is None:
            return
        elapsed = self.widget.tk.call("clock", "milliseconds") - self._start
        progress = clamp01(elapsed / self.duration_ms)
        if self.on_frame is not None:
            self.on_frame(self.easing(progress))
        if progress >= 1:
            self._job = None
            self._start = None
            if self.on_done is not None:
                self.on_done()
            return
        self._job = self.widget.after(FRAME_MS, self._tick)

    def start(self) -> None:
        self.stop()
        if not self.widget.winfo_exists():
            return
        self._start = int(self.widget.tk.call("clock", "milliseconds"))
        self._tick()

    def stop(self) -> None:
        if self._job is not None:
            try:
                self.widget.after_cancel(self._job)
            except tk.TclError:
                pass
        self._job = None
        self._start = None


# ------------------------------------------------------------ glass widgets
class GlassPanel(tk.Canvas):
    """Frosted glass card: rounded translucent body, top specular line, sheen.

    The sheen is a soft diagonal highlight that sweeps across the panel on a
    slow loop; it can be disabled with ``sheen=False``.
    """

    def __init__(
        self,
        master: tk.Misc,
        width: int = 260,
        height: int = 120,
        radius: int = 18,
        fill: str = "#161b26",
        border: str = "#2a3242",
        highlight: str = "#7dd3fc",
        sheen: bool = True,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            master, width=width, height=height, bg=fill, highlightthickness=0, bd=0, **kwargs
        )
        self._radius = max(2, radius)
        self._fill = fill
        self._border = border
        self._highlight = highlight
        self._sheen_enabled = sheen
        self._sheen_x = -width // 3
        self._sheen_job: str | None = None
        self._draw_static()
        if sheen:
            self._animate_sheen()

    def _rounded(self, x0: int, y0: int, x1: int, y1: int) -> Any:
        points = [
            x0 + self._radius, y0, x1 - self._radius, y0, x1, y0, x1, y0 + self._radius,
            x1, y1 - self._radius, x1, y1, x1 - self._radius, y1, x0 + self._radius, y1,
            x0, y1, x0, y1 - self._radius, x0, y0 + self._radius, x0, y0,
        ]
        return self.create_polygon(*points, smooth=True, outline="", fill="")

    def _draw_static(self) -> None:
        w, h = int(self["width"]), int(self["height"])
        self._rounded(1, 1, w - 2, h - 2)
        self.itemconfigure(self.find_withtag("polygon")[0] if self.find_withtag("polygon") else "", fill=self._fill)
        self.create_line(
            self._radius, 3, w - self._radius, 3,
            fill=_with_alpha(self._highlight, 0.55), width=1, capstyle="round",
        )
        self._rounded(1, 1, w - 2, h - 2)
        polygon_items = self.find_withtag("polygon")
        for item in polygon_items:
            self.itemconfigure(item, outline=self._border, width=1)

    def _animate_sheen(self) -> None:
        if not self.winfo_exists():
            return
        w = int(self["width"])
        h = int(self["height"])
        self.delete("sheen")
        self._sheen_x += 2
        if self._sheen_x > w + w // 3:
            self._sheen_x = -w // 3
        x = self._sheen_x
        self.create_line(
            x, 4, x + h // 2, h - 4,
            fill=_with_alpha("#ffffff", 0.06), width=8, capstyle="round", tags=("sheen",),
        )
        self.tag_lower("sheen")
        self._sheen_job = self.after(60, self._animate_sheen)

    def destroy(self) -> None:  # noqa: D102 - inherited docstring
        if self._sheen_job is not None:
            try:
                self.after_cancel(self._sheen_job)
            except tk.TclError:
                pass
        super().destroy()


class GlassButton(tk.Canvas):
    """Pill button with hover glow, press ripple and a spring label lift."""

    def __init__(
        self,
        master: tk.Misc,
        text: str,
        command: Callable[[], None] | None = None,
        width: int = 140,
        height: int = 38,
        fill: str = "#1c2230",
        border: str = "#2f3949",
        glow: str = "#38bdf8",
        text_color: str = "#e6edf7",
        font: tuple[str, int, str] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            master, width=width, height=height, bg=fill, highlightthickness=0, bd=0, **kwargs
        )
        self._command = command
        self._w = width
        self._h = height
        self._fill = fill
        self._border = border
        self._glow = glow
        self._text_color = text_color
        self._ripples: list[dict[str, Any]] = []
        self._job: str | None = None
        self._label = self.create_text(
            width // 2, height // 2, text=text, fill=text_color,
            font=font or ("Segoe UI", 10, "bold"),
        )
        self._draw(fill)
        self.bind("<Enter>", lambda _e: self._hover(True))
        self.bind("<Leave>", lambda _e: self._hover(False))
        self.bind("<Button-1>", self._press)
        self.configure(cursor="hand2")

    def _draw(self, fill: str) -> None:
        self.delete("pill", "ripple")
        self.create_oval(
            2, 2, self._w - 2, self._h - 2,
            outline=self._border, width=1, fill=fill, tags=("pill",),
        )
        self.tag_lower("ripple")

    def _hover(self, inside: bool) -> None:
        target = mix_hex_color(self._fill, self._glow, 0.18 if inside else 0.0)
        self._draw(target)
        self.itemconfigure(self._label, fill=self._text_color if inside else _with_alpha(self._text_color, 0.86))
        if inside:
            self._spring()

    def _spring(self) -> None:
        """Little pop of the label using the back-easing curve."""
        steps = 10

        def frame(step: int = 0) -> None:
            if step > steps or not self.winfo_exists():
                self.coords(self._label, self._w // 2, self._h // 2)
                return
            t = ease_out_back(step / steps)
            lift = (1 - t) * 2
            self.coords(self._label, self._w // 2, self._h // 2 - lift)
            self._job = self.after(FRAME_MS, lambda: frame(step + 1))

        frame()

    def _press(self, _event: Any) -> None:
        self._spawn_ripple()
        if self._command is not None:
            self._command()

    def _spawn_ripple(self) -> None:
        cx, cy = self._w // 2, self._h // 2
        ripple = {"r": 2.0, "alpha": 0.35, "item": None}
        self._ripples.append(ripple)

        def expand() -> None:
            if not self.winfo_exists():
                return
            if ripple["alpha"] <= 0.01:
                if ripple["item"] is not None:
                    self.delete(ripple["item"])
                if ripple in self._ripples:
                    self._ripples.remove(ripple)
                return
            if ripple["item"] is not None:
                self.delete(ripple["item"])
            r = ripple["r"]
            ripple["item"] = self.create_oval(
                cx - r, cy - r / 2, cx + r, cy + r / 2,
                outline="",
                fill=_with_alpha(self._glow, ripple["alpha"]),
                tags=("ripple",),
            )
            self.tag_lower("ripple")
            ripple["r"] += 3.2
            ripple["alpha"] *= 0.90
            self._job = self.after(FRAME_MS, expand)

        expand()

    def set_text(self, text: str) -> None:
        self.itemconfigure(self._label, text=text)


class PulseDot(tk.Canvas):
    """Status dot with a breathing glow ring (running = calm pulse)."""

    def __init__(
        self,
        master: tk.Misc,
        color: str = "#34d399",
        size: int = 14,
        period_ms: int = 1600,
        **kwargs: Any,
    ) -> None:
        super().__init__(master, width=size, height=size, bg=master["bg"] if isinstance(master, tk.Widget) else "#000000", highlightthickness=0, bd=0, **kwargs)
        self._color = color
        self._size = size
        self._period = period_ms
        self._phase = 0.0
        self._job: str | None = None
        self._draw()
        self._pulse()

    def _draw(self) -> None:
        self.delete("all")
        c = self._size / 2
        self.create_oval(c - 3, c - 3, c + 3, c + 3, fill=self._color, outline="")

    def _pulse(self) -> None:
        if not self.winfo_exists():
            return
        self._phase = (self._phase + FRAME_MS / self._period) % 1.0
        t = ease_in_out_sine(self._phase)
        c = self._size / 2
        r = 3 + 4 * t
        self.delete("ring")
        self.create_oval(
            c - r, c - r, c + r, c + r,
            outline=_with_alpha(self._color, 0.45 * (1 - t)), width=2, tags=("ring",),
        )
        self._job = self.after(FRAME_MS, self._pulse)

    def set_color(self, color: str) -> None:
        self._color = color
        self._draw()


class GlassSparkline(tk.Canvas):
    """Animated gradient sparkline with a scanning reveal."""

    def __init__(
        self,
        master: tk.Misc,
        width: int = 220,
        height: int = 56,
        stroke: str = "#38bdf8",
        base: str = "#0d1117",
        **kwargs: Any,
    ) -> None:
        super().__init__(
            master, width=width, height=height, bg=base, highlightthickness=0, bd=0, **kwargs
        )
        self._w = width
        self._h = height
        self._stroke = stroke
        self._points: list[float] = []
        self._reveal = 0.0
        self._anim = Animator(self, duration_ms=700, on_frame=self._paint)

    def set_data(self, points: Sequence[float], animate: bool = True) -> None:
        self._points = list(points)
        if animate:
            self._reveal = 0.0
            self._anim.start()
        else:
            self._reveal = 1.0
            self._paint(1.0)

    def _paint(self, t: float) -> None:
        self.delete("all")
        if len(self._points) < 2:
            self.create_text(
                self._w // 2, self._h // 2, text="awaiting data",
                fill=_with_alpha(self._stroke, 0.4), font=("Segoe UI", 8),
            )
            return
        visible = max(2, int(len(self._points) * ease_out_cubic(t)))
        chunk = self._points[:visible]
        lo, hi = min(chunk), max(chunk)
        span = (hi - lo) or 1.0
        step = (self._w - 8) / (len(chunk) - 1)
        coords: list[float] = []
        for index, value in enumerate(chunk):
            x = 4 + index * step
            y = self._h - 6 - (value - lo) / span * (self._h - 12)
            coords.extend((x, y))
        if len(coords) >= 4:
            fill_top = self._h - 6
            polygon = list(coords) + [coords[-2], fill_top, coords[0], fill_top]
            self.create_polygon(
                *polygon, fill=_with_alpha(self._stroke, 0.14), outline="", smooth=True,
            )
            self.create_line(*coords, fill=self._stroke, width=2, smooth=True, capstyle="round")


class GradientSheen(tk.Canvas):
    """Animated ambient gradient strip; colours drift and blend slowly."""

    def __init__(
        self,
        master: tk.Misc,
        width: int = 400,
        height: int = 6,
        colors: tuple[str, ...] = ("#38bdf8", "#a78bfa", "#34d399"),
        **kwargs: Any,
    ) -> None:
        super().__init__(
            master, width=width, height=height, bg="#000000", highlightthickness=0, bd=0, **kwargs
        )
        self._w = width
        self._h = height
        self._colors = colors or ("#38bdf8",)
        self._phase = 0.0
        self._job: str | None = None
        self._drift()

    def _drift(self) -> None:
        if not self.winfo_exists():
            return
        self._phase = (self._phase + 0.008) % 1.0
        self.delete("all")
        bands = max(8, self._w // 6)
        for index in range(bands):
            t = index / (bands - 1)
            cycle = (self._phase + t) % 1.0
            first = int(cycle * len(self._colors))
            a = self._colors[first % len(self._colors)]
            b = self._colors[(first + 1) % len(self._colors)]
            color = mix_hex_color(a, b, (cycle * len(self._colors)) % 1.0)
            self.create_rectangle(
                round(t * self._w), 0, round((t + 1 / bands) * self._w) + 1, self._h,
                outline="", fill=color,
            )
        self._job = self.after(50, self._drift)


__all__ = [
    "Animator",
    "GlassButton",
    "GlassPanel",
    "GlassSparkline",
    "GradientSheen",
    "PulseDot",
    "clamp01",
    "ease_in_out_sine",
    "ease_out_back",
    "ease_out_cubic",
    "lerp",
    "mix_hex_color",
]