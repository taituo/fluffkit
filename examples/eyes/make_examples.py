"""Generate the example eye animations as SVG frames (original art, MIT).

    python3 examples/eyes/make_examples.py      -> examples/eyes/<name>/frame_*.svg

Use them with:  fluffkit.py pack items.txt --eyes examples/eyes/thinking/*.svg
"""
import math
from pathlib import Path

HERE = Path(__file__).resolve().parent


def eye(pupil_dx=0.0, pupil_dy=0.0, lid=0.0, iris="#3aa0ff", extra=""):
    """A friendly cartoon eye. lid: 0 open .. 1 closed."""
    lid_h = 128 * lid
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="128" height="128" viewBox="0 0 128 128">
  <rect width="128" height="128" fill="#fffaf0"/>
  <circle cx="{64 + pupil_dx:.1f}" cy="{64 + pupil_dy:.1f}" r="40" fill="{iris}"/>
  <circle cx="{64 + pupil_dx:.1f}" cy="{64 + pupil_dy:.1f}" r="20" fill="#141414"/>
  <circle cx="{72 + pupil_dx:.1f}" cy="{54 + pupil_dy:.1f}" r="7" fill="#ffffff"/>
  {extra}
  <rect width="128" height="{lid_h:.1f}" fill="#7a4fb5"/>
</svg>'''


def thinking(n=8):
    """Pupil circles around while a little orbit dot spins: 'Furby is thinking'."""
    out = []
    for i in range(n):
        a = 2 * math.pi * i / n
        dot = f'<circle cx="{64 + 54 * math.cos(-a):.1f}" cy="{64 + 54 * math.sin(-a):.1f}" r="6" fill="#ffb000"/>'
        out.append(eye(14 * math.cos(a), 14 * math.sin(a), 0, "#3aa0ff", dot))
    return out


def blink():
    lids = [0, 0, 0, 0, 0.5, 1, 0.5, 0]
    return [eye(0, 0, l) for l in lids]


def hearts(n=6):
    out = []
    for i in range(n):
        s = 1 + 0.12 * math.sin(2 * math.pi * i / n)
        out.append(f'''<svg xmlns="http://www.w3.org/2000/svg" width="128" height="128" viewBox="0 0 128 128">
  <rect width="128" height="128" fill="#fffaf0"/>
  <g transform="translate(64 66) scale({s:.3f}) translate(-64 -66)">
    <path d="M64 104 C20 74 14 44 36 32 C50 25 60 33 64 42 C68 33 78 25 92 32 C114 44 108 74 64 104 Z" fill="#ff3b6b"/>
    <ellipse cx="46" cy="46" rx="8" ry="5" fill="#ffd0dc"/>
  </g>
</svg>''')
    return out


STARS = [(12, 14), (30, 100), (104, 22), (116, 96), (20, 60), (98, 116), (60, 8), (8, 120), (120, 56)]


def spaceknight():
    """A space knight's helmet eye: an angular red visor that glows with its breathing, then a red
    energy blade sweeps across. Stars twinkle behind. The right eye mirrors it into a helmet."""
    def frame(glow, blade=None, twinkle=0):
        stars = "".join(f'<circle cx="{x}" cy="{y}" r="{1.6 if (k + twinkle) % 3 else 2.6}" fill="#ffffff"/>'
                        for k, (x, y) in enumerate(STARS))
        r = int(150 + 105 * glow)
        visor = (f'<polygon points="14,58 64,40 116,52 104,80 60,86 22,76" fill="#1a1a1a" stroke="#3c3c3c" stroke-width="4"/>'
                 f'<polygon points="30,62 64,52 100,58 92,72 62,76 34,70" fill="rgb({r},{int(20 * glow)},{int(10 * glow)})"/>'
                 f'<polygon points="44,62 64,57 84,60 78,66 62,68 48,66" fill="rgb(255,{int(90 + 120 * glow)},{int(60 + 100 * glow)})"/>')
        saber = ""
        if blade is not None:   # 0..1: the blade's tip position along the diagonal
            x2, y2 = 8 + 112 * blade, 120 - 112 * blade
            saber = (f'<line x1="8" y1="120" x2="{x2:.0f}" y2="{y2:.0f}" stroke="#ff2020" stroke-width="14" stroke-linecap="round"/>'
                     f'<line x1="8" y1="120" x2="{x2:.0f}" y2="{y2:.0f}" stroke="#ffd8d8" stroke-width="5" stroke-linecap="round"/>'
                     f'<rect x="0" y="112" width="18" height="16" fill="#9a9a9a"/>')
        return f'''<svg xmlns="http://www.w3.org/2000/svg" width="128" height="128" viewBox="0 0 128 128">
  <rect width="128" height="128" fill="#05060f"/>
  {stars}
  {visor}
  {saber}
</svg>'''
    return [frame(0.15), frame(0.55, twinkle=1), frame(1.0, twinkle=2), frame(0.55),
            frame(0.3, 0.35, 1), frame(0.6, 0.75, 2), frame(1.0, 1.0), frame(0.4, twinkle=1)]


if __name__ == "__main__":
    for name, frames in (("thinking", thinking()), ("blink", blink()), ("hearts", hearts()),
                         ("spaceknight", spaceknight())):
        d = HERE / name
        d.mkdir(exist_ok=True)
        for i, svg in enumerate(frames):
            (d / f"frame_{i:02d}.svg").write_text(svg)
        print(d, len(frames), "frames")
