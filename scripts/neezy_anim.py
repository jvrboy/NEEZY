#!/usr/bin/env python3
"""
NEEZY CLI ANIMATION SUITE
17 text animations + tiny bots roaming around the logo.
Pure Python 3, zero dependencies. Needs a truecolor terminal (Termux works).

  python neezy_anim.py            # play every scene in a loop
  python neezy_anim.py list       # list scenes
  python neezy_anim.py fire       # play one scene (loops)
  python neezy_anim.py --once     # play all scenes once
  python neezy_anim.py --fps 30   # frame rate (default 24)
  python neezy_anim.py --no-bots  # hide the bots
Ctrl+C to quit.
"""
import sys, os, time, math, random, shutil, argparse, colorsys

# ───────────────────────── font ─────────────────────────
FONT = {
 'N': ["█   █", "██  █", "█ █ █", "█  ██", "█   █"],
 'E': ["█████", "█    ", "████ ", "█    ", "█████"],
 'Z': ["█████", "   █ ", "  █  ", " █   ", "█████"],
 'Y': ["█   █", " █ █ ", "  █  ", "  █  ", "  █  "],
}
WORD = "NEEZY"
TAGLINE = "A U T O N O M O U S   A G E N T S"

# ───────────────────────── helpers ─────────────────────────
def hsv(h, s=1.0, v=1.0):
    r, g, b = colorsys.hsv_to_rgb(h % 1.0, max(0, min(1, s)), max(0, min(1, v)))
    return (int(r * 255), int(g * 255), int(b * 255))

def lerp(a, b, t):
    t = max(0.0, min(1.0, t))
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))

def dim(c, k):
    return tuple(max(0, min(255, int(v * k))) for v in c)

def ease(t):
    t = max(0.0, min(1.0, t))
    return t * t * (3 - 2 * t)

def pingpong(u):
    u %= 2.0
    return u if u < 1 else 2 - u

def perim(x0, y0, x1, y1, d):
    W, H = x1 - x0, y1 - y0
    d %= 2 * (W + H)
    if d < W: return x0 + d, y0
    d -= W
    if d < H: return x1, y0 + d
    d -= H
    if d < W: return x1 - d, y1
    d -= W
    return x0, y1 - d

# ───────────────────────── canvas ─────────────────────────
class Canvas:
    def __init__(s, w, h):
        s.w, s.h = w, h
        s.clear()

    def clear(s):
        s.buf = [[(' ', None)] * s.w for _ in range(s.h)]

    def put(s, x, y, ch, col=None):
        x = math.floor(x + 0.5); y = math.floor(y + 0.5)
        if 0 <= x < s.w and 0 <= y < s.h:
            s.buf[y][x] = (ch, col)

    def text(s, x, y, txt, col=None, skip_space=True):
        for i, ch in enumerate(txt):
            if skip_space and ch == ' ': continue
            s.put(x + i, y, ch, col)

    def render(s):
        out = ["\x1b[H"]
        for row in s.buf:
            last = "x"
            for ch, col in row:
                if col != last:
                    out.append("\x1b[39m" if col is None else "\x1b[38;2;%d;%d;%dm" % col)
                    last = col
                out.append(ch)
            out.append("\x1b[0m\n")
        sys.stdout.write("".join(out)[:-1])
        sys.stdout.flush()

# ───────────────────────── logo ─────────────────────────
class Logo:
    def __init__(s, w, h, scale):
        s.scale = scale
        s.w = (len(WORD) * 6 - 1) * scale
        s.x = (w - s.w) // 2
        s.y = (h - 16) // 2 + 3
        s.cells = []
        for li, ch in enumerate(WORD):
            for ry, row in enumerate(FONT[ch]):
                for rx, v in enumerate(row):
                    if v == '█':
                        for k in range(scale):
                            s.cells.append((s.x + (li * 6 + rx) * scale + k, s.y + ry, li))
        s.cx, s.cy = s.x + s.w / 2, s.y + 2
        s.set = {(x, y) for x, y, _ in s.cells}
        s.halo = {}
        for x, y, _ in s.cells:
            for dx in range(-2, 3):
                for dy in range(-1, 2):
                    p = (x + dx, y + dy)
                    if p in s.set: continue
                    wt = max(0.0, 1 - (abs(dx) * 0.35 + abs(dy) * 0.5))
                    if wt > s.halo.get(p, 0): s.halo[p] = wt

