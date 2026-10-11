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


if __name__ == "__main__":
    for name, frames in (("thinking", thinking()), ("blink", blink()), ("hearts", hearts())):
        d = HERE / name
        d.mkdir(exist_ok=True)
        for i, svg in enumerate(frames):
            (d / f"frame_{i:02d}.svg").write_text(svg)
        print(d, len(frames), "frames")
