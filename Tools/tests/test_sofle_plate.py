# ABOUTME: Validates the committed Sofle order files (the <=9-cap split STLs) satisfy JLC3DP's
# ABOUTME: max-10-parts-per-file rule, and that the generator's 1.25u thumb geometry is exact.

import glob
import os
import sys

import numpy as np
import pytest
import trimesh

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from make_sofle_plate import (  # noqa: E402
    COMBOS,
    MIX,
    REPO_ROOT,
    build_stretched_thumb,
    load_cap,
    plate_path,
    skirt_bottom_z,
)

COMBO_IDS = list(COMBOS)

# JLC3DP accepts at most 10 small parts (caps) per file; upstream uses 9.
JLC_MAX_PARTS = 10
CAP_MIN_FOOTPRINT = 10.0  # mm; caps are ~18mm, connector bars are <=4mm


@pytest.fixture(scope="module", params=COMBO_IDS)
def combo(request):
    return request.param


def split_files(combo):
    folder = os.path.dirname(plate_path(combo))
    return sorted(glob.glob(os.path.join(folder, "*_9pc_*.stl")))


def cap_bodies(mesh):
    return [b for b in mesh.split(only_watertight=False)
            if (b.bounds[1] - b.bounds[0])[0] > CAP_MIN_FOOTPRINT]


def test_mix_totals_58_caps():
    assert sum(qty for _, qty in MIX) == 58


def test_split_files_exist(combo):
    assert split_files(combo), f"no _9pc_ order files for {combo} — run split_for_jlc.py"


def test_each_file_within_jlc_part_limit(combo):
    # The rule that actually gates JLC approval: <=10 caps per file.
    for f in split_files(combo):
        caps = cap_bodies(trimesh.load(f, process=True))
        assert len(caps) <= JLC_MAX_PARTS, (
            f"{os.path.basename(f)} has {len(caps)} caps, over JLC's {JLC_MAX_PARTS} limit"
        )


def test_caps_are_watertight_and_complete(combo):
    # Every cap watertight, and the files together hold the full 60-cap set.
    total = 0
    for f in split_files(combo):
        caps = cap_bodies(trimesh.load(f, process=True))
        assert all(c.is_watertight for c in caps), f"non-watertight cap in {os.path.basename(f)}"
        total += len(caps)
    assert total == 60, f"{combo}: split files hold {total} caps, expected 60"


def test_files_are_uploadable(combo):
    for f in split_files(combo):
        mb = os.path.getsize(f) / 1e6
        assert mb < 50, f"{os.path.basename(f)} is {mb:.0f}MB — too large to upload"


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
