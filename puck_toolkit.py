#!/usr/bin/env python3
"""Puck Report toolkit: renders recap videos, score cards and news reels from JSON specs.

Usage:
  python3 puck_toolkit.py setup                 # logos + converter (run once per workspace)
  python3 puck_toolkit.py fetch 2026-10-20 out/slate.json   # one night's finals from the NHL stats feed
  python3 puck_toolkit.py scores  spec.json     # animated 'Last night' card (mp4) + still (png), 1080x1350
  python3 puck_toolkit.py recap   spec.json     # single-game recap video, 1080x1920
  python3 puck_toolkit.py reel    spec.json     # single-screen news reel (story or list), 1080x1920
Every command writes <out>.mp4 (and <out>.png for scores) next to the spec unless "out" is a path.
"""
import json
import os
import subprocess
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
LOGOS = os.path.join(HERE, "logos")
FPS = 30
WHITE, MUTED, ICE, RED = (242, 246, 250), (139, 160, 189), (92, 200, 255), (232, 56, 79)
BG_TOP, BG_BOT = (9, 16, 30), (16, 34, 60)
NAVY = np.array((9, 16, 30), np.float32) / 255.0
LOGO_CODES = {"NJ": "NJD", "LA": "LAK", "SJ": "SJS", "TB": "TBL", "UTAH": "UTA"}
FROM_API = {"NJD": "NJ", "LAK": "LA", "SJS": "SJ", "TBL": "TB"}
NICK = {"ANA": "Ducks", "BOS": "Bruins", "BUF": "Sabres", "CAR": "Hurricanes", "CBJ": "Blue Jackets",
        "CGY": "Flames", "CHI": "Blackhawks", "COL": "Avalanche", "DAL": "Stars", "DET": "Red Wings",
        "EDM": "Oilers", "FLA": "Panthers", "LA": "Kings", "MIN": "Wild", "MTL": "Canadiens", "NJ": "Devils",
        "NSH": "Predators", "NYI": "Islanders", "NYR": "Rangers", "OTT": "Senators", "PHI": "Flyers",
        "PIT": "Penguins", "SEA": "Kraken", "SJ": "Sharks", "STL": "Blues", "TB": "Lightning", "TOR": "Maple Leafs",
        "UTA": "Mammoth", "VAN": "Canucks", "VGK": "Golden Knights", "WPG": "Jets", "WSH": "Capitals"}


# ------------------------------------------------------------------ fonts
FONT_DIRS = ["/usr/share/fonts/opentype/inter/"]
_fonts = {}


def font(size, weight="Bold"):
    key = (size, weight)
    if key not in _fonts:
        f = None
        for d in FONT_DIRS:
            p = os.path.join(d, f"InterDisplay-{weight}.otf")
            if os.path.exists(p):
                f = ImageFont.truetype(p, size)
                break
        if f is None:
            bold = weight in ("Black", "ExtraBold", "Bold")
            p = "/usr/share/fonts/truetype/dejavu/DejaVuSans" + ("-Bold" if bold else "") + ".ttf"
            f = ImageFont.truetype(p, size) if os.path.exists(p) else ImageFont.load_default()
        _fonts[key] = f
    return _fonts[key]


def wrap(s, f, max_w):
    out = []
    for para in s.split("\n"):
        cur = ""
        for w in para.split():
            t = (cur + " " + w).strip()
            if f.getlength(t) <= max_w or not cur:
                cur = t
            else:
                out.append(cur)
                cur = w
        out.append(cur)
    return "\n".join(out)


# ------------------------------------------------------------------ sprites
class El:
    def __init__(self, img, x, y, delay=0.0, rise=50):
        a = np.asarray(img.convert("RGBA"), dtype=np.float32) / 255.0
        self.rgb, self.a = a[..., :3], a[..., 3:4]
        self.x, self.y, self.delay, self.rise = int(x), int(y), delay, rise
        self.h, self.w = self.a.shape[:2]


def text_img(s, f, color, spacing=0.12, align="left"):
    d = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    sp = int(f.size * spacing)
    bb = [int(round(v)) for v in d.multiline_textbbox((0, 0), s, font=f, spacing=sp, align=align)]
    img = Image.new("RGBA", (bb[2] - bb[0] + 4, bb[3] - bb[1] + 4), (0, 0, 0, 0))
    ImageDraw.Draw(img).multiline_text((-bb[0] + 2, -bb[1] + 2), s, font=f, fill=color, spacing=sp, align=align)
    return img


def T(s, size, x, y, delay, color=WHITE, weight="Bold", anchor="l", max_w=None, spacing=0.12):
    f = font(size, weight)
    if max_w:
        s = wrap(s, f, max_w)
    img = text_img(s, f, color, spacing, {"l": "left", "r": "right", "c": "center"}[anchor])
    if anchor == "r":
        x -= img.width
    elif anchor == "c":
        x -= img.width // 2
    return El(img, x, y, delay)


