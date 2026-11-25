"""Generate the README banner and dividers (dark and light) as animated SVG.

Lettering is converted to outlines from Luckiest Guy (Apache 2.0) so GitHub's
image proxy, which loads no web fonts, still shows the right letterforms.
Usage: python scripts/make_readme_art.py path/to/LuckiestGuy-Regular.ttf
"""

from __future__ import annotations

import sys
from pathlib import Path

from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"


def text_path(font: TTFont, text: str, size: float, x: float, y: float, anchor: str = "middle", track: float = 0.0):
    gs = font.getGlyphSet()
    cmap = font.getBestCmap()
    upm = font["head"].unitsPerEm
    s = size / upm
    hmtx = font["hmtx"]
    names = [cmap.get(ord(ch)) for ch in text]
    width = sum((hmtx[n][0] if n else upm * 0.3) * s + track for n in names) - track
    cx = x - (width / 2 if anchor == "middle" else (width if anchor == "end" else 0))
    pen = SVGPathPen(gs)
    for n in names:
        if n:
            tp = TransformPen(pen, (s, 0, 0, -s, cx, y))
            gs[n].draw(tp)
            cx += hmtx[n][0] * s + track
        else:
            cx += upm * 0.3 * s + track
    return pen.getCommands(), width


THEMES = {
    "dark": {"bg": "#140D08", "bg2": "#1E140D", "ink": "#050302", "grid": "#C0C6CC", "grid_op": ".07", "hud": "#8A9299",
             "hud_hi": "#F5B700", "sub": "#C0C6CC", "outline": "#050302"},
    "light": {"bg": "#FBF6EC", "bg2": "#F1E7D3", "ink": "#2A1C12", "grid": "#2A1C12", "grid_op": ".08", "hud": "#6B5A45",
              "hud_hi": "#A86F00", "sub": "#3A2819", "outline": "#2A1C12"},
}


def banner(font: TTFont, theme: str) -> str:
    t = THEMES[theme]
    W, Hh = 1280, 420
    line1, w1 = text_path(font, "METAL FUTURE", 118, W / 2, 196, track=4)
    line2, w2 = text_path(font, "FORECAST", 118, W / 2, 318, track=10)
    sub, _ = text_path(font, "HYPERLIQUID  //  XYZ:GOLD  +  XYZ:SILVER  //  LONG OR SHORT", 20, W / 2, 372, track=3)
    l1x0 = W / 2 - w1 / 2
    l2x0 = W / 2 - w2 / 2
    drips = []
    spots = [(l1x0 + w1 * f, 186, h, wd, d) for f, h, wd, d in ((.06, 40, 16, 0), (.19, 30, 12, 1.6), (.37, 54, 18, 3.1), (.58, 28, 12, .8), (.74, 46, 16, 2.4), (.93, 34, 13, 4))]
    spots += [(l2x0 + w2 * f, 308, h, wd, d) for f, h, wd, d in ((.12, 52, 18, 1.2), (.33, 36, 13, 3.6), (.55, 62, 20, .4), (.81, 42, 15, 2.8))]
    for i, (x, y, h, wd, d) in enumerate(spots):
        grad = "url(#g)" if i % 3 else "url(#s)"
        drips.append(
            f'<rect x="{x:.1f}" y="{y}" width="{wd}" height="{h}" rx="{wd / 2}" fill="{grad}">'
            f'<animate attributeName="height" values="{h * .4:.0f};{h * 1.2:.0f};{h:.0f};{h * .4:.0f}" dur="{6 + i % 4 * 1.3:.1f}s" begin="-{d}s" repeatCount="indefinite"/></rect>')
    hud = []
    # Corner brackets
    for (x, y, sx, sy) in ((28, 28, 1, 1), (W - 28, 28, -1, 1), (28, Hh - 28, 1, -1), (W - 28, Hh - 28, -1, -1)):
        hud.append(f'<path d="M{x} {y + sy * 38} V{y} H{x + sx * 38}" fill="none" stroke="{t["hud_hi"]}" stroke-width="3"/>')
    # Readouts
    mono = "font-family='ui-monospace,SFMono-Regular,Menlo,Consolas,monospace' font-size='13' letter-spacing='2'"
    hud.append(f'<text x="80" y="54" fill="{t["hud"]}" {mono}>SIG/AU-AG  //  COHORT TOP-500  //  P(LONG) 0.60 · 0.40</text>')
    hud.append(f'<text x="{W - 80}" y="54" text-anchor="end" fill="{t["hud"]}" {mono}>FOUNDRY ONLINE <tspan fill="{t["hud_hi"]}">●</tspan></text>')
    hud.append(f'<text x="80" y="{Hh - 44}" fill="{t["hud"]}" {mono}>DEX XYZ · 30 MIN</text>')
    hud.append(f'<text x="{W - 80}" y="{Hh - 44}" text-anchor="end" fill="{t["hud"]}" {mono}>NOT ADVICE</text>')
    # Tick ruler
    ticks = "".join(f'<line x1="{x}" y1="{Hh - 70}" x2="{x}" y2="{Hh - 70 + (10 if x % 80 == 0 else 5)}" stroke="{t["hud"]}" stroke-width="1" opacity=".6"/>' for x in range(80, W - 79, 16))
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {Hh}" width="{W}" height="{Hh}" role="img" aria-label="Metal Future Forecast: molten gold and silver lettering on a sci-fi HUD">
<defs>
  <linearGradient id="g" x1="0" y1="0" x2="1" y2="0" spreadMethod="reflect">
    <stop offset="0" stop-color="#FFE08A"/><stop offset=".3" stop-color="#F5B700"/><stop offset=".55" stop-color="#FF5A1F"/><stop offset=".8" stop-color="#F5B700"/><stop offset="1" stop-color="#C8901A"/>
    <animate attributeName="x1" values="0;-1;0" dur="9s" repeatCount="indefinite"/><animate attributeName="x2" values="1;0;1" dur="9s" repeatCount="indefinite"/>
  </linearGradient>
  <linearGradient id="s" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0" stop-color="#FFFFFF"/><stop offset=".42" stop-color="#C0C6CC"/><stop offset=".55" stop-color="#8A9299"/><stop offset="1" stop-color="#EEF1F4"/>
  </linearGradient>
  <linearGradient id="sweep" x1="0" y1="0" x2="1" y2="0">
    <stop offset="0" stop-color="#FFFFFF" stop-opacity="0"/><stop offset=".5" stop-color="#FFFFFF" stop-opacity=".55"/><stop offset="1" stop-color="#FFFFFF" stop-opacity="0"/>
  </linearGradient>
  <pattern id="grid" width="32" height="32" patternUnits="userSpaceOnUse"><path d="M32 0 H0 V32" fill="none" stroke="{t["grid"]}" stroke-opacity="{t["grid_op"]}" stroke-width="1"/></pattern>
  <radialGradient id="glow" cx=".5" cy=".55" r=".6"><stop offset="0" stop-color="#F5B700" stop-opacity=".22"/><stop offset="1" stop-color="#F5B700" stop-opacity="0"/></radialGradient>
  <filter id="goo"><feGaussianBlur stdDeviation="5"/><feColorMatrix values="1 0 0 0 0  0 1 0 0 0  0 0 1 0 0  0 0 0 20 -8"/></filter>
  <path id="l1" d="{line1}"/><path id="l2" d="{line2}"/>
  <clipPath id="letters"><use href="#l1"/><use href="#l2"/></clipPath>
