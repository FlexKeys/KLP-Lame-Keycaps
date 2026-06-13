# ABOUTME: Validates the generated Sofle mix production plates (all stem/size combos) are
# ABOUTME: printable as one part: single watertight body, 58 caps, accurate cap geometry.

import os
import sys

import numpy as np
import pytest
import trimesh

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from make_sofle_plate import (  # noqa: E402
    BAR_HEIGHT,
    BAR_WIDTH,
    COMBOS,
    MIX,
    REPO_ROOT,
    build_stretched_thumb,
    load_cap,
    plate_path,
    skirt_bottom_z,
)

COMBO_IDS = list(COMBOS)

# JLC3DP connected-parts rule: connection cross-sections must be >= 1.5mm, and
# 3.0mm keeps them unified rather than flagged as loose small parts.
JLC_MIN_CONNECTION = 1.5
JLC_UNIFIED_CONNECTION = 3.0


@pytest.fixture(scope="module", params=COMBO_IDS)
def combo(request):
    return request.param


@pytest.fixture(scope="module")
def plate(combo):
    path = plate_path(combo)
    assert os.path.exists(path), (
        f"plate not generated yet — run Tools/make_sofle_plate.py first ({path})"
    )
    return trimesh.load(path, process=True)


@pytest.fixture(scope="module")
def nylon(combo):
    path = plate_path(combo).replace("_Sofle_Mix.stl", "_Sofle_Mix_Nylon.stl")
    assert os.path.exists(path), (
        f"nylon file not generated yet — run Tools/make_sofle_plate.py first ({path})"
    )
    return trimesh.load(path, process=True)


def test_mix_totals_58_caps():
    assert sum(qty for _, qty in MIX) == 58


def test_plate_is_single_watertight_body(plate):
    assert plate.is_watertight, "plate must be watertight for print services"
    assert plate.is_winding_consistent
    components = plate.split(only_watertight=False)
    assert len(components) == 1, f"expected one fused body, got {len(components)}"


def test_nylon_is_60_separate_watertight_bodies(nylon):
    # The MJF/SLS file must be 60 distinct, non-touching, watertight caps so the
    # powder-bed printer nests them as loose parts (no connectors to snip).
    bodies = nylon.split(only_watertight=False)
    assert len(bodies) == 60, f"expected 60 loose caps, got {len(bodies)}"
    assert all(b.is_watertight for b in bodies), "every loose cap must be watertight"


def test_plate_has_60_cap_walls(combo, plate):
    # Slice low, where every cap (whatever its height) still shows a hollow
    # wall. Connector bars fuse the outer boundaries together, so cap count is
    # read from the interior holes: one cap-sized hole per cap. The standard
    # plate holds the 58-key mix plus both wide-thumb options (2x 1.25u, 2x
    # 1.5U). Slicing high would miss the short caps closed into their dish.
    from shapely.geometry import Polygon

    cap = load_cap(combo, "Normal")
    cap_area = np.prod((cap.bounds[1] - cap.bounds[0])[:2])
    slice_z = skirt_bottom_z(cap) + 0.6
    section = plate.section(plane_origin=[0, 0, slice_z], plane_normal=[0, 0, 1])
    assert section is not None
    planar, _ = section.to_2D()
    holes = sum(
        1
        for poly in planar.polygons_full
        for ring in poly.interiors
        if Polygon(ring).area > cap_area / 3
    )
    assert holes == 60, f"expected 60 cap walls in cross-section, found {holes}"


def test_connection_bars_meet_jlc_minimum():
    # Both bar cross-section dimensions must clear JLC's unified-connection size
    # so the plate is accepted as one shell, not 60 loose small parts.
    assert min(BAR_WIDTH, BAR_HEIGHT) >= JLC_UNIFIED_CONNECTION