# ───────────────────────── bots ─────────────────────────
PROPS = ["\\*/", "|*|", "/*\\", "-*-"]

def draw_roller(c, x, y, d, t, col, flip=False, ph=0.0):
    eyes = ">_>" if d > 0 else "<_<"
    if int(t * 2 + ph) % 7 == 0: eyes = "-_-"
    head = "[" + eyes + "]"
    wheels = " o o " if int(t * 8 + ph) % 2 else " O O "
    hy, wy = (y + 1, y) if flip else (y, y + 1)
    c.text(x, hy, head, col, False)
    c.text(x, wy, wheels, dim(col, 0.7), False)

class Ambient:
    def __init__(s, a):
        L = a.logo; s.a = a
        s.px0, s.px1 = max(0, L.x - 5), min(a.w - 1, L.x + L.w + 4)
        s.py0, s.py1 = L.y - 2, L.y + 6
        P = 2 * ((s.px1 - s.px0) + (s.py1 - s.py0))
        s.patrols = [(i * P / 4, hsv(i / 4 + 0.05, 0.8, 1)) for i in range(4)]
        s.rx = min(L.w / 2 + 10, (a.w - 4) / 2)
        s.ry = min(6.5, L.cy - 1.5)
        s.orbs = [(i * 2.1, 0.8 + 0.3 * i, hsv(0.12 + i * 0.3, 0.7, 1), 1 if i % 2 else -1) for i in range(3)]
        s.drones = [(0.0, 0.5, 1.5, hsv(0.9, .6, 1)), (3.1, 0.35, 1.5, hsv(0.1, .6, 1)),
                    (1.0, 0.45, a.logo.y + 9.5, hsv(0.4, .6, 1)), (4.0, 0.3, a.logo.y + 9.5, hsv(0.6, .6, 1))]

    def draw(s, c, t):
        a, L = s.a, s.a.logo
        # tiny patrol bots circling the logo box
        for off, col in s.patrols:
            d = off + t * 16
            for k in range(8, 0, -1):
                x, y = perim(s.px0, s.py0, s.px1, s.py1, d - k * 1.2)
                c.put(x, y, '·' if k > 3 else '•', dim(col, 1 - k / 9))
            x, y = perim(s.px0, s.py0, s.px1, s.py1, d)
            c.put(x, y, '●', col)
        # orbiters with trails
        for ph, sp, col, dr in s.orbs:
            for k in range(7, -1, -1):
                ang = dr * (t - k * 0.04) * sp * 2 + ph
                x = L.cx + s.rx * math.cos(ang); y = L.cy + 1 + s.ry * math.sin(ang)
                if k: c.put(x, y, '•' if k < 3 else '·', dim(col, 1 - k / 9))
                else: c.put(x, y, '◆', (255, 255, 255))
        # propeller drones weaving across top and bottom bands
        for ph, sp, yb, col in s.drones:
            x = L.cx + (a.w / 2 - 4) * math.sin(sp * t + ph)
            y = yb + 1.2 * math.sin(2.3 * t + ph)
            c.text(x - 1, y, PROPS[int(t * 14 + ph) % 4], col, False)
        # ground rollers + ceiling rollers
        rng = max(10, a.w - 10)
        for i, (sp, ph) in enumerate([(0.07, 0.0), (0.05, 1.0)]):
            u = t * sp + ph
            d = 1 if (u % 2) < 1 else -1
            if i == 1: d = -d
            x = 2 + pingpong(u if i == 0 else -u) * rng
            draw_roller(c, x, a.h - 3, d, t, hsv(0.55 + i * 0.3, .6, 1), False, ph)
        u = t * 0.06 + 0.5
        d = 1 if (u % 2) < 1 else -1
        draw_roller(c, 2 + pingpong(u) * rng, 0, d, t, hsv(0.8, .6, 1), True, 2.0)

