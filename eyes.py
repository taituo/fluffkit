"""
Custom eye animations for Furby Connect DLC packs.

Formats (see FORMAT.md):
  PAL  palettes of 64 x u16: RGB555, bit 15 set = transparent
  CEL  64x64 images, 6-bit palette indices, 3 bytes per 4 pixels (3072 bytes per cel)
  SPR  16 frame playlists; a frame = 4 x (cel index, palette ref) for the TL, TR, BL, BR
       quarters of one 128x128 eye, terminated by 0xFFFF

Injection follows the Context IS demo that ran on a real Furby (ctxis/Furby demo.py, 2017):
  - the DLC's own eye animation (sequence word 0x8401) composites playlists 8/9 (base),
    10/11 and 12/13 (overlays), 38 frames each;
  - base and middle layers are blanked to a white cel, the custom animation goes into
    playlist 13 (left eye, palette 4, ref 5362) and 12 (right eye, palette 5, ref 6386);
  - sequences that should show it get [type, playlist, motor/lips..., 0x8401, 0].
"""
from __future__ import annotations

import shutil
import struct
import subprocess
import tempfile
from pathlib import Path

CEL_BYTES = 3072
FRAMES_PER_PLAYLIST = 38
EYE_ANIM_WORD = 0x8401
# proven mapping from the Context IS demo
LEFT_PLAYLIST, RIGHT_PLAYLIST = 13, 12
LEFT_PAL, RIGHT_PAL = 4, 5
LEFT_REF, RIGHT_REF = 5362, 6386
BASE_REF = 4338
BLANK_PLAYLISTS = (8, 9, 10, 11)
WHITE_SOURCE_CEL = 17        # a plain white cel in tu003410, copied to index 1 (as in the demo)

# playlist index -> sequence index for tu003410 (input-75 actions), from its XLS/SEQ tables
APL_TO_SEQ = {16: 16, 17: 21, 18: 18, 19: 22, 20: 23, 21: 17, 22: 19, 23: 20, 0: 0, 1: 3, 2: 2, 3: 4,
              4: 5, 5: 1, 24: 51, 25: 58, 26: 53, 27: 54, 28: 55, 29: 56, 30: 52, 31: 57, 32: 43,
              33: 48, 34: 45, 35: 49, 36: 50, 37: 44, 38: 46, 39: 47, 6: 8, 7: 13, 8: 10, 9: 14,
              10: 15, 11: 9, 12: 11, 13: 12, 40: 24, 41: 25, 42: 26, 43: 28, 44: 29, 45: 27, 46: 30,
              47: 31, 48: 32, 49: 33, 50: 35, 51: 36, 52: 34, 53: 37, 54: 38, 55: 39, 14: 6, 56: 41,
              57: 42, 58: 40, 15: 7, 59: 59}


# ------------------------------------------------------------------ cels and palettes

def decode_cel(b: bytes) -> list[int]:
    px = []
    for i in range(0, CEL_BYTES, 3):
        a, c, d = b[i], b[i + 1], b[i + 2]
        px += [a >> 2, ((a & 3) << 4) | (c >> 4), ((c & 15) << 2) | (d >> 6), d & 63]
    return px


def encode_cel(px: list[int]) -> bytes:
    assert len(px) == 64 * 64 and max(px) < 64
    out = bytearray()
    for i in range(0, len(px), 4):
        p0, p1, p2, p3 = px[i:i + 4]
        out += bytes([(p0 << 2) | (p1 >> 4), ((p1 & 15) << 4) | (p2 >> 2), ((p2 & 3) << 6) | p3])
    return bytes(out)


def rgb555(r: int, g: int, b: int, transparent: bool = False) -> int:
    return (0x8000 if transparent else 0) | ((r >> 3) << 10) | ((g >> 3) << 5) | (b >> 3)


def from555(w: int) -> tuple[int, int, int, int]:
    return ((w >> 10) & 31) << 3, ((w >> 5) & 31) << 3, (w & 31) << 3, 0 if w & 0x8000 else 255


def parse_pal(raw: bytes) -> list[list[int]]:
    n = len(raw) // 128
    return [list(struct.unpack_from("<64H", raw, i * 128)) for i in range(n)]


def build_pal(pals: list[list[int]]) -> bytes:
    return b"".join(struct.pack("<64H", *p) for p in pals)


# ------------------------------------------------------------------ SPR (frames patched in place)

