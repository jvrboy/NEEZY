#!/usr/bin/env python3
"""NEEZY // terminal animation playground

Run:   python3 neezy_animations.py
       python3 neezy_animations.py --list
       python3 neezy_animations.py --mode matrix --speed 1.4

Controls while running: q / Esc quit, Space / n next effect, p previous,
1-9 jump to an effect. No third-party packages required.
"""
import argparse
import math
import os
import random
import shutil
import sys
import time

TITLE = "NEEZY"
MODES = [
    "neon", "rainbow", "wave", "glitch", "matrix", "particles", "orbit",
    "bots", "fire", "scan", "bounce", "hyperspace", "sparkle", "pulse",
    "pixel", "radar", "galaxy", "laser", "water", "all",
]

RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"


def color(n, text, enabled=True, bold=False):
    if not enabled:
        return text
    return f"\033[{1 if bold else 0};38;5;{n}m{text}{RESET}"


def gradient_char(ch, x, y, t, enabled=True, palette=(51, 45, 39, 33, 27, 93, 129, 165, 201)):
    idx = int((x * .75 + y * .35 + t * 5) % len(palette))
    return color(palette[idx], ch, enabled, True)


def make_canvas(w, h):
    return [[(" ", None) for _ in range(w)] for _ in range(h)]


def put(c, x, y, ch, col=None):
    h, w = len(c), len(c[0]) if c else 0
    ix, iy = int(x), int(y)
    if 0 <= ix < w and 0 <= iy < h:
        c[iy][ix] = (ch, col)


def text(c, x, y, s, col=None):
    for i, ch in enumerate(s):
        put(c, x + i, y, ch, col)