# ───────────────────────── app ─────────────────────────
class App:
    def __init__(s, fps=24, bots=True, tmul=1.0):
        sz = shutil.get_terminal_size((80, 24))
        s.w = max(40, sz.columns - 1)
        s.h = max(18, min(sz.lines - 1, 24))
        s.scale = 2 if s.w >= 66 else 1
        s.logo = Logo(s.w, s.h, s.scale)
        s.c = Canvas(s.w, s.h)
        s.fps, s.bots, s.tmul = fps, bots, tmul
        s.amb = Ambient(s)
        s.name, s.idx, s.total, s.dt = "", 0, 0, 1 / fps

    def tagline(s, c, t):
        L = s.logo; x0 = int(L.cx - len(TAGLINE) / 2); y = L.y + 8
        hi = (t * 18) % (len(TAGLINE) + 14) - 7
        for i, ch in enumerate(TAGLINE):
            k = max(0, 1 - abs(i - hi) / 5)
            c.put(x0 + i, y, ch, lerp((70, 90, 130), (255, 255, 255), k))

    def hud(s, c):
        c.text(1, s.h - 1, "NEEZY · %s · %d/%d · ctrl+c quit" % (s.name, s.idx, s.total), (80, 90, 110))

    def play(s, dur, fn, tag=True, bots=True):
        dur *= s.tmul
        t0 = time.time(); nxt = t0; prev = 0.0
        while True:
            t = time.time() - t0
            if t >= dur: return
            s.dt = max(0.001, t - prev); prev = t
            c = s.c; c.clear()
            fn(c, t)
            if tag: s.tagline(c, t)
            if bots and s.bots: s.amb.draw(c, t)
            s.hud(c)
            c.render()
            nxt += 1 / s.fps
            d = nxt - time.time()
            if d > 0: time.sleep(d)
            else: nxt = time.time()

SCENES = []
def scene(name, desc, dur):
    def deco(f):
        SCENES.append((name, desc, dur, f)); return f
    return deco

# ───────────────────────── scenes ─────────────────────────
@scene("decrypt", "hacker decrypt, letter by letter", 6)
def sc_decrypt(a, dur):
    L = a.logo; G = "01#@%&$▒░▓<>/\\|"
    def f(c, t):
        for x, y, li in L.cells:
            rt = 0.8 + li * 0.75
            if t < rt: c.put(x, y, random.choice(G), (0, random.randint(110, 255), 60))
            elif t < rt + 0.25: c.put(x, y, '█', (255, 255, 255))
            else: c.put(x, y, '█', hsv(0.5 + 0.08 * math.sin(t + li) + x * 0.004, 0.8, 1))
    a.play(dur, f)

@scene("matrix", "matrix rain that locks into the logo", 7)
def sc_matrix(a, dur):
    L = a.logo; CH = "01ABCDEF<>=+*/"
    cols = [(random.uniform(-a.h, 0), random.uniform(7, 20), random.randint(5, 12)) for _ in range(a.w)]
    delay = {(x, y): random.uniform(0.8, dur - 2.0) for x, y, _ in L.cells}
    def f(c, t):
        for x in range(a.w):
            y0, sp, ln = cols[x]; head = (y0 + t * sp) % (a.h + ln)
            for k in range(ln):
                y = int(head) - k
                if 0 <= y < a.h:
                    g = 1 - k / ln
                    c.put(x, y, random.choice(CH), (200, 255, 200) if k == 0 else (0, int(200 * g), int(50 * g)))
        for x, y, li in L.cells:
            age = t - delay[(x, y)]
            if age > 0: c.put(x, y, '█', lerp((255, 255, 255), (0, 230, 255), age * 4))
    a.play(dur, f)