def test_horizontal_bridge_is_solid(combo, plate):
    # The bar between the first two top-row caps must be a solid block at least
    # JLC's minimum across its cross-section. Probe a grid of points filling a
    # JLC_MIN_CONNECTION square at the bar centre and require all inside.
    cap = load_cap(combo, "Normal")
    pitch_x = (cap.bounds[1] - cap.bounds[0])[0] + 1.0
    bar_center_z = skirt_bottom_z(cap) + BAR_HEIGHT / 2
    half = JLC_MIN_CONNECTION / 2
    offs = np.linspace(-half, half, 5)
    pts = np.array([[pitch_x / 2, y, bar_center_z + z] for y in offs for z in offs])
    inside = plate.contains(pts)
    assert inside.all(), (
        f"{(~inside).sum()}/{len(pts)} probe points in the bridge are outside the "
        "mesh — connection thinner than JLC minimum"
    )


def test_plate_dimensions_fit_layout(plate):
    size = plate.bounds[1] - plate.bounds[0]
    # 8 columns of <=19mm pitch caps, 7 rows plus a deeper 1.25u row.
    assert size[0] < 160, f"plate too wide: {size[0]:.1f}mm"
    assert size[1] < 180, f"plate too deep: {size[1]:.1f}mm"
    assert size[2] < 10, f"plate too tall: {size[2]:.1f}mm"


def test_plate_file_size_uploadable(combo):
    mb = os.path.getsize(plate_path(combo)) / 1e6
    assert mb < 50, f"STL is {mb:.0f}MB — too large for print service upload"


def test_stretched_thumb_dimensions(combo):
    # 1.25u must be exactly a quarter key-pitch deeper than the 1u Thumb,
    # with width and height unchanged.
    ours = build_stretched_thumb(combo)
    thumb = load_cap(combo, "Thumb")
    expected = thumb.bounds[1] - thumb.bounds[0] + [0, 0.25 * COMBOS[combo]["key_pitch"], 0]
    assert np.allclose(ours.bounds[1] - ours.bounds[0], expected, atol=0.02)


def test_stretched_thumb_stem_is_unmodified(combo):
    # The stem region must match the source 1u Thumb cap within sampling
    # tolerance — stem fit is the one dimension that cannot drift.
    ours = build_stretched_thumb(combo)
    thumb = load_cap(combo, "Thumb")
    samples, _ = trimesh.sample.sample_surface(thumb, 30000, seed=7)
    stem = (np.linalg.norm(samples[:, :2], axis=1) < 3.2) & (
        samples[:, 2] < skirt_bottom_z(thumb) + 2.0
    )
    assert stem.sum() > 500, "sampling did not reach the stem region"
    _, dist, _ = trimesh.proximity.closest_point(ours, samples[stem])
    assert dist.max() < 0.02, f"stem deviates by {dist.max():.4f}mm"


def test_stretched_thumb_matches_community_125u():
    # The MX+MX rebuild must match the community-stretched STL from upstream
    # issue #28 within print tolerance, away from the (intentionally exact) stem.
    ours = build_stretched_thumb("MX Stem + MX Size")
    theirs = trimesh.load(
        os.path.join(REPO_ROOT, "STL", "MX Stem + MX Size", "MX_Stem_MX_Size_Thumb_1.25u.stl"),
        process=True,
    )
    theirs.vertices -= np.append((theirs.bounds[0][:2] + theirs.bounds[1][:2]) / 2, theirs.bounds[0][2])
    ours_size = ours.bounds[1] - ours.bounds[0]
    theirs_size = theirs.bounds[1] - theirs.bounds[0]
    assert np.allclose(ours_size, theirs_size, atol=0.3), (
        f"bounding boxes differ: ours {ours_size} vs community {theirs_size}"
    )
    samples, _ = trimesh.sample.sample_surface(theirs, 5000, seed=7)
    _, dist, _ = trimesh.proximity.closest_point(ours, samples)
    assert np.percentile(dist, 95) < 0.25, (
        f"stretched thumb deviates from community 1.25u: p95={np.percentile(dist, 95):.3f}mm"
    )