def centered(c, y, s, col=None):
    text(c, (len(c[0]) - len(s)) // 2, y, s, col)


def render(c, enabled=True):
    out = []
    for row in c:
        pieces = []
        active = None
        for ch, col in row:
            if col != active:
                pieces.append(RESET if active is not None else "")
                if col is not None and enabled:
                    pieces.append(f"\033[1;38;5;{col}m")
                active = col
            pieces.append(ch)
        if active is not None:
            pieces.append(RESET)
        out.append("".join(pieces).rstrip())
    return "\n".join(out)


def logo(c, t, style="gradient", enabled=True, y=None):
    h, w = len(c), len(c[0])
    y = h // 2 if y is None else y
    x0 = (w - len(TITLE)) // 2
    for i, ch in enumerate(TITLE):
        if style == "gradient":
            col = (51, 45, 39, 33, 27, 93, 129, 165, 201)[int((i * 2 + t * 5) % 9)] if enabled else None
        elif style == "pulse":
            col = (201, 213, 219, 225, 231, 225, 219, 213)[int((t * 6) % 8)] if enabled else None
        elif style == "fire":
            col = (196, 202, 208, 214, 220, 226)[int((i + t * 8) % 6)] if enabled else None
        elif style == "matrix":
            col = (46, 40, 34, 28)[int((i + t * 6) % 4)] if enabled else None
        else:
            col = style if isinstance(style, int) and enabled else None
        put(c, x0 + i, y, ch, col)


def add_bots(c, t, count=4, radius=None, enabled=True, mode="orbit"):
    h, w = len(c), len(c[0])
    cx, cy = w / 2, h / 2
    radius = radius or max(5, min(w * .34, h * .62))
    sprites = ["[o_o]", "<^_^>", "{0_0}", "(•‿•)"]
    for i in range(count):
        phase = t * (0.65 + i * .13) + i * (2 * math.pi / count)
        if mode == "bots":
            # Bots patrol a rounded rectangular perimeter and scoot up/down slightly.
            perimeter = 2 * (max(1, w - 14) + max(1, h - 6))
            d = (t * 7 + i * perimeter / count) % perimeter
            ww, hh = max(1, w - 14), max(1, h - 6)
            if d < ww:
                bx, by = 7 + d, 2
            elif d < ww + hh:
                bx, by = 7 + ww, 2 + d - ww
            elif d < 2 * ww + hh:
                bx, by = 7 + ww - (d - ww - hh), 2 + hh
            else:
                bx, by = 7, 2 + hh - (d - 2 * ww - hh)
            bx += math.sin(t * 4 + i) * 1.5
            by += math.sin(t * 5 + i * 2) * .5
        else:
            rx = min(radius, max(2, w * .37))
            ry = min(radius * .48, max(1, h * .33))
            bx = cx + math.cos(phase) * rx
            by = cy + math.sin(phase * 1.27) * ry
        sprite = sprites[i % len(sprites)]
        xx = int(bx - len(sprite) / 2)
        col = (51, 87, 123, 159)[i % 4] if enabled else None
        text(c, xx, int(by), sprite, col)
        # tiny blinking antenna tip
        put(c, xx + 2, int(by) - 1, "*" if int(t * 5 + i) % 2 else "·", 226 if enabled else None)


def scene(mode, t, w, h, enabled=True, rng=None):
    rng = rng or random.Random(0)
    c = make_canvas(w, h)
    cx, cy = w // 2, h // 2
    if mode == "neon":
        logo(c, t, "pulse", enabled)
        centered(c, cy + 2, "✦  N E O N   S I G N A L  ✦", 201 if enabled else None)
        add_bots(c, t, 3, enabled=enabled)
        for y in range(1, h - 1):
            put(c, 2, y, "│", 54 if enabled else None); put(c, w - 3, y, "│", 54 if enabled else None)
    elif mode == "rainbow":
        logo(c, t, "gradient", enabled)
        for x in range(w):
            put(c, x, max(0, cy - 3 + int(math.sin(x * .22 + t * 3) * 2)), "~", (45 + (x + int(t * 6)) % 180) if enabled else None)
            put(c, x, min(h - 1, cy + 4 + int(math.cos(x * .15 - t * 2) * 2)), "≈", (165 + x % 50) if enabled else None)
        add_bots(c, t, 4, enabled=enabled)
    elif mode == "wave":
        logo(c, t, "gradient", enabled)
        for x in range(w):
            yy = int(cy + math.sin(x * .16 + t * 2.8) * max(2, h * .23))
            put(c, x, yy, "∿", 45 + (x % 6) * 6 if enabled else None)
            put(c, x, yy + 1, "·", 39 if enabled else None)
        add_bots(c, t, 2, enabled=enabled)
    elif mode == "glitch":
        logo(c, t, "gradient", enabled)
        if int(t * 8) % 3 == 0:
            for _ in range(max(2, w // 12)):
                yy = rng.randint(max(0, cy - 3), min(h - 1, cy + 3))
                xx = rng.randint(0, max(0, w - 5))
                text(c, xx, yy, rng.choice(["////", "░▒▓", "<<<<", "????"]), rng.choice([196, 201, 51]) if enabled else None)
            # offset echo
            text(c, cx - 2 + rng.choice([-1, 1]), cy, "NEEZY", 51 if enabled else None)
        add_bots(c, t, 2, enabled=enabled)
    elif mode == "matrix":
        for x in range(0, w, 2):
            head = int((t * (5 + x % 7) + x * 3) % max(h, 1))
            for k in range(7):
                yy = (head - k) % h
                put(c, x, yy, rng.choice("01アイウエオ<>[]{}"), (46 if k == 0 else max(22, 40 - k * 2)) if enabled else None)
        logo(c, t, "matrix", enabled)
        add_bots(c, t, 2, enabled=enabled)
    elif mode == "particles":
        for i in range(max(18, w * h // 35)):
            x = (i * 17 + int(t * (2 + i % 4) * 3)) % w
            y = (i * 11 + int(t * (1 + i % 3) * 2)) % h
            put(c, x, y, rng.choice(["·", ".", "*", "+", "✧"]), rng.choice([39, 45, 51, 93, 201]) if enabled else None)
        logo(c, t, "gradient", enabled)
        add_bots(c, t, 4, enabled=enabled)
    elif mode == "orbit":
        logo(c, t, "pulse", enabled)
        for i in range(3):
            rx, ry = 9 + i * 4, max(2, 2 + i)
            for j in range(100):
                a = 2 * math.pi * j / 100
                put(c, cx + math.cos(a) * min(rx, w * .43), cy + math.sin(a) * min(ry, h * .4), "·", (39 + i * 12) if enabled else None)
            a = t * (1.5 - i * .2) + i * 1.7
            put(c, cx + math.cos(a) * min(rx, w * .43), cy + math.sin(a) * min(ry, h * .4), "●", (51 + i * 60) if enabled else None)
        add_bots(c, t, 3, enabled=enabled)
    elif mode == "bots":
        logo(c, t, "gradient", enabled)
        add_bots(c, t, 4, enabled=enabled, mode="bots")
        centered(c, h - 2, "BOT PATROL // 04 UNITS ACTIVE", 45 if enabled else None)
    elif mode == "fire":
        logo(c, t, "fire", enabled)
        for x in range(w):
            height = int((.15 + .85 * abs(math.sin(x * .12 + t * 3) * math.cos(x * .05 - t))) * max(2, h * .4))
            for k in range(height):
                put(c, x, h - 1 - k, rng.choice(["░", "▒", "▓", "▲"]), (196 if k < height * .4 else 208 if k < height * .7 else 226) if enabled else None)
        add_bots(c, t, 2, enabled=enabled)
    elif mode == "scan":
        logo(c, t, "gradient", enabled)
        scan = int((t * 12) % max(1, h))
        for x in range(w):
            put(c, x, scan, "━", 51 if enabled else None)
            if scan + 1 < h: put(c, x, scan + 1, "·", 39 if enabled else None)
        for y in range(h):
            put(c, cx - 12, y, "┆", 39 if enabled else None); put(c, cx + 12, y, "┆", 39 if enabled else None)
        add_bots(c, t, 2, enabled=enabled)
    elif mode == "bounce":
        logo_y = int(cy + math.sin(t * 2.2) * max(1, h * .22))
        logo(c, t, "gradient", enabled, logo_y)
        centered(c, min(h - 1, logo_y + 2), "BOUNCE / DEFY GRAVITY", 93 if enabled else None)
        add_bots(c, t, 3, enabled=enabled)
    elif mode == "hyperspace":
        for i in range(40):
            ang = (i * 2.399) % (math.pi * 2)
            dist = ((i * 7 + t * (8 + i % 6)) % max(1, min(w, h) * .65))
            x = cx + math.cos(ang) * dist * 1.5
            y = cy + math.sin(ang) * dist * .48
            put(c, x, y, rng.choice([".", "·", "*", "-", "✦"]), (45 + i % 6 * 25) if enabled else None)
        logo(c, t, "pulse", enabled)
        add_bots(c, t, 2, enabled=enabled)
    elif mode == "sparkle":
        for i in range(20):
            x = (i * 13 + int(math.sin(t + i) * 4)) % w
            y = (i * 7 + int(math.cos(t * .8 + i) * 3)) % h
            ch = "✦" if int(t * 4 + i) % 4 == 0 else "+"
            put(c, x, y, ch, (201, 213, 226, 51)[i % 4] if enabled else None)
        logo(c, t, "pulse", enabled)
        centered(c, cy + 2, "S P A R K   M O D E", 201 if enabled else None)
        add_bots(c, t, 4, enabled=enabled)
    elif mode == "pulse":
        logo(c, t, "pulse", enabled)
        radius = 2 + int((t * 5) % max(2, min(w, h) / 2))
        for j in range(120):
            a = j * math.pi * 2 / 120
            put(c, cx + math.cos(a) * radius * 1.7, cy + math.sin(a) * radius * .55, "·", 51 if enabled else None)
        centered(c, cy + 2, "PULSE // 01", 213 if enabled else None)
        add_bots(c, t, 2, enabled=enabled)
    elif mode == "pixel":
        shades = " .:-=+*#%@"
        for y in range(h):
            for x in range(w):
                d = math.sqrt(((x - cx) / 1.8) ** 2 + (y - cy) ** 2)
                v = math.sin(d * .55 - t * 4) + math.sin(x * .2 + t) * .5
                if v > .7:
                    put(c, x, y, shades[min(9, int(abs(v) * 5))], (45 + int(x * 1.7) % 160) if enabled else None)
        logo(c, t, "gradient", enabled)
        add_bots(c, t, 2, enabled=enabled)
    elif mode == "radar":
        for r in (3, 6, 9, 12):
            for j in range(100):
                a = j * math.pi * 2 / 100
                put(c, cx + math.cos(a) * min(r, w * .45), cy + math.sin(a) * min(r * .48, h * .4), "·", 22 if enabled else None)
        a = t * 2.8
        for r in range(1, min(13, w // 2)):
            put(c, cx + math.cos(a) * r, cy + math.sin(a) * r * .48, "╱", 46 if enabled else None)
        logo(c, t, "matrix", enabled)
        add_bots(c, t, 2, enabled=enabled)
    elif mode == "galaxy":
        for i in range(55):
            a = i * 2.399 + t * .25
            r = (i % 25) * .52
            x = cx + math.cos(a) * r * 1.55
            y = cy + math.sin(a) * r * .58
            put(c, x, y, rng.choice([".", "·", "✧", "*", "✦"]), (93 + i % 6 * 18) if enabled else None)
        logo(c, t, "pulse", enabled)
        add_bots(c, t, 3, enabled=enabled)
    elif mode == "laser":
        logo(c, t, "gradient", enabled)
        y = int(cy + math.sin(t * 3) * max(1, h * .3))
        for x in range(w):
            put(c, x, y, "═", 196 if enabled else None)
            if y + 1 < h: put(c, x, y + 1, "─", 201 if enabled else None)
        for side in (0, w - 1):
            put(c, side, y, "◉", 226 if enabled else None)
        add_bots(c, t, 2, enabled=enabled)
    elif mode == "water":
        logo(c, t, "gradient", enabled)
        for x in range(w):
            yy = int(cy + 3 + math.sin(x * .18 + t * 2) * 2 + math.sin(x * .07 - t) * 2)
            put(c, x, yy, "≈", 39 if enabled else None)
            if yy + 1 < h: put(c, x, yy + 1, "~", 33 if enabled else None)
        for i in range(4):
            x = int((i * 17 + t * 6) % w)
            y = int(cy + 2 + math.sin(x * .18 + t * 2) * 2)
            put(c, x, y - 1, "○", 51 if enabled else None)
        add_bots(c, t, 2, enabled=enabled)
    return c


def getch_nonblocking():
    if os.name != "posix" or not sys.stdin.isatty():
        return None
    import select, termios, tty
    fd = sys.stdin.fileno()
    ready, _, _ = select.select([sys.stdin], [], [], 0)
    if not ready:
        return None
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        return sys.stdin.read(1)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def main():
    parser = argparse.ArgumentParser(description="Advanced NEEZY terminal animations with roaming mini-bots.")
    parser.add_argument("--mode", choices=MODES, default="all", help="animation mode (default: all, cycles through every effect)")
    parser.add_argument("--list", action="store_true", help="list available animation modes")
    parser.add_argument("--speed", type=float, default=1.0, help="speed multiplier (default: 1.0)")
    parser.add_argument("--fps", type=int, default=18, help="frames per second (default: 18)")
    parser.add_argument("--duration", type=float, default=7.0, help="seconds per mode in all mode (default: 7)")
    parser.add_argument("--no-color", action="store_true", help="disable ANSI colors")
    parser.add_argument("--seed", type=int, default=None, help="random seed for repeatable effects")
    args = parser.parse_args()
    if args.list:
        print("Available modes:\n  " + "  ".join(MODES[:-1]))
        return
    enabled = not args.no_color and sys.stdout.isatty()
    rng = random.Random(args.seed)
    modes = MODES[:-1] if args.mode == "all" else [args.mode]
    fps = max(1, min(60, args.fps))
    frame = 0
    mode_i = 0
    mode_started = time.monotonic()
    start = mode_started
    if sys.stdout.isatty():
        sys.stdout.write("\033[?25l\033[2J")
    try:
        while True:
            now = time.monotonic()
            elapsed = (now - start) * max(.05, args.speed)
            if args.mode == "all" and now - mode_started >= max(.5, args.duration):
                mode_i = (mode_i + 1) % len(modes)
                mode_started = now
                rng = random.Random(args.seed + mode_i if args.seed is not None else None)
            mode = modes[mode_i]
            size = shutil.get_terminal_size((90, 28))
            w, h = max(36, min(size.columns, 120)), max(14, min(size.lines - 1, 38))
            c = scene(mode, elapsed, w, h, enabled, rng)
            headline = f" N E E Z Y  //  {mode.upper()}  //  {mode_i + 1:02d}/{len(modes):02d} "
            footer = " q / Esc quit   SPACE / n next   p previous   1-9 jump "
            centered(c, 0, headline[:w], 51 if enabled else None)
            centered(c, h - 1, footer[:w], 244 if enabled else None)
            frame_text = render(c, enabled)
            if sys.stdout.isatty():
                sys.stdout.write("\033[H" + frame_text + "\033[J")
                sys.stdout.flush()
            else:
                print(f"NEEZY animation preview: {mode}\n" + frame_text)
                break
            key = getch_nonblocking()
            if key in ("q", "Q", "\x1b", "\x03"):
                break
            if key in (" ", "n") and args.mode == "all":
                mode_i = (mode_i + 1) % len(modes); mode_started = time.monotonic()
            elif key == "p" and args.mode == "all":
                mode_i = (mode_i - 1) % len(modes); mode_started = time.monotonic()
            elif key and key.isdigit() and key != "0":
                mode_i = (int(key) - 1) % len(modes); mode_started = time.monotonic()
            frame += 1
            time.sleep(max(0, 1 / fps - (time.monotonic() - now)))
    except KeyboardInterrupt:
        pass
    finally:
        if sys.stdout.isatty():
            sys.stdout.write("\033[0m\033[?25h\n")
            sys.stdout.flush()
    print("NEEZY // animation sequence complete")


if __name__ == "__main__":
    main()