@scene("typewriter", "type-in with cursor, then neon glow pulse", 7)
def sc_type(a, dur):
    L = a.logo; order = sorted(L.cells, key=lambda q: (q[0], q[1]))
    def f(c, t):
        n = int(t * len(order) / 3.0); done = n >= len(order)
        col = lambda x: hsv(0.55 + 0.25 * (x - L.x) / L.w, 0.7, 1)
        if done:
            p = 0.6 + 0.4 * math.sin(t * 4)
            for (x, y), wt in L.halo.items():
                c.put(x, y, '░' if wt < 0.6 else '▒', dim(col(x), 0.45 * wt * p))
        for x, y, li in order[:n]: c.put(x, y, '█', col(x))
        if not done:
            x, y, _ = order[n]; c.put(x, y, '▌', (255, 255, 255))
        elif int(t * 3) % 2: c.put(L.x + L.w + 1, L.y + 4, '▌', (255, 255, 255))
    a.play(dur, f)

@scene("neon", "neon tube sputter, then steady buzz", 7)
def sc_neon(a, dur):
    L = a.logo
    def f(c, t):
        cols = [(255, 40, 200), (40, 220, 255)]
        flick = lambda li: t > li * 0.5 + 0.6 and (random.random() > 0.4 or t > li * 0.5 + 1.5)
        for (x, y), wt in L.halo.items():
            li = min(len(WORD) - 1, max(0, int((x - L.x) / (6 * L.scale))))
            if flick(li): c.put(x, y, '░', dim(cols[li % 2], 0.5 * wt))
        for x, y, li in L.cells:
            if flick(li):
                k = 0.92 + 0.08 * random.random() if t > 3 else 1
                c.put(x, y, '█', dim(lerp(cols[li % 2], (255, 255, 255), 0.25), k))
    a.play(dur, f)

@scene("rainbow", "rainbow sine wave", 6)
def sc_rainbow(a, dur):
    L = a.logo
    def f(c, t):
        for x, y, li in L.cells:
            dy = round(math.sin(x * 0.22 - t * 5) * 1.2)
            c.put(x, y + dy, '█', hsv(x * 0.012 - t * 0.35 + y * 0.04, 0.85, 1))
    a.play(dur, f)

@scene("glitch", "RGB-split glitch bursts", 7)
def sc_glitch(a, dur):
    L = a.logo
    def f(c, t):
        burst = (t % 1.3) < 0.25 or random.random() < 0.04
        sh = {y: (random.randint(-4, 4) if burst and random.random() < 0.6 else 0) for y in range(L.y, L.y + 5)}
        if burst:
            for x, y, li in L.cells:
                c.put(x + sh[y] - 1, y, '█', (255, 0, 80)); c.put(x + sh[y] + 1, y, '█', (0, 80, 255))
        for x, y, li in L.cells:
            c.put(x + sh[y], y, '█', (235, 255, 255) if burst else (0, 255, 230))
        if burst:
            for _ in range(30):
                c.put(random.randint(L.x - 3, L.x + L.w + 3), random.randint(L.y - 1, L.y + 5),
                      random.choice("▓▒░#%"), hsv(random.random(), 1, 1))
    a.play(dur, f)

@scene("fire", "burning logo with embers", 7)
def sc_fire(a, dur):
    L = a.logo; embers = []; top = {}
    for x, y, _ in L.cells: top[x] = min(top.get(x, 99), y)
    def f(c, t):
        for x, y, li in L.cells:
            heat = min(1, max(0, 0.3 + 0.7 * (y - L.y) / 4 + random.uniform(-.15, .15)))
            c.put(x, y, '█', lerp((190, 20, 0), (255, 235, 90), heat))
        for x, ty in top.items():
            h = int(1 + 2.6 * abs(math.sin(x * 0.7 + t * 9)) * random.random())
            for j in range(1, h + 1):
                c.put(x, ty - j, random.choice("^'`▴"), lerp((255, 140, 0), (120, 0, 0), j / (h + 1)))
        if random.random() < 0.9:
            x, y, _ = random.choice(L.cells)
            embers.append([x, y, random.uniform(-3, 3), -random.uniform(5, 12), 1.0])
        for e in embers:
            e[0] += e[2] * a.dt; e[1] += e[3] * a.dt; e[4] -= a.dt * 0.7
            if e[4] > 0: c.put(e[0], e[1], random.choice("·*'"), lerp((120, 20, 0), (255, 200, 60), e[4]))
        embers[:] = [e for e in embers if e[4] > 0 and e[1] > 0]
    a.play(dur, f)