class Sprites:
    T1_ENTRY = 14   # u16 framecount, u32 t2 offset (words), u32 layer, u32 terminator

    def __init__(self, raw: bytes):
        self.raw = bytearray(raw)
        self.playlists = []  # list of lists of byte offsets of frames
        for w in range(16):
            n, t2, layer, term = struct.unpack_from("<HIII", raw, w * self.T1_ENTRY)
            offs = struct.unpack_from(f"<{n}I", raw, t2 * 2)
            self.playlists.append([o * 2 for o in offs])

    def frame(self, off: int) -> list[int]:
        return list(struct.unpack_from("<9H", self.raw, off))

    def set_frame(self, off: int, quarters: list[tuple[int, int]]) -> None:
        words = [x for q in quarters for x in q] + [0xFFFF]
        struct.pack_into("<9H", self.raw, off, *words)


# ------------------------------------------------------------------ SEQ

def parse_seq(raw: bytes) -> list[list[int]]:
    n = struct.unpack_from("<H", raw, 0)[0]
    offs = struct.unpack_from(f"<{n}I", raw, 6)
    seqs = []
    for o in offs:
        p, s = o * 2, []
        while True:
            w = struct.unpack_from("<H", raw, p)[0]
            s.append(w)
            p += 2
            if w == 0:
                break
        seqs.append(s)
    return seqs


def build_seq(seqs: list[list[int]], entry_len: int = 6) -> bytes:
    n = len(seqs)
    off = 2 * n + 3
    offs = []
    for s in seqs:
        offs.append(off)
        off += len(s)
    return struct.pack(f"<HI{n}I", n, entry_len, *offs) + b"".join(struct.pack(f"<{len(s)}H", *s) for s in seqs)


def with_custom_eyes(seq: list[int]) -> list[int]:
    """[type, playlist, motor/lips words..., 0x8401, 0] (the demo's form, generalised)."""
    keep = [w for w in seq[2:-1] if (w >> 12) in (0xC, 0xE)]
    return seq[:2] + keep + [EYE_ANIM_WORD, 0]


# ------------------------------------------------------------------ images

