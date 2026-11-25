# Design: Metal Future Forecast

This project breaks the house rule on purpose. The BTC instrument was a quiet,
Tufte-style plate. This one is a cartoon foundry: two blobs of molten metal
argue about where price goes, and the data sits on the workbench between them.
The fun lives in the chrome. The numbers stay crisp.

## 1. Idea in one line

> A smelting shop at midnight. Gold and silver drip off the headline, the
> panels look like cooled slag with thick ink outlines, and every chart is
> printed on a clean steel plate bolted inside the goo.

## 2. Palette

| Token | Hex | Use |
| :--- | :--- | :--- |
| `--choc-900` | `#140D08` | page background (dark chocolate, almost black) |
| `--choc-800` | `#1E140D` | panel fill |
| `--choc-700` | `#2A1C12` | inset wells, table stripes |
| `--ink` | `#050302` | cartoon outlines, 3px |
| `--gold-500` | `#F5B700` | molten gold, gold metal accents, LONG on gold |
| `--gold-700` | `#C8901A` | gold shadow, gradients |
| `--gold-200` | `#FFE08A` | gold highlight |
| `--silver-300` | `#C0C6CC` | silver metal, body text on dark |
| `--silver-600` | `#8A9299` | silver shadow, secondary text |
| `--silver-100` | `#EEF1F4` | silver highlight, primary numbers |
| `--lava` | `#FF5A1F` | lava glow, used only in headline chrome |
| `--up` | `#7BD88F` | LONG verdict and gains (data colour) |
| `--down` | `#FF6B6B` | SHORT verdict and losses (data colour) |
| `--flat` | `#B9A68C` | NEUTRAL |

Gold and silver are identity colours, never data colours. Gains and losses
use `--up` / `--down` so a silver-coloured number never reads as "neutral".
All text on `--choc-800` passes WCAG AA (silver-100 is 15:1, silver-600 is 5.6:1).

## 3. Type (two families, no more)

- **Luckiest Guy** for display only: the wordmark, tab labels, panel titles,
  verdict words. Chunky, cartoon, takes drips and goo without falling apart.
- **Nunito** (variable, 400 to 800) for everything else, with
  `font-variant-numeric: tabular-nums` on every number so columns line up.
- Data is never set in the display face. Verdict words are the one exception,
  and they also sit next to the plain number.

## 4. The goo system

1. **Molten wordmark.** "METAL FUTURE FORECAST" is SVG text filled with a slow
   animated linear gradient (gold to lava to gold, 9 s loop), clipped to the
   letters. Under the letters sits a row of drip shapes (paths) that stretch
   and snap back on staggered timers.
2. **Goo filter.** `feGaussianBlur (stdDeviation 7) -> feColorMatrix
   (alpha 0 0 0 22 -9)` merges the letters with the drips so they look like
   one poured shape. A second, sharp copy of the text sits on top, so the
   words stay legible while the goo wobbles underneath.
3. **Blob panels.** Panels have asymmetric radii (`28px 34px 30px 38px`), a
   3px ink outline and a hard 6px offset shadow in ink. On hover they wobble
   (a 600 ms rotate of plus or minus 0.4 degrees and a radius morph). Charts
   inside them do not move.
4. **Mascots.** Gold is "Nugget", a round ingot blob; silver is "Quicksilver",
   a taller droplet. Both are inline SVG with ink outlines, two specular
   highlights and eyes that follow the verdict: LONG looks up and grins,
   SHORT looks down and frowns, NEUTRAL looks sideways. They blink every few
   seconds. They are the only illustrations on the page.
5. **Lava floor.** A thin animated wave at the bottom of the header and
   between sections (SVG path with a two-stop gradient). One per section, no
   more.

## 5. Data rules (the part that is not fun)

- Every chart is drawn as plain SVG on a flat `--choc-700` well with 1px
  hairline gridlines, no blur, no gradient fill under lines, no animation.
- Numbers are Nunito 600 to 800 in `--silver-100`. Units always shown.
- Thresholds (0.40, 0.60) are drawn as dashed lines on every P(long) chart.
- Proxies are labelled where they appear, not in a footnote: PAXG is called
  "gold-backed token, not spot gold"; the open-interest liquidation proxy is
  called "proxy".

## 6. Voice

Labels speak like a trader on the desk ("gold is cooking", "silver got rekt",
"bag holders", "degen mode", "touch grass"), but every number keeps a plain
label next to it, and every explainer is written in full sentences. No
profanity, nothing aimed at any group of people.

## 7. Motion

- Headline gradient, drips, mascot blinks, lava wave: slow (6 to 12 s).
- Panel wobble only on hover or focus.
- `prefers-reduced-motion: reduce` stops all animation, removes the goo filter
  wobble, and leaves a static molten gradient.

## 8. Layout

- 1440 px: header with the wordmark and both mascots, then the two metals side
  by side in two equal blob panels, then full-width sections.
- 390 px: one column; metals stack gold first; tables scroll inside their
  panel; the wordmark wraps to three lines and the drips shrink.
- No stock card grid. Each section has its own shape: the verdict pair is a
  "scale" with the two blobs facing each other; Flows is a long tape; Backtest
  reads like a lab notebook with numbered figures.

## 9. What we will not do

No emoji. No glassmorphism. No neon outer glows on text that carries data. No
gradient-filled charts. No more than two fonts. No icons from a stock set:
every glyph on the page is drawn for it.