def fly_pos(sx, sy, x, y, p, sw):
    e = ease(p)
    return (sx + (x - sx) * e + sw * 6 * math.sin(p * math.pi),
            sy + (y - sy) * e + sw * 3 * math.sin(p * math.pi * 2) * (1 - p))

@scene("assemble", "bot swarm flies in and builds the logo", 8)
def sc_assemble(a, dur):
    L = a.logo; P = []
    for x, y, li in L.cells:
        side = random.choice("LRTB")
        sx, sy = {"L": (-3, random.uniform(0, a.h)), "R": (a.w + 3, random.uniform(0, a.h)),
                  "T": (random.uniform(0, a.w), -3), "B": (random.uniform(0, a.w), a.h + 3)}[side]
        P.append((x, y, sx, sy, random.uniform(0, 2.0), random.uniform(1.4, 2.2), random.uniform(-1, 1)))
    def f(c, t):
        for x, y, sx, sy, d, fl, sw in P:
            p = (t - d) / fl
            if p <= 0: continue
            if p >= 1:
                base = hsv(0.5 + 0.1 * math.sin(x * .1 + t), .8, 1)
                c.put(x, y, '█', lerp((255, 255, 255), base, (t - d - fl) * 3)); continue
            col = hsv(sw * .2 + .55, .6, 1)
            for k in (4, 3, 2, 1):
                px, py = fly_pos(sx, sy, x, y, max(0, p - k * 0.04), sw)
                c.put(px, py, '·', dim(col, 1 - k / 5))
            px, py = fly_pos(sx, sy, x, y, p, sw); c.put(px, py, '●', col)
    a.play(dur, f)

@scene("shatter", "logo explodes then bots pull it back", 7)
def sc_shatter(a, dur):
    L = a.logo
    V = {(x, y): (random.uniform(-26, 26), -random.uniform(4, 18)) for x, y, _ in L.cells}
    def at(x, y, tt):
        vx, vy = V[(x, y)]
        return x + vx * tt, y + vy * tt + 0.5 * 38 * tt * tt
    def f(c, t):
        tt = t - 1.2
        for x, y, li in L.cells:
            base = hsv(0.6 + x * 0.006, .7, 1)
            if tt < 0: c.put(x, y, '█', base); continue
            if tt < 1.6:
                px, py = at(x, y, tt); k = tt / 1.6
                c.put(px, py, '█' if k < .3 else '▓' if k < .6 else '▒', lerp(base, (255, 120, 40), k))
            else:
                p = ease((tt - 1.6) / 1.8); px, py = at(x, y, 1.6)
                nx, ny = px + (x - px) * p, py + (y - py) * p
                c.put(nx, ny, '█' if p > .9 else '▒', lerp((255, 120, 40), base, p))
    a.play(dur, f)

@scene("warp", "hyperspace warp into the logo", 7)
def sc_warp(a, dur):
    L = a.logo
    S = [[random.uniform(-1, 1), random.uniform(-1, 1), random.uniform(0.05, 1)] for _ in range(110)]
    def proj(s, z): return a.w / 2 + s[0] / z * a.w * 0.12, a.h / 2 + s[1] / z * a.h * 0.12
    def f(c, t):
        sp = 0.15 + 1.5 * math.sin(math.pi * min(1, t / dur)) ** 2
        for s in S:
            z0 = s[2]; s[2] -= sp * a.dt
            if s[2] < 0.03: s[0], s[1], s[2] = random.uniform(-1, 1), random.uniform(-1, 1), 1.0; continue
            x1, y1 = proj(s, s[2]); x0, y0 = proj(s, min(1.2, s[2] + sp * 0.06))
            n = max(1, int(abs(x1 - x0) + abs(y1 - y0)))
            br = 1 - s[2]
            for i in range(n + 1):
                c.put(x0 + (x1 - x0) * i / n, y0 + (y1 - y0) * i / n,
                      '·' if i < n else ('*' if br > .6 else '+'), lerp((60, 80, 160), (255, 255, 255), br))
        k = ease((t - dur * 0.4) / (dur * 0.3))
        if k > 0:
            for x, y, li in L.cells: c.put(x, y, '█', dim(lerp((120, 200, 255), (255, 255, 255), k), k))
    a.play(dur, f)