def load_frames(paths: list[str], max_frames: int, background=(255, 255, 255)):
    """Load PNG/GIF/WebP/JPG/SVG (animated GIF/WebP give several frames) as 128x128 RGB images."""
    from PIL import Image, ImageSequence
    frames = []
    for p in paths:
        p = str(Path(p).expanduser())
        if p.lower().endswith(".svg"):
            frames.append(_load_svg(p))
            continue
        with Image.open(p) as im:
            for fr in ImageSequence.Iterator(im):
                frames.append(fr.convert("RGBA").copy())
    if not frames:
        raise ValueError("no frames")
    if len(frames) > max_frames:  # keep evenly spaced frames
        frames = [frames[round(i * (len(frames) - 1) / (max_frames - 1))] for i in range(max_frames)] \
            if max_frames > 1 else frames[:1]
    out = []
    for fr in frames:
        fr.thumbnail((128, 128), Image.LANCZOS)
        canvas = Image.new("RGBA", (128, 128), background + (255,))
        canvas.alpha_composite(fr, ((128 - fr.width) // 2, (128 - fr.height) // 2))
        out.append(canvas.convert("RGB"))
    return out


def _load_svg(path: str):
    from PIL import Image
    with tempfile.TemporaryDirectory() as td:
        png = Path(td) / "svg.png"
        for cmd in (["resvg", "-w", "128", "-h", "128", path, str(png)],
                    ["rsvg-convert", "-w", "128", "-h", "128", "-o", str(png), path],
                    ["ffmpeg", "-v", "error", "-y", "-i", path, "-frames:v", "1",
                     "-vf", "scale=128:128:force_original_aspect_ratio=decrease", str(png)]):
            if shutil.which(cmd[0]) and subprocess.run(cmd, capture_output=True).returncode == 0 and png.exists():
                return Image.open(png).convert("RGBA").copy()
    raise RuntimeError(f"cannot rasterise {path}: install resvg, rsvg-convert, or ffmpeg with librsvg")


def quantise(frames, colours: int = 64):
    """One shared <=64-colour palette for all frames of an eye. Returns (index frames, RGB palette)."""
    from PIL import Image
    strip = Image.new("RGB", (128, 128 * len(frames)))
    for i, f in enumerate(frames):
        strip.paste(f, (0, 128 * i))
    q = strip.quantize(colors=colours, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    pal = q.getpalette()[:3 * colours]
    pal += [255] * (3 * colours - len(pal))
    rgb = [tuple(pal[3 * i:3 * i + 3]) for i in range(colours)]
    data = list(q.getdata())
    idx = [data[128 * 128 * i:128 * 128 * (i + 1)] for i in range(len(frames))]
    return idx, rgb


def quarters(idx_frame: list[int]) -> list[list[int]]:
    """128x128 index image -> TL, TR, BL, BR 64x64 index lists."""
    out = []
    for qy, qx in ((0, 0), (0, 64), (64, 0), (64, 64)):
        out.append([idx_frame[(qy + y) * 128 + qx + x] for y in range(64) for x in range(64)])
    return out


# ------------------------------------------------------------------ inject

def inject(D, left_paths: list[str], right_paths: list[str] | None, mirror: bool = True,
           max_frames: int = 8) -> dict:
    """Put a custom eye animation into DLC D (dlcpack.DLC). Returns info for previews/tests."""
    from PIL import ImageOps
    left = load_frames(left_paths, max_frames)
    right = load_frames(right_paths, max_frames) if right_paths else \
        [ImageOps.mirror(f) for f in left] if mirror else list(left)

    stock_cels = D.raw["CEL"]
    cels = [stock_cels[:CEL_BYTES],
            stock_cels[WHITE_SOURCE_CEL * CEL_BYTES:(WHITE_SOURCE_CEL + 1) * CEL_BYTES]]
    index_of: dict[bytes, int] = {}

    def add(px: list[int]) -> int:
        b = encode_cel(px)
        if b not in index_of:
            index_of[b] = len(cels)
            cels.append(b)
        return index_of[b]

    pals = parse_pal(D.raw["PAL"])
    spr = Sprites(D.raw["SPR"])
    info = {}
    for name, frames, playlist, pal_i, ref in (("left", left, LEFT_PLAYLIST, LEFT_PAL, LEFT_REF),
                                               ("right", right, RIGHT_PLAYLIST, RIGHT_PAL, RIGHT_REF)):
        idx_frames, rgb = quantise(frames)
        pals[pal_i] = [rgb555(*c) for c in rgb]
        frame_cels = [[add(q) for q in quarters(f)] for f in idx_frames]
        n = len(frame_cels)
        for k, off in enumerate(spr.playlists[playlist]):
            fc = frame_cels[min(n - 1, k * n // len(spr.playlists[playlist]))]
            spr.set_frame(off, [(c, ref) for c in fc])
        info[name] = {"frames": n, "palette": rgb, "index_frames": idx_frames}
    for pl in BLANK_PLAYLISTS:
        for off in spr.playlists[pl]:
            spr.set_frame(off, [(1, BASE_REF)] * 4)

    D.raw["CEL"] = b"".join(cels)
    D.raw["PAL"] = build_pal(pals)
    D.raw["SPR"] = bytes(spr.raw)
    info["cels"] = len(cels)
    return info


def mark_phrase(D, apl_index: int) -> None:
    """Make the sequence of a phrase slot show the custom eye animation."""
    seqs = parse_seq(D.raw["SEQ"])
    entry_len = struct.unpack_from("<I", D.raw["SEQ"], 2)[0]
    s = APL_TO_SEQ[apl_index]
    seqs[s] = with_custom_eyes(seqs[s])
    D.raw["SEQ"] = build_seq(seqs, entry_len)


# ------------------------------------------------------------------ render (preview / check)

def render_eye(D, playlist: int, ref_to_pal: dict[int, int], frame_no: int):
    """Render one 128x128 frame of a playlist from the DLC's own data (RGBA)."""
    from PIL import Image
    pals = parse_pal(D.raw["PAL"])
    spr = Sprites(D.raw["SPR"])
    words = spr.frame(spr.playlists[playlist][frame_no])
    im = Image.new("RGBA", (128, 128))
    for q, (qy, qx) in enumerate(((0, 0), (0, 64), (64, 0), (64, 64))):
        cel, ref = words[2 * q], words[2 * q + 1]
        px = decode_cel(D.raw["CEL"][cel * CEL_BYTES:(cel + 1) * CEL_BYTES])
        pal = [from555(w) for w in pals[ref_to_pal.get(ref, 0)]]
        tile = Image.new("RGBA", (64, 64))
        tile.putdata([pal[p] for p in px])
        im.paste(tile, (qx, qy))
    return im


def preview_gif(D, out: str, ms: int = 80) -> None:
    """Both custom eyes side by side on white, as Furby would composite them (white base layer)."""
    from PIL import Image
    refs = {LEFT_REF: LEFT_PAL, RIGHT_REF: RIGHT_PAL}
    frames = []
    for k in range(FRAMES_PER_PLAYLIST):
        canvas = Image.new("RGBA", (128 * 2 + 24, 128 + 16), (40, 40, 40, 255))
        for i, pl in enumerate((LEFT_PLAYLIST, RIGHT_PLAYLIST)):
            eye = Image.new("RGBA", (128, 128), (255, 255, 255, 255))
            eye.alpha_composite(render_eye(D, pl, refs, k))
            canvas.paste(eye, (8 + i * (128 + 8), 8))
        frames.append(canvas.convert("P", palette=Image.Palette.ADAPTIVE))
    frames[0].save(out, save_all=True, append_images=frames[1:], duration=ms, loop=0)