def pill_img(label, size=34, bg=RED):
    f = font(size, "ExtraBold")
    tw = int(f.getlength(label))
    h = int(size * 1.9)
    img = Image.new("RGBA", (tw + 56, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, img.width - 1, h - 1), radius=h // 2, fill=bg)
    d.text((28, h // 2), label, font=f, fill=WHITE, anchor="lm")
    return img


def pill(label, x, y, delay):
    return El(pill_img(label), x, y, delay)


def card_img(w, h, accent=None):
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, w - 1, h - 1), radius=28, fill=(255, 255, 255, 18), outline=(255, 255, 255, 38),
                        width=2)
    if accent:
        d.rounded_rectangle((0, 0, 10, h - 1), radius=5, fill=tuple(accent))
    return img


def card(w, h, x, y, delay, accent=None):
    return El(card_img(w, h, accent), x, y, delay, rise=30)


def badge(abbr, size=74):
    """Official logo on a light disc; falls back to an abbreviation disc."""
    s = size * 3
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    path = os.path.join(LOGOS, LOGO_CODES.get(abbr, abbr) + ".png")
    d.ellipse((0, 0, s - 1, s - 1), fill=(242, 246, 250, 255))
    if os.path.exists(path):
        logo = Image.open(path).convert("RGBA")
        logo = logo.crop(logo.getbbox())
        box = int(s * 0.74)
        r = min(box / logo.width, box / logo.height)
        logo = logo.resize((max(1, int(logo.width * r)), max(1, int(logo.height * r))), Image.LANCZOS)
        img.paste(logo, ((s - logo.width) // 2, (s - logo.height) // 2), logo)
    else:
        d.text((s / 2, s / 2), abbr[:3], font=font(int(s * 0.36), "Black"), fill=(9, 16, 30), anchor="mm")
    return img.resize((size, size), Image.LANCZOS)


def puck_img(scale=1.0):
    w, h = int(420 * scale), int(200 * scale)
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    s = scale
    for i, (x1, ln, op) in enumerate(((10, 140, 255), (60, 100, 180), (110, 60, 110))):
        y = (60 + i * 36) * s
        d.rounded_rectangle((x1 * s, y - 7 * s, (x1 + ln) * s, y + 7 * s), radius=7 * s, fill=ICE + (op,))
    cx, rx, ry, top, bot = 300 * s, 110 * s, 36 * s, 70 * s, 140 * s
    lw = max(2, int(5 * s))
    d.ellipse((cx - rx, bot - ry, cx + rx, bot + ry), fill=(3, 6, 12, 255), outline=ICE + (255,), width=lw)
    d.rectangle((cx - rx, top, cx + rx, bot), fill=(3, 6, 12, 255))
    d.line((cx - rx, top, cx - rx, bot), fill=ICE + (255,), width=lw)
    d.line((cx + rx, top, cx + rx, bot), fill=ICE + (255,), width=lw)
    d.ellipse((cx - rx, top - ry, cx + rx, top + ry), fill=(26, 38, 56, 255), outline=ICE + (255,), width=lw)
    return img


def make_bg(W, H, extra=400):
    t = np.linspace(0, 1, H + extra)[:, None, None]
    top, bot = np.array(BG_TOP, np.float32), np.array(BG_BOT, np.float32)
    bg = (top * (1 - t) + bot * t) * np.ones((1, W, 1), np.float32)
    img = Image.fromarray(bg.astype(np.uint8))
    d = ImageDraw.Draw(img, "RGBA")
    for yy, col in ((int(H * 0.27), (92, 200, 255, 22)), (int(H * 0.6), (232, 56, 79, 26)),
                    (int(H * 0.93), (92, 200, 255, 22))):
        d.rectangle((0, yy, W, yy + 10), fill=col)
    d.ellipse((W - 520, int(H * 0.44), W + 220, int(H * 0.44) + 600), outline=(232, 56, 79, 30), width=8)
    return np.asarray(img, np.float32) / 255.0


def ease(p):
    p = min(max(p, 0.0), 1.0)
    return 1 - (1 - p) ** 3


# ------------------------------------------------------------------ photos
class Photo:
    def __init__(self, path, dest_h, W, H, focus_x=0.5, focus_y=0.35, box=None, fade=(0.55, 1.0), max_dark=1.0,
                 top_dark=False):
        im = Image.open(path).convert("RGB")
        if box:
            im = im.crop(tuple(box))
        self.pan = 70
        tw, th = W + self.pan, dest_h
        r = tw / th
        sw, sh = im.size
        if sw / sh > r:
            cw = int(sh * r)
            x0 = int(min(max(focus_x * sw - cw / 2, 0), sw - cw))
            im = im.crop((x0, 0, x0 + cw, sh))
        else:
            ch = int(sw / r)
            y0 = int(min(max(focus_y * sh - ch / 2, 0), sh - ch))
            im = im.crop((0, y0, sw, y0 + ch))
        im = im.resize((tw, th), Image.LANCZOS)
        self.img = np.asarray(im, np.float32) / 255.0
        y = np.arange(th, dtype=np.float32)[:, None, None] / th
        if top_dark:
            self.dark = np.clip((0.52 - y) / 0.22, 0, 1) * 0.95 + np.clip((y - 0.9) / 0.1, 0, 1) * 0.3
        else:
            g = np.clip((y - fade[0]) / (fade[1] - fade[0]), 0, 1) * max_dark
            self.dark = np.maximum(g, np.clip((0.12 - y) / 0.12, 0, 1) * 0.45)
        self.h, self.W = th, W

    def draw(self, frame, prog, alpha):
        x = int(self.pan * prog)
        src = self.img[:, x:x + self.W]
        shaded = src * (1 - self.dark) + NAVY * self.dark
        frame[:self.h] = frame[:self.h] * (1 - alpha) + shaded * alpha


# ------------------------------------------------------------------ music
def beat(seconds, out, seed=7):
    from scipy.io import wavfile
    from scipy.signal import butter, lfilter
    SR, BPM = 44100, 122
    B = 60 / BPM
    rng = np.random.default_rng(seed)

    def env(n, a, d):
        t = np.arange(n) / SR
        return np.minimum(t / a, 1.0) * np.exp(-t / d)

    def filt(x, f, kind):
        b, a = butter(2, f / (SR / 2), kind)
        return lfilter(b, a, x)

    def kick():
        n = int(0.35 * SR)
        t = np.arange(n) / SR
        return np.sin(2 * np.pi * np.cumsum(50 + 110 * np.exp(-t * 30)) / SR) * env(n, 0.001, 0.12)

    def snare():
        n = int(0.25 * SR)
        t = np.arange(n) / SR
        return 0.45 * filt(rng.standard_normal(n), 1200, "high") * env(n, 0.001, 0.07) + \
            0.35 * np.sin(2 * np.pi * 190 * t) * env(n, 0.001, 0.05)

    def hat(o=False):
        n = int((0.18 if o else 0.05) * SR)
        return filt(rng.standard_normal(n), 7000, "high") * env(n, 0.0005, 0.06 if o else 0.015) * 0.18

    def saw(fq, n):
        return 2 * ((np.arange(n) / SR * fq) % 1.0) - 1

    def note(m):
        return 440 * 2 ** ((m - 69) / 12)

    n = int(seconds * SR)
    drums, bass, pad = np.zeros(n), np.zeros(n), np.zeros(n)

    def place(buf, sig, t):
        i = int(t * SR)
        j = min(i + len(sig), len(buf))
        if i < len(buf):
            buf[i:j] += sig[:j - i]

    prog = [(57, [69, 72, 76]), (53, [65, 69, 72]), (48, [64, 67, 72]), (55, [67, 71, 74])]
    bar = 4 * B
    for b in range(int(seconds / bar) + 1):
        t0 = b * bar
        root, chord = prog[b % 4]
        intro = b < 2
        for s in range(16):
            ts = t0 + s * B / 4
            if not intro and s in (0, 6, 8, 10 if b % 2 else 99):
                place(drums, kick(), ts)
            if intro and s in (0, 8):
                place(drums, kick() * 0.7, ts)
            if not intro and s in (4, 12):
                place(drums, snare(), ts)
            if s % 2 == 0:
                place(drums, hat(s == 14), ts)
        for e in range(8):
            sn = int(B / 2 * SR * 0.9)
            m = root - 12 + (12 if e in (3, 7) else 0)
            place(bass, filt(saw(note(m), sn), 600, "low") * env(sn, 0.003, 0.18) * (0.22 if intro else 0.32),
                  t0 + e * B / 2)
        for st in ((1.5, 3.5) if not intro else (0,)):
            sn = int((B * 0.45 if not intro else bar) * SR)
            sig = sum(filt(saw(note(m), sn) + saw(note(m) * 1.004, sn), 2400, "low") for m in chord)
            place(pad, sig * env(sn, 0.01, 0.25 if not intro else 1.2) * 0.06, t0 + st * B)
    mix = drums * 0.8 + bass + pad
    fi, fo = int(0.3 * SR), int(2.0 * SR)
    mix[:fi] *= np.linspace(0, 1, fi)
    mix[-fo:] *= np.linspace(1, 0, fo)
    mix = np.tanh(mix * 1.4)
    mix = mix / np.max(np.abs(mix)) * 0.85
    wavfile.write(out, SR, (np.stack([mix, np.roll(mix, 220) * 0.98], 1) * 32767).astype(np.int16))


def mux(silent, total, out):
    wav = out + ".wav"
    beat(total + 0.5, wav)
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", silent, "-i", wav, "-map", "0:v", "-map", "1:a",
                    "-c:v", "copy", "-filter:a", "volume=-4dB", "-c:a", "aac", "-b:a", "160k", "-ar", "48000",
                    "-shortest", "-movflags", "+faststart", out], check=True)
    os.remove(wav)
    os.remove(silent)


# ------------------------------------------------------------------ 9:16 slide engine
W9, H9, M9 = 1080, 1920, 80


def render_slides(slides, out, progress=True):
    W, H = W9, H9
    bg = make_bg(W, H)
    total = sum(s["dur"] for s in slides)
    silent = out + ".silent.mp4"
    ff = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s",
                           f"{W}x{H}", "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "medium", "-crf", "19",
                           "-pix_fmt", "yuv420p", silent], stdin=subprocess.PIPE)
    starts, acc = [], 0.0
    for s in slides:
        starts.append(acc)
        acc += s["dur"]
    n = len(slides)
    for fi in range(int(total * FPS)):
        t = fi / FPS
        si = max(i for i, s0 in enumerate(starts) if s0 <= t)
        sl, lt = slides[si], t - starts[si]
        dur = sl["dur"]
        shift = min(int(lt * 18), 199)
        frame = bg[200 - shift:200 - shift + H].copy()
        out_p = ease((lt - (dur - 0.35)) / 0.3) if si < n - 1 or not sl.get("hold") else 0
        if sl.get("photo"):
            sl["photo"].draw(frame, lt / dur, ease(lt / 0.5) * (1 - out_p))
        for e in sl["els"]:
            p = ease((lt - e.delay) / 0.45)
            a_ = p * (1 - out_p)
            if a_ <= 0.001:
                continue
            y = e.y + int((1 - p) * e.rise) - int(out_p * 40)
            x = e.x
            y0, y1, x0, x1 = max(y, 0), min(y + e.h, H), max(x, 0), min(x + e.w, W)
            if y0 >= y1 or x0 >= x1:
                continue
            a = e.a[y0 - y:y1 - y, x0 - x:x1 - x] * a_
            frame[y0:y1, x0:x1] = frame[y0:y1, x0:x1] * (1 - a) + e.rgb[y0 - y:y1 - y, x0 - x:x1 - x] * a
        img8 = (np.clip(frame, 0, 1) * 255).astype(np.uint8)
        if progress:
            gap = 10
            seg = (W - 80 - gap * (n - 1)) / n
            for i in range(n):
                sx = int(40 + i * (seg + gap))
                ex = int(sx + seg)
                img8[70:78, sx:ex] = (img8[70:78, sx:ex] * 0.6 + 36).astype(np.uint8)
                fill = 1.0 if i < si else (min(lt / dur, 1.0) if i == si else 0.0)
                if fill > 0:
                    img8[70:78, sx:sx + int((ex - sx) * fill)] = WHITE
        ff.stdin.write(img8.tobytes())
    ff.stdin.close()
    ff.wait()
    mux(silent, total, out)
    return total