@scene("scanner", "laser scan with shimmer sweep", 7)
def sc_scan(a, dur):
    L = a.logo
    def f(c, t):
        lx = L.x - 2 + pingpong(t * 0.35) * (L.w + 4)
        band = (t * 28) % (a.w + 30) - 10
        for x, y, li in L.cells:
            base = (0, 190, 255) if x < lx else (35, 60, 100)
            k = max(0, 1 - abs(x + y * 2 - band) / 6)
            c.put(x, y, '█', lerp(base, (255, 255, 255), k))
        for y in range(L.y - 1, L.y + 6): c.put(lx, y, '│', (255, 40, 90))
        for _ in range(4): c.put(lx + random.randint(-2, 2), random.randint(L.y - 1, L.y + 5), '*', (255, 200, 80))
    a.play(dur, f)

@scene("bounce", "letters bounce in sequence with shadows", 6)
def sc_bounce(a, dur):
    L = a.logo
    def f(c, t):
        up = {}
        for li in range(len(WORD)):
            up[li] = abs(math.sin(t * 3 - li * 0.6)) * 3
            sx0 = L.x + li * 6 * L.scale; sw = 5 * L.scale
            sh = max(1, int(sw * (1 - up[li] / 5)))
            c.text(sx0 + (sw - sh) // 2, L.y + 6, '▀' * sh, (40, 45, 60))
        for x, y, li in L.cells:
            c.put(x, y - up[li], '█', hsv(li * 0.18 + t * 0.2, .8, 1))
    a.play(dur, f)

@scene("rings", "shockwave rings rippling from the logo", 7)
def sc_rings(a, dur):
    L = a.logo
    def f(c, t):
        for y in range(a.h):
            for x in range(a.w):
                d = math.hypot((x - L.cx) / 2.0, y - L.cy)
                for k in range(3):
                    r = (t * 9 + k * 7) % 21
                    e = abs(d - r)
                    if e < 0.7: c.put(x, y, '○' if e < .35 else '·', hsv(0.55 + k * .12, .7, 1 - r / 24)); break
        for x, y, li in L.cells:
            c.put(x, y, '█', lerp((120, 160, 255), (255, 255, 255), 0.5 + 0.5 * math.sin(t * 5)))
    a.play(dur, f)

@scene("loading", "boot bar with a bot pushing progress", 8)
def sc_loading(a, dur):
    L = a.logo
    MSG = ["linking agents", "syncing repo", "warming models", "arming tools", "going live"]
    def f(c, t):
        p = max(0.0, min(1.0, t / max(0.2, dur * a.tmul - 1.5)))
        for x, y, li in L.cells:
            c.put(x, y, '█', hsv(0.55 + 0.1 * math.sin(t * 2 + x * .05), .8, 1) if x < L.x + p * L.w else (35, 45, 65))
        bw, bx, by = L.w, L.x, L.y + 10
        fill = int(bw * p)
        c.text(bx, by, '█' * fill, (0, 220, 255)); c.text(bx + fill, by, '░' * (bw - fill), (45, 55, 80))
        if p < 1:
            c.text(bx + max(0, fill - 3), by - 1, "[>_>]", (255, 255, 255), False)
            c.text(bx, by + 1, "%3d%%  %s%s" % (p * 100, MSG[min(4, int(p * 5))], "." * (int(t * 4) % 4)), (140, 160, 200), False)
        else:
            c.text(bx, by + 1, "READY ✔" if int(t * 4) % 2 else "READY", (80, 255, 140), False)
    a.play(dur, f)

@scene("braille", "every block is a living braille spinner", 6)
def sc_braille(a, dur):
    L = a.logo; SP = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
    def f(c, t):
        for x, y, li in L.cells:
            c.put(x, y, SP[int(t * 12 + x * 0.7 + y) % len(SP)], hsv(x * 0.01 + t * 0.2, .7, 1))
    a.play(dur, f)

@scene("spin", "3D coin-spin around the vertical axis", 6)
def sc_spin(a, dur):
    L = a.logo
    def f(c, t):
        cs = math.cos(t * 2.2)
        for x, y, li in L.cells:
            nx = L.cx + (x - L.cx) * cs
            col = lerp((0, 120, 255), (0, 255, 220), abs(cs)) if cs >= 0 else lerp((90, 0, 160), (255, 60, 200), abs(cs))
            c.put(nx, y, '█' if abs(cs) > .2 else '│', col)
    a.play(dur, f)

@scene("plasma", "liquid plasma behind and inside the logo", 7)
def sc_plasma(a, dur):
    L = a.logo
    def pl(x, y, t):
        return (math.sin(x * .15 + t) + math.sin(y * .3 - t * 1.3) + math.sin((x + y) * .1 + t * .7)) / 3
    def f(c, t):
        for y in range(a.h):
            for x in range(a.w):
                if (x, y) not in L.set: c.put(x, y, '░', hsv(.6 + pl(x, y, t) * .3, .8, .28))
        for x, y, li in L.cells: c.put(x, y, '█', hsv(.6 + pl(x, y, t) * .4 + .15, .7, 1))
    a.play(dur, f)

@scene("party", "finale: confetti, rainbow, a whole bot parade", 9)
def sc_party(a, dur):
    L = a.logo; conf = []
    runners = [(random.uniform(.4, 1.4), random.uniform(0, 6), random.choice((-1, 1)), random.choice((0, 1)), hsv(random.random(), .7, 1)) for _ in range(8)]
    def f(c, t):
        for x, y, li in L.cells:
            c.put(x, y + round(math.sin(x * .2 - t * 6)), '█', hsv(x * 0.015 - t * .5, .85, 1))
        for _ in range(3): conf.append([random.uniform(0, a.w), -1, random.uniform(6, 14), random.random()])
        for q in conf:
            q[1] += q[2] * a.dt; q[0] += math.sin(q[1] + q[3] * 6) * 0.4
            c.put(q[0], q[1], random.choice("*+·•"), hsv(q[3] + t * .3, 1, 1))
        conf[:] = [q for q in conf if q[1] < a.h]
        for sp, ph, d, top, col in runners:
            u = t * sp * 0.12 + ph
            x = 2 + pingpong(u) * (a.w - 10); dr = d * (1 if (u % 2) < 1 else -1)
            draw_roller(c, x, 0 if top else a.h - 3, dr, t, col, bool(top), ph)
    a.play(dur, f)

# ───────────────────────── main ─────────────────────────
def main():
    ap = argparse.ArgumentParser(description="NEEZY CLI animations")
    ap.add_argument("scene", nargs="?", default="all", help="scene name, 'all' or 'list'")
    ap.add_argument("--fps", type=int, default=24)
    ap.add_argument("--once", action="store_true", help="play everything once and exit")
    ap.add_argument("--no-bots", action="store_true")
    ap.add_argument("--time", type=float, default=1.0, help="duration multiplier")
    args = ap.parse_args()
    if args.scene == "list":
        for n, d, t, _ in SCENES: print("%-11s %s" % (n, d))
        return
    pick = SCENES if args.scene == "all" else [s for s in SCENES if s[0] == args.scene]
    if not pick: sys.exit("unknown scene. run: python neezy_anim.py list")
    os.system("")  # enable ANSI on Windows
    a = App(args.fps, not args.no_bots, args.time); a.total = len(pick)
    sys.stdout.write("\x1b[?1049h\x1b[?25l\x1b[2J")
    try:
        while True:
            for i, (n, d, dur, fn) in enumerate(pick, 1):
                a.name, a.idx = n, i
                sys.stdout.write("\x1b[2J"); fn(a, dur)
            if args.once: break
    except KeyboardInterrupt:
        pass
    finally:
        sys.stdout.write("\x1b[0m\x1b[?25h\x1b[?1049l"); sys.stdout.flush()

if __name__ == "__main__":
    main()
