"""Draws the integration's icon: a square base-station box with a sound-wave badge.

    python3 assets/make_icons.py   # writes icon.svg, dark_icon.svg and the brand PNGs

Needs rsvg-convert (brew install librsvg).
"""
import pathlib
import subprocess

HERE = pathlib.Path(__file__).parent
BRAND = HERE.parent / 'custom_components' / 'airport_express' / 'brand'


def svg(body, edge, face, led):
    cx, cy, rb, gap = 388, 388, 104, 18
    # Three arcs fanning out to the right of a small speaker dot.
    arcs = ''.join(
        f'<path d="M{cx - 30 + r * 0.6:.1f},{cy - r * 0.8:.1f} '
        f'A{r},{r} 0 0 1 {cx - 30 + r * 0.6:.1f},{cy + r * 0.8:.1f}"/>'
        for r in (30, 56, 82))
    # The badge cuts a transparent ring out of the box, so it reads on any background.
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">
  <mask id="cut">
    <rect width="512" height="512" fill="#fff"/>
    <circle cx="{cx}" cy="{cy}" r="{rb + gap}" fill="#000"/>
  </mask>
  <g mask="url(#cut)">
    <rect x="36" y="36" width="400" height="400" rx="72" fill="{body}"
          stroke="{edge}" stroke-width="20"/>
    <rect x="92" y="92" width="288" height="288" rx="44" fill="{face}"/>
    <circle cx="236" cy="236" r="22" fill="{led}"/>
  </g>
  <circle cx="{cx}" cy="{cy}" r="{rb}" fill="#1E88E5"/>
  <circle cx="{cx - 40}" cy="{cy}" r="13" fill="#FFFFFF"/>
  <g fill="none" stroke="#FFFFFF" stroke-width="15" stroke-linecap="round">{arcs}</g>
</svg>
'''


VARIANTS = {
    '': svg(body='#ECEFF1', edge='#90A4AE', face='#CFD8DC', led='#43A047'),
    'dark_': svg(body='#CFD8DC', edge='#ECEFF1', face='#B0BEC5', led='#66BB6A'),
}
BRAND.mkdir(exist_ok=True)
for prefix, text in VARIANTS.items():
    source = HERE / f'{prefix}icon.svg'
    source.write_text(text)
    for suffix, size in (('', 256), ('@2x', 512)):
        subprocess.run(['rsvg-convert', '-w', str(size), '-h', str(size), '-o',
                        BRAND / f'{prefix}icon{suffix}.png', source], check=True)
print('wrote', sorted(p.name for p in BRAND.iterdir()))