# ------------------------------------------------------------------ recap slide builders
def photo_for(s, dest_h, base):
    if not s.get("photo"):
        return None
    p = s["photo"]
    if isinstance(p, str):
        p = {"path": p}
    path = p["path"] if os.path.isabs(p["path"]) else os.path.join(base, p["path"])
    if not os.path.exists(path):
        return None
    return Photo(path, p.get("h", dest_h), W9, H9, p.get("focus_x", 0.5), p.get("focus_y", 0.35), p.get("box"),
                 top_dark=p.get("top_dark", False))


def stack_text(els, x, y, parts, max_w):
    for s, size, col, wt, d, gap, sp in parts:
        e = T(s, size, x, y, d, col, wt, max_w=max_w, spacing=sp)
        els.append(e)
        y += e.h + gap
    return y


def b_hook(s, base):
    M = M9
    p = s.get("photo")
    p = ({"path": p} if isinstance(p, str) else dict(p)) if p else None
    top = bool(p and p.get("top_dark"))
    if p:
        p.setdefault("h", H9 if top else 1180)
    ph = photo_for({"photo": p}, H9, base) if p else None
    y0 = 250 if top else (1000 if ph else 680)
    els = [] if ph else [El(puck_img(1.1), M - 10, 360, 0.1)]
    els.append(pill(s.get("tag", "FINAL"), M, y0, 0.25))
    stack_text(els, M, y0 + 90, [(s["headline"], s.get("size", 112), WHITE, "Black", 0.45, 24, 0.06),
                                 (s.get("line", ""), 56, ICE, "Bold", 0.9, 0, 0.1)], W9 - 2 * M)
    return els, ph