</defs>
<rect width="{W}" height="{Hh}" rx="22" fill="{t["bg"]}"/>
<rect width="{W}" height="{Hh}" rx="22" fill="url(#grid)"/>
<rect width="{W}" height="{Hh}" rx="22" fill="url(#glow)"/>
<line x1="60" x2="{W - 60}" y1="0" y2="0" stroke="{t["hud_hi"]}" stroke-opacity=".35" stroke-width="2"><animate attributeName="y1" values="70;350;70" dur="7s" repeatCount="indefinite"/><animate attributeName="y2" values="70;350;70" dur="7s" repeatCount="indefinite"/></line>
{"".join(hud)}
{ticks}
<g filter="url(#goo)"><use href="#l1" fill="url(#g)"/><use href="#l2" fill="url(#g)"/>{"".join(drips)}</g>
<use href="#l1" fill="url(#g)" stroke="{t["outline"]}" stroke-width="5" stroke-linejoin="round" paint-order="stroke"/>
<use href="#l2" fill="url(#s)" stroke="{t["outline"]}" stroke-width="5" stroke-linejoin="round" paint-order="stroke"/>
<g clip-path="url(#letters)"><rect x="-200" y="80" width="160" height="260" fill="url(#sweep)" transform="skewX(-18)"><animate attributeName="x" values="-300;1500" dur="5.5s" repeatCount="indefinite"/></rect></g>
<path d="{sub}" fill="{t["sub"]}"/>
</svg>
'''


def divider(theme: str) -> str:
    t = THEMES[theme]
    W, Hh = 1280, 48
    wave = "M0 24 " + " ".join(f"Q {x + 40} {6 if (x // 80) % 2 == 0 else 42} {x + 80} 24" for x in range(0, W + 160, 80))
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {Hh}" width="{W}" height="{Hh}" role="img" aria-label="">
<defs><linearGradient id="l" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#C0C6CC"/><stop offset=".35" stop-color="#F5B700"/><stop offset=".5" stop-color="#FF5A1F"/><stop offset=".65" stop-color="#F5B700"/><stop offset="1" stop-color="#C0C6CC"/></linearGradient></defs>
<g><path d="{wave}" fill="none" stroke="url(#l)" stroke-width="5" stroke-linecap="round"><animateTransform attributeName="transform" type="translate" values="0 0;-160 0" dur="6s" repeatCount="indefinite"/></path></g>
<circle cx="640" cy="24" r="9" fill="{t["bg"]}" stroke="{t["hud_hi"]}" stroke-width="3"/><circle cx="640" cy="24" r="3" fill="{t["hud_hi"]}"><animate attributeName="r" values="2;5;2" dur="2.4s" repeatCount="indefinite"/></circle>
</svg>
'''


def main():
    font = TTFont(sys.argv[1])
    DOCS.mkdir(exist_ok=True)
    for th in THEMES:
        (DOCS / f"banner-{th}.svg").write_text(banner(font, th))
        (DOCS / f"divider-{th}.svg").write_text(divider(th))
    print("wrote banners and dividers")


if __name__ == "__main__":
    main()
