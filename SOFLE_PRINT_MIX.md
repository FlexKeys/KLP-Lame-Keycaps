# Sofle v2 Print Mix — KLP Lamé, MX Stem + MX Size

Print mix for a Sofle v2 (58 keys: 4×6 matrix per half + 5 thumbs per half).
Uses the 1.25u Thumb cap (from upstream issue #28, stretched for the Sofle)
on the two wide inner thumb positions (Space / Enter), one per half.

All files live in `STL/MX Stem + MX Size/`.

## Row sculpt

Tilted variants go on the two outermost rows only; the middle two rows get
non-tilted caps. This matches 4-row builds reported in upstream issue #34
(Lily58 Pro, same 4×6+thumbs layout): tilted caps on the inner rows were
found uncomfortable ("feels really nice on second row but not so much for
the first" when both were tilted).

Rows top to bottom: number → upper → home → bottom.

| Qty | File                                  | Goes on                                    |
| --: | :------------------------------------ | :----------------------------------------- |
|  12 | `MX_Stem_MX_Size_Saddle_Tilted.stl`   | Number row (tilt faces fingers)            |
|  12 | `MX_Stem_MX_Size_Normal.stl`          | Upper row (above home)                     |
|  10 | `MX_Stem_MX_Size_Saddle.stl`          | Home row (minus F/J)                       |
|   2 | `MX_Stem_MX_Size_Saddle_Homing.stl`   | F and J home positions                     |
|  12 | `MX_Stem_MX_Size_Normal_Tilted.stl`   | Bottom row (rotate cap 180° so tilt faces up) |
|   8 | `MX_Stem_MX_Size_Thumb.stl`           | Outer 1u thumb keys (4 per half)           |
|   2 | `MX_Stem_MX_Size_Thumb_1.25u.stl`     | Inner thumb key (Space / Enter), one per half |

Total: 58

## All-saddle alternative (from the Lily58 build in issue #34)

| Qty | File                                  | Goes on                  |
| --: | :------------------------------------ | :------------------------ |
|  24 | `MX_Stem_MX_Size_Saddle_Tilted.stl`   | Number row + bottom row   |
|  22 | `MX_Stem_MX_Size_Saddle.stl`          | Upper row + home row      |
|   2 | `MX_Stem_MX_Size_Saddle_Homing.stl`   | F and J                   |
|   8 | `MX_Stem_MX_Size_Thumb.stl`           | Outer 1u thumb keys       |
|   2 | `MX_Stem_MX_Size_Thumb_1.25u.stl`     | Inner thumb key           |

Total: 58

## Order files: `*_9pc_*.stl` (JLC3DP)

JLC3DP accepts at most **10 small parts per file** for both resin (SLA) and
nylon (MJF/SLS) — a single 60-cap file is rejected on the part count whether
it's one fused shell or loose bodies (we tried both; both failed). The proven
fix is exactly what the upstream Production files do: ship the set as several
files of **≤9 caps each**, held together by light connector bars.

So each combo's full 60-cap mix is split into **seven `*_9pc_*.stl` files**
under `Production/<combo>/` (six of 9 caps + one of 6). Upload all seven for
your combo, order quantity 1 of each. The same seven files work for **both
resin and nylon** — the process/material is just a setting in JLC's order form,
not a different file:

- **Resin (SLA):** the connector bars hold each group together through the
  resin process; snip them with flush cutters after printing.
- **Nylon (MJF/SLS):** the powder bed nests the groups and prints with no
  supports; snip the same small bars after printing.

Connection thickness does **not** matter at ≤10 caps — upstream's own bars are
only ~0.9mm and pass. (The earlier single-plate attempts, even as a clean
watertight shell with 3mm bars, were rejected purely on the >10 part count.)
https://jlc3dp.com/help/article/213-Connected-Parts-Printing-Guide

Pick by switch type (stem) and board spacing (size): the MX Sofle v2 is
MX Stem + MX Size; the Sofle Choc (choc spacing, also 58 keys with two wider
thumbs) is Choc Stem + Choc Size. Each combo's seven files together contain the
full mix (row map below) plus both wide-thumb options (2 × 1.25u + 2 × 1.5U),
so the unused thumb pair is spares.

Row map (the full 60-cap set, spread across the seven files): Saddle Tilted ×8 |
Saddle Tilted ×4 + Normal ×4 | Normal ×8 | Saddle ×8 | Saddle ×2 + Saddle
Homing ×2 + Normal Tilted ×4 | Normal Tilted ×8 | Thumb ×8 | Thumb 1.25u ×2 +
1.5U Thumb V ×2.

Generation (`Tools/make_sofle_plate.py` then `Tools/split_for_jlc.py`,
validated by `Tools/tests/test_sofle_plate.py`): caps are decimated with a
verified surface error under 0.1mm. For the 1.25u, the MX Stem + MX Size set
uses the community cap from issue #28 directly (healed and decimated via
Blender, verified to 0.006mm); combos without a community file get a seam-free
equivalent made by warping the combo's own 1u Thumb cap with a smoothstep ramp
— zero displacement over the stem, full quarter-pitch shift at the walls — so
the stem geometry is exact. Two upstream source files (`Saddle_Tilted` in both
Choc Size combos) ship with a small crack along the front wall and are repaired
automatically during generation.

## Materials (community-tested, from upstream issues)

> Note: the same `*_9pc_*.stl` order files work for every process below — pick
> the material in JLC's order form. MJF PA12-HP nylon is the best-feeling
> option; SLA black resin is the cheapest reliable one.

Best documented results, in order:

| Material / process               | Verdict                                                                       |
| :------------------------------- | :----------------------------------------------------------------------------- |
| **MJF PA12-HP Nylon, black**     | Best feel per long-term users (issue #24): PBT-like texture, easy to clean. Black hides grime; natural gray looks dirty out of the box. |
| **MJF PA12S-HP Nylon**           | **Avoid** (issue #35): stems print too thick, MX switches don't fit. The models expect PA12-HP's shrinkage. |
| **SLA resin (LC Black, JLC)**    | "Turned out nicely" (issue #24). Smooth glassy feel — some love it, one user compared it to "fingers on a blackboard". |
| **SLA resin (translucent 8001)** | Confirmed working (issue #24). For full transparency PCBWay clear resin works; don't expect 100% clarity (issue #7). |
| **SLA white**                    | Avoid: author warns it yellows in sunlight; white SLS also gets dirty fast.    |
| **FDM (home printer)**           | Works since v1.1; author recommends SLA for quality. 75° along X for Tilted, 60° for the rest, keep supports out of the stem socket (issue #17). Print individual caps, not the fused plates. |

Ordering caveats:

- With MJF/SLS, the light bars may let some caps arrive snapped off their group
  (issue #22 — powder tumbling is rough on thin sprues); the caps themselves
  survive fine, so this only means a bit of hunting in the bag.
- Skip the "sanding" surface finish: it can eat the choc stem and loosen fit
  (issue #24; Kapton tape on the stem is the rescue if it happens).
- JLC flags `<0.8mm wall thickness` on these caps — accept it; prints have
  been fine. Connected parts add ~$0.1/pc and 1-2 business days.
- Choc switch-top collision was fixed upstream in v1.4 (0.6mm bump, issue #21,
  confirmed with Ambient silents); these caps are built from current models.

## Notes

- Rotary encoders: each EC11 encoder replaces one thumb key. Subtract one
  `Thumb.stl` per encoder installed (e.g. 2 encoders → print 6 thumbs, not 8).
- Print 1–2 spares of each kind; small caps fail occasionally.
- Orientation: tilt models 45°–75° off the plate to avoid layer bumps on the
  touch surface (per upstream README). Resin (SLA) preferred. The 1.25u was
  FDM printed by its author at 0.08mm layer height, stem vertical, with good
  results (issue #28).
- The `Production/MX Stem + MX Size/` zips are batched for 3-row boards
  (tilted-heavy ratios) and don't fit this 4-row mix well (see issue #34) —
  order/print from the individual STLs above instead. The 1.25u thumb is not
  in any production batch.