def b_score(s, base):
    M = M9
    els = [pill(s.get("tag", "FINAL SCORE"), M, 300, 0)]
    for i, (city, name, sc) in enumerate(s["teams"]):
        win = i == 0
        y, d = 420 + i * 330, 0.25 + i * 0.25
        els += [card(W9 - 2 * M, 290, M, y, d, accent=ICE if win else None),
                T(city.upper(), 38, M + 50, y + 60, d + 0.1, MUTED, "SemiBold"),
                T(name, 80 if len(name) < 12 else 66, M + 50, y + 115, d + 0.1, WHITE if win else MUTED, "ExtraBold"),
                T(str(sc), 190, W9 - M - 50, y + 40, d + 0.2, ICE if win else MUTED, "Black", anchor="r")]
    if s.get("line"):
        els.append(T(s["line"], 54, M, 1150, 0.9, WHITE, "SemiBold", max_w=W9 - 2 * M, spacing=0.25))
    return els, None


def b_periods(s, base):
    M = M9
    rows = s["rows"]
    els = [pill(s.get("tag", "HOW IT HAPPENED"), M, 300, 0),
           T(s.get("title", "Period by period"), 84, M, 400, 0.15, WHITE, "Black")]
    ch, step, y = (230, 265, 580) if len(rows) <= 3 else (196, 218, 560)
    hi = s.get("highlight", len(rows) - 1)
    for i, (per, what, sc) in enumerate(rows):
        d = 0.4 + i * 0.32
        els += [card(W9 - 2 * M, ch, M, y, d, accent=RED if i == hi else ICE),
                T(per.upper(), 34, M + 50, y + 36, d + 0.1, MUTED, "Bold"),
                T(what, 46, M + 50, y + ch // 2 - 10, d + 0.1, WHITE, "ExtraBold", max_w=W9 - 2 * M - 340),
                T(sc, 58, W9 - M - 50, y + 36, d + 0.2, ICE, "Black", anchor="r")]
        y += step
    return els, None


def b_photo_text(s, base):
    M = M9
    ph = photo_for(s, 1180 if s.get("y0", 1000) >= 1000 else 900, base)
    if ph is None:  # no photo: fall back to a tiles-free graphic layout
        els = [pill(s["tag"], M, 300, 0)]
        stack_text(els, M, 400, [(s["name"], 120, WHITE, "Black", 0.2, 30, 0.04),
                                 (s.get("stat", ""), 70, ICE, "ExtraBold", 0.6, 30, 0.1),
                                 (s.get("sub", ""), 52, WHITE, "SemiBold", 1.0, 0, 0.25)], W9 - 2 * M)
        return els, None
    y0 = s.get("y0", 1000)
    els = [pill(s["tag"], M, y0, 0.3)]
    stack_text(els, M, y0 + 90, [(s["name"], 100, WHITE, "Black", 0.45, 22, 0.04),
                                 (s.get("stat", ""), 66, ICE, "ExtraBold", 0.75, 26, 0.1),
                                 (s.get("sub", ""), 48, WHITE, "Medium", 1.0, 0, 0.25)], W9 - 2 * M)
    return els, ph


def b_tiles(s, base):
    M = M9
    els = [pill(s["tag"], M, 300, 0), T(s["title"], 132, M, 400, 0.2, WHITE, "Black", spacing=0.02)]
    tiles = s["tiles"][:3]
    tw = (W9 - 2 * M - 2 * 24) // 3
    for i, (num, lab) in enumerate(tiles):
        x, d = M + i * (tw + 24), 0.55 + i * 0.18
        nsz = 92 if len(str(num)) <= 4 else 70
        els += [card(tw, 230, x, 760, d, accent=ICE if i == 0 else None),
                T(str(num), nsz, x + tw // 2, 790, d + 0.05, ICE if i == 0 else WHITE, "Black", anchor="c"),
                T(lab.upper(), 30, x + tw // 2, 915, d + 0.1, MUTED, "Bold", anchor="c", max_w=tw - 20)]
    if s.get("note"):
        els.append(T(s["note"], 52, M, 1080, 1.2, WHITE, "SemiBold", max_w=W9 - 2 * M, spacing=0.25))
    return els, None


def b_list(s, base):
    M = M9
    ph = photo_for(s, 900, base)
    y = 830 if ph else 300
    els = [pill(s["tag"], M, y, 0.3)]
    if not ph and s.get("title"):
        els.append(T(s["title"], 84, M, 400, 0.15, WHITE, "Black"))
        y = 470
    y += 90
    for i, (n, lab) in enumerate(s["rows"]):
        d = 0.5 + i * 0.18
        els += [card(W9 - 2 * M, 104, M, y, d, accent=ICE),
                T(n, 48, M + 50, y + 26, d + 0.05, WHITE, "Bold"),
                T(lab.upper(), 28, W9 - M - 40, y + 38, d + 0.1, ICE, "ExtraBold", anchor="r")]
        y += 120
    if s.get("foot"):
        els.append(T(s["foot"], 40, M, y + 14, 1.3, MUTED, "SemiBold", max_w=W9 - 2 * M, spacing=0.2))
    return els, ph


def stat_bar(label, a, b, fmt, y, delay, low_wins=False):
    M = M9
    w, h = W9 - 2 * M, 150
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    fl, fb = font(38, "SemiBold"), font(60, "Black")
    ab = a < b if low_wins else a > b
    bb = b < a if low_wins else b > a
    d.text((w / 2, 18), label.upper(), font=fl, fill=MUTED, anchor="mt")
    d.text((0, 10), fmt.format(a), font=fb, fill=ICE if ab else WHITE, anchor="lt")
    d.text((w, 10), fmt.format(b), font=fb, fill=ICE if bb else WHITE, anchor="rt")
    by, bh, cx, half = 100, 18, w / 2, w / 2 - 6
    mx = max(a, b, 1e-9)
    d.rounded_rectangle((0, by, w, by + bh), radius=9, fill=(255, 255, 255, 20))
    if a > 0:
        d.rounded_rectangle((min(cx - half * a / mx, cx - 3 - bh), by, cx - 3, by + bh), radius=9, fill=ICE + (255,))
    if b > 0:
        d.rounded_rectangle((cx + 3, by, max(cx + half * b / mx, cx + 3 + bh), by + bh), radius=9,
                            fill=MUTED + (255,))
    return El(img, M, y, delay, rise=30)


def b_numbers(s, base):
    M = M9
    els = [pill(s.get("tag", "BY THE NUMBERS"), M, 300, 0), T(s["title"], 84, M, 400, 0.15, WHITE, "Black"),
           T(s["left"], 40, M, 545, 0.3, ICE, "ExtraBold"), T(s["right"], 40, W9 - M, 545, 0.3, MUTED, "ExtraBold",
                                                              anchor="r")]
    for i, st in enumerate(s["stats"][:5]):
        lab, a, b = st[0], st[1], st[2]
        fmt = st[3] if len(st) > 3 else "{}"
        low = st[4] if len(st) > 4 else False
        els.append(stat_bar(lab, a, b, fmt, 620 + i * 170, 0.45 + i * 0.25, low))
    if s.get("note"):
        y = 620 + len(s["stats"][:5]) * 170 + 20
        els.append(T(s["note"], 46, M, y, 1.5, WHITE, "SemiBold", max_w=W9 - 2 * M, spacing=0.25))
    return els, None


def b_outro(s, base):
    p = puck_img(1.0)
    bar = Image.new("RGBA", (140, 12), RED + (255,))
    return [El(p, (W9 - p.width) // 2, 560, 0.1), T("PUCK REPORT", 130, W9 // 2, 800, 0.3, WHITE, "Black", anchor="c"),
            El(bar, (W9 - 140) // 2, 960, 0.5, rise=0),
            T(s.get("line", "Follow for every game"), 56, W9 // 2, 1020, 0.7, ICE, "Bold", anchor="c")], None


BUILDERS = {"hook": b_hook, "score": b_score, "periods": b_periods, "photo_text": b_photo_text, "tiles": b_tiles,
            "list": b_list, "numbers": b_numbers, "outro": b_outro}
DEFAULT_DUR = {"hook": 4.2, "score": 4.5, "periods": 5.0, "photo_text": 5.5, "tiles": 5.0, "list": 5.5,
               "numbers": 6.0, "outro": 3.8}


def cmd_recap(spec, base):
    slides = []
    for s in spec["slides"]:
        els, ph = BUILDERS[s["type"]](s, base)
        slides.append(dict(dur=s.get("dur", DEFAULT_DUR[s["type"]]), els=els, photo=ph))
    if spec["slides"][-1]["type"] != "outro":
        els, _ = b_outro({}, base)
        slides.append(dict(dur=3.8, els=els))
    return render_slides(slides, spec["out"])


# ------------------------------------------------------------------ single-screen news reels
def brand(delay):
    p = puck_img(0.34)
    img = Image.new("RGBA", (W9 - 2 * M9 + 40, 90), (0, 0, 0, 0))
    img.paste(p, (0, 10), p)
    d = ImageDraw.Draw(img)
    d.text((p.width + 14, 45), "PUCK REPORT", font=font(44, "Black"), fill=WHITE, anchor="lm")
    d.text((img.width, 45), "Follow for daily NHL", font=font(32, "SemiBold"), fill=ICE, anchor="rm")
    return El(img, M9 - 20, H9 - 170, delay, rise=20)


def cmd_reel(spec, base):
    M = 60
    els = []
    if spec.get("kind", "story") == "story":
        p = spec.get("photo")
        p = ({"path": p} if isinstance(p, str) else dict(p)) if p else None
        if p:
            p.setdefault("h", 900)
        ph = photo_for({"photo": p}, 900, base) if p else None
        y = 700 if ph else 260
        els.append(pill(spec["tag"], M, y, 0.3))
        h = T(spec["headline"], 96, M, y + 84, 0.5, WHITE, "Black", max_w=W9 - 2 * M, spacing=0.04)
        s = T(spec.get("sub", ""), 48, M, h.y + h.h + 10, 0.9, ICE, "Bold", max_w=W9 - 2 * M)
        els += [h, s]
        y = s.y + s.h + 36
        d = 2.0
        for it in spec.get("items", []):
            t = T(it, 42, M + 46, y + 28, d + 0.05, WHITE, "SemiBold", max_w=W9 - 2 * M - 92, spacing=0.22)
            els += [card(W9 - 2 * M, t.h + 56, M, y, d, accent=ICE), t]
            y += t.h + 74
            d += 1.6
        if spec.get("question"):
            els.append(T(spec["question"], 44, M, y + 10, d + 0.2, WHITE, "ExtraBold", max_w=W9 - 2 * M))
        if spec.get("source"):
            els.append(T(spec["source"], 28, M, H9 - 230, d + 0.4, MUTED, "Medium"))
        els.append(brand(d + 0.6))
        slide = dict(dur=spec.get("dur", max(10.0, d + 3.0)), els=els, photo=ph)
        return render_slides([slide], spec["out"])
    # list reel (injuries, signings, ...): scrolls when rows overflow
    return list_reel(spec)


def list_reel(spec):
    W, H, M = W9, H9, 60
    rows = spec["rows"]  # [team, title, subtitle, status]
    RW, RH, GAP = W - 2 * M, 112, 14
    VT, VB = 440, 1700
    STEP = spec.get("step", max(0.55, min(1.3, 7.0 / max(len(rows), 1))))
    bgf = make_bg(W, H)[200:200 + H]
    bg = Image.fromarray((bgf * 255).astype(np.uint8)).convert("RGBA")
    head = Image.new("RGBA", (W, VT), (0, 0, 0, 0))
    d = ImageDraw.Draw(head)
    tag = pill_img(spec["tag"], 30)
    head.paste(tag, (M, 140), tag)
    d.text((M, 220), spec["title"], font=font(110, "Black"), fill=WHITE)
    d.text((M, 340), spec.get("sub", ""), font=font(46, "ExtraBold"), fill=ICE)
    foot = Image.new("RGBA", (W, H - VB), (0, 0, 0, 0))
    d = ImageDraw.Draw(foot)
    p = puck_img(0.34)
    foot.paste(p, (M, 70), p)
    d.text((M + p.width + 14, 105), "PUCK REPORT", font=font(44, "Black"), fill=WHITE, anchor="lm")
    d.text((W - M, 105), spec.get("note", ""), font=font(28, "SemiBold"), fill=MUTED, anchor="rm")
    red_words = set(spec.get("red", ["SEASON", "LONG-TERM", "MONTHS"]))
    sprites = []
    for team, name, sub, status in rows:
        img = Image.new("RGBA", (RW, RH), (0, 0, 0, 0))
        dd = ImageDraw.Draw(img)
        dd.rounded_rectangle((0, 0, RW - 1, RH - 1), radius=22, fill=(255, 255, 255, 16),
                             outline=(255, 255, 255, 36), width=2)
        b = badge(team, 70)
        img.paste(b, (22, (RH - 70) // 2), b)
        dd.text((112, 20), name, font=font(42, "ExtraBold"), fill=WHITE)
        dd.text((112, 70), sub, font=font(28, "SemiBold"), fill=MUTED)
        dd.text((RW - 26, RH // 2), status, font=font(36, "Black"), fill=RED if status in red_words else ICE,
                anchor="rm")
        sprites.append(img)
    top_panel, bot_panel = bg.crop((0, 0, W, VT)), bg.crop((0, VB, W, H))
    n = len(rows)
    total = max(9.0, 1.0 + (n - 1) * STEP + 3.0)
    view_h, content_h = VB - VT, n * (RH + GAP)

    def fade(im, a):
        if a >= 1:
            return im
        o = im.copy()
        o.putalpha(o.getchannel("A").point(lambda v: int(v * a)))
        return o

    silent = spec["out"] + ".silent.mp4"
    ff = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s",
                           f"{W}x{H}", "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "medium", "-crf", "19",
                           "-pix_fmt", "yuv420p", silent], stdin=subprocess.PIPE)
    sp = 0.0
    for fi in range(int(total * FPS)):
        t = fi / FPS
        k = min(max((t - 1.0) / STEP, 0), n - 1)
        target = min(max(0.0, (k + 1) * (RH + GAP) + 40 - view_h), max(0.0, content_h - view_h + 40))
        sp += (target - sp) * 0.12
        f = bg.copy()
        for i, r in enumerate(sprites):
            p = ease((t - 1.0 - i * STEP) / 0.45)
            if p <= 0:
                continue
            y = int(VT + 20 + i * (RH + GAP) - sp)
            if y > VB or y + RH < VT - 40:
                continue
            f.alpha_composite(fade(r, p), (M + int((1 - p) * 100), y))
        f.alpha_composite(top_panel, (0, 0))
        f.alpha_composite(bot_panel, (0, VB))
        ha = ease(t / 0.5)
        f.alpha_composite(fade(head, ha), (0, int((1 - ha) * -30)))
        f.alpha_composite(fade(foot, ease((t - 0.6) / 0.5)), (0, VB))
        ff.stdin.write(np.asarray(f.convert("RGB")).tobytes())
    ff.stdin.close()
    ff.wait()
    mux(silent, total, spec["out"])
    return total


# ------------------------------------------------------------------ 4:5 'Last night' score card
def cmd_scores(spec, base):
    W, H, M = 1080, 1350, 60
    games = spec["games"]  # [winner, ws, loser, ls, note]
    n = len(games)
    RW = W - 2 * M
    RH = 78 if n > 8 else (110 if n > 5 else 150)
    GAP = 8 if n > 8 else 14
    Y0 = 300
    fs, bs = (32, 50) if n > 8 else ((40, 64) if n > 5 else (46, 76))

    def nick(ab):
        return NICK.get(FROM_API.get(ab, ab), ab)

    def row_base(g):
        wa, ws, la, ls = g[:4]
        note = g[4] if len(g) > 4 else ""
        img = Image.new("RGBA", (RW, RH), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.rounded_rectangle((0, 0, RW - 1, RH - 1), radius=20, fill=(255, 255, 255, 16), outline=(255, 255, 255, 36),
                            width=2)
        d.rounded_rectangle((0, 0, 8, RH - 1), radius=4, fill=ICE)
        cy = RH // 2
        b1, b2 = badge(wa, bs), badge(la, bs)
        img.paste(b1, (22, cy - bs // 2), b1)
        img.paste(b2, (RW - 18 - bs, cy - bs // 2), b2)
        room = RW // 2 - bs - 40 - int(fs * 1.6)

        def fit(txt, wt):
            z = fs
            while z > 18 and font(z, wt).getlength(txt) > room:
                z -= 2
            return font(z, wt)
        d.text((22 + bs + 16, cy), nick(wa), font=fit(nick(wa), "ExtraBold"), fill=WHITE, anchor="lm")
        d.text((RW - 18 - bs - 16, cy), nick(la), font=fit(nick(la), "SemiBold"), fill=MUTED, anchor="rm")
        if note:
            d.text((RW // 2, cy + int(fs * 0.95)), note, font=font(max(16, int(fs * 0.55)), "ExtraBold"), fill=ICE,
                   anchor="mm")
        return img

    bgf = make_bg(W, H)[200:200 + H]
    bg = Image.fromarray((bgf * 255).astype(np.uint8)).convert("RGBA")
    head = Image.new("RGBA", (W, 290), (0, 0, 0, 0))
    d = ImageDraw.Draw(head)
    tg = pill_img(spec.get("tag", "FINALS"), 30)
    head.paste(tg, (M, 56), tg)
    d.text((M, 130), spec.get("title", "LAST NIGHT"), font=font(96, "Black"), fill=WHITE)
    d.text((M, 226), spec.get("sub", "IN THE NHL"), font=font(50, "ExtraBold"), fill=ICE)
    d.text((W - M, 236), f"{n} GAMES", font=font(34, "Black"), fill=MUTED, anchor="ra")
    foot = Image.new("RGBA", (W, 90), (0, 0, 0, 0))
    d = ImageDraw.Draw(foot)
    p = puck_img(0.30)
    foot.paste(p, (M - 4, 6), p)
    d.text((M + 128, 46), "PUCK REPORT", font=font(40, "Black"), fill=WHITE, anchor="lm")
    d.text((W - M, 46), spec.get("footer", "Full recaps on the page"), font=font(30, "SemiBold"), fill=ICE, anchor="rm")
    rows = [row_base(g) for g in games]
    step = min(0.32, 3.4 / max(n, 1))

    def fade(im, a):
        if a >= 1:
            return im
        o = im.copy()
        o.putalpha(o.getchannel("A").point(lambda v: int(v * a)))
        return o

    def frame(t, final=False):
        f = bg.copy()
        pa = 1 if final else ease(t / 0.5)
        f.alpha_composite(fade(head, pa), (0, int((1 - pa) * -30)))
        sc = font(int(fs * 1.25), "Black")
        for i, (g, r) in enumerate(zip(games, rows)):
            st = 0.6 + i * step
            pp = 1 if final else ease((t - st) / 0.45)
            if pp <= 0:
                continue
            y = Y0 + i * (RH + GAP)
            x = M + int((1 - pp) * 120)
            f.alpha_composite(fade(r, pp), (x, y))
            dd = ImageDraw.Draw(f)
            sp = 1 if final else ease((t - st - 0.2) / 0.5)
            if sp > 0:
                a = int(255 * pp)
                note = g[4] if len(g) > 4 else ""
                cx, cy = x + RW // 2, y + RH // 2 - (6 if note else 0)
                dd.text((cx - 14, cy), str(round(g[1] * sp)), font=sc, fill=ICE + (a,), anchor="rm")
                dd.text((cx, cy), "–", font=sc, fill=MUTED + (a,), anchor="mm")
                dd.text((cx + 14, cy), str(round(g[3] * sp)), font=sc, fill=MUTED + (a,), anchor="lm")
        fa = 1 if final else ease((t - (0.6 + n * step + 0.4)) / 0.5)
        if fa > 0:
            f.alpha_composite(fade(foot, fa), (0, 1262))
        t0 = 0.6 + n * step + 0.8
        if not final and t0 < t < t0 + 1.0:
            sx = int(-300 + (t - t0) * (W + 600))
            sh = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            yb = Y0 + n * (RH + GAP)
            ImageDraw.Draw(sh).polygon([(sx, Y0), (sx + 90, Y0), (sx - 200, yb), (sx - 290, yb)],
                                       fill=(255, 255, 255, 22))
            f.alpha_composite(sh.filter(ImageFilter.GaussianBlur(18)))
        return f.convert("RGB")

    out = spec["out"]
    frame(0, final=True).save(os.path.splitext(out)[0] + ".png")
    total = max(9.0, 0.6 + n * step + 3.5)
    silent = out + ".silent.mp4"
    ff = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s",
                           f"{W}x{H}", "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "medium", "-crf", "18",
                           "-pix_fmt", "yuv420p", silent], stdin=subprocess.PIPE)
    for fi in range(int(total * FPS)):
        ff.stdin.write(np.asarray(frame(fi / FPS)).tobytes())
    ff.stdin.close()
    ff.wait()
    mux(silent, total, out)
    return total


# ------------------------------------------------------------------ data: official NHL stats feed
NHL_API = "https://api-web.nhle.com/v1"
API_CODES = {"NJD": "NJ", "LAK": "LA", "SJS": "SJ", "TBL": "TB"}


def _get(url):
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": "PuckReport/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def _code(a):
    return API_CODES.get(a, a)


def _nm(x):
    return (x or {}).get("default", "") if isinstance(x, dict) else (x or "")


def fetch(date, out_path):
    """Pull one night's finals (ET date) into a compact slate JSON for writing specs."""
    sc = _get(f"{NHL_API}/score/{date}")
    games = []
    for g in sc.get("games", []):
        a, h = g["awayTeam"], g["homeTeam"]
        st = g.get("gameState", "")
        item = {"id": g["id"], "state": st, "final": st in ("OFF", "FINAL"), "start_utc": g.get("startTimeUTC"),
                "away": _code(a["abbrev"]), "home": _code(h["abbrev"]),
                "away_score": a.get("score"), "home_score": h.get("score"),
                "away_sog": a.get("sog"), "home_sog": h.get("sog"),
                "finish": (g.get("gameOutcome") or {}).get("lastPeriodType", "REG"), "goals": []}
        for gl in g.get("goals", []):
            item["goals"].append({
                "period": (gl.get("periodDescriptor") or {}).get("periodType", "REG") + str(gl.get("period", "")),
                "time": gl.get("timeInPeriod"), "team": _code(gl.get("teamAbbrev", "")),
                "scorer": f"{_nm(gl.get('firstName'))} {_nm(gl.get('lastName'))}".strip() or _nm(gl.get("name")),
                "assists": [f"{_nm(x.get('firstName'))} {_nm(x.get('lastName'))}".strip() or _nm(x.get("name"))
                            for x in gl.get("assists", [])],
                "strength": gl.get("strength"), "modifier": gl.get("goalModifier"),
                "score_after": f"{gl.get('awayScore')}-{gl.get('homeScore')}"})
        if item["final"]:
            try:  # team stats (hits, faceoffs, power play, blocks)
                rr = _get(f"{NHL_API}/gamecenter/{g['id']}/right-rail")
                item["team_stats"] = {t.get("category"): [t.get("awayValue"), t.get("homeValue")]
                                      for t in rr.get("teamGameStats", [])}
                item["three_stars"] = [f"{_nm(x.get('name'))} ({_code(x.get('teamAbbrev', ''))})"
                                       for x in (rr.get("threeStars") or [])]
            except Exception as e:
                item["team_stats_error"] = str(e)
            try:  # goalies
                bx = _get(f"{NHL_API}/gamecenter/{g['id']}/boxscore")
                pg = bx.get("playerByGameStats", {})
                item["goalies"] = {side: [{"name": _nm(x.get("name")), "saves_shots": x.get("saveShotsAgainst"),
                                           "decision": x.get("decision"), "toi": x.get("toi")}
                                          for x in pg.get(side + "Team", {}).get("goalies", []) if x.get("toi") not in
                                          (None, "00:00")]
                                   for side in ("away", "home")}
            except Exception as e:
                item["goalies_error"] = str(e)
        games.append(item)
    out = {"date": date, "games": games}
    try:
        stn = _get(f"{NHL_API}/standings/now")
        out["records"] = {_code(_nm(t.get("teamAbbrev"))): f"{t.get('wins')}-{t.get('losses')}-{t.get('otLosses')}"
                          for t in stn.get("standings", [])}
    except Exception as e:
        out["records_error"] = str(e)
    json.dump(out, open(out_path, "w"), indent=1)
    fin = sum(1 for g in games if g["final"])
    print(f"fetched {len(games)} games ({fin} final) for {date} -> {out_path}")


# ------------------------------------------------------------------ checks + setup
def contact(video, out, n=12, width=270):
    """Grab n evenly spaced frames into one sheet for a visual check."""
    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", video],
                               capture_output=True, text=True).stdout.strip() or 0)
    ims = []
    for i in range(n):
        t = dur * (i + 0.6) / n
        f = f"{out}.{i}.png"
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-ss", str(t), "-i", video, "-frames:v", "1", "-vf",
                        f"scale={width}:-1", f])
        if os.path.exists(f):
            ims.append(Image.open(f).copy())
            os.remove(f)
    if not ims:
        return
    w, h = ims[0].size
    cols = 6
    c = Image.new("RGB", (w * cols, h * ((len(ims) + cols - 1) // cols)))
    for i, im in enumerate(ims):
        c.paste(im, ((i % cols) * w, (i // cols) * h))
    c.save(out)


def setup():
    os.makedirs(LOGOS, exist_ok=True)
    if len([f for f in os.listdir(LOGOS) if f.endswith(".png")]) >= 32:
        print("logos already present")
        return
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "--break-system-packages", "cairosvg"], check=False)
    work = os.path.join(HERE, "_logo_build")
    os.makedirs(work, exist_ok=True)
    subprocess.run("npm init -y >/dev/null && npm install --silent react@18.3.1 react-dom@18.3.1 "
                   "react-nhl-logos@1.4.1", shell=True, cwd=work, check=True)
    js = ('const R=require("react"),{renderToStaticMarkup:s}=require("react-dom/server"),L=require("react-nhl-logos"),'
          'fs=require("fs");fs.mkdirSync("svg",{recursive:true});for(const k of Object.keys(L)){if(typeof L[k]!=="function")'
          'continue;fs.writeFileSync(`svg/${k}.svg`,s(R.createElement(L[k],{size:512})))}')
    with open(os.path.join(work, "x.cjs"), "w") as fh:
        fh.write(js)
    subprocess.run(["node", "x.cjs"], cwd=work, check=True, stderr=subprocess.DEVNULL)
    import cairosvg
    for f in os.listdir(os.path.join(work, "svg")):
        cairosvg.svg2png(url=os.path.join(work, "svg", f), write_to=os.path.join(LOGOS, f[:-4] + ".png"),
                         output_width=512, output_height=512)
    print("logos:", len(os.listdir(LOGOS)))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "help"
    if cmd == "setup":
        setup()
    elif cmd == "fetch":
        fetch(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else f"slate_{sys.argv[2]}.json")
    elif cmd in ("scores", "recap", "reel"):
        path = sys.argv[2]
        base = os.path.dirname(os.path.abspath(path))
        spec = json.load(open(path))
        if not os.path.isabs(spec["out"]):
            spec["out"] = os.path.join(base, spec["out"])
        dur = {"scores": cmd_scores, "recap": cmd_recap, "reel": cmd_reel}[cmd](spec, base)
        contact(spec["out"], os.path.splitext(spec["out"])[0] + "_check.png")
        print(f"done {spec['out']} {dur:.1f}s  (check sheet: {os.path.splitext(spec['out'])[0]}_check.png)")
    elif cmd == "contact":
        contact(sys.argv[2], sys.argv[3])
    else:
        print(__doc__)
