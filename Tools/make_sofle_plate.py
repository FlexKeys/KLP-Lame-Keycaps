# ABOUTME: Generates production STLs with the full 58-key Sofle KLP Lame mix for every
# ABOUTME: stem/size combo, caps fused by connector bars like the upstream Production plates.

import os

import numpy as np
import trimesh
import fast_simplification
import manifold3d as m3d
import pymeshfix

REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

# Stem/size combos mirror the upstream folder layout. key_pitch is the
# keyboard's unit spacing, which sets how much wider a 1.25u cap is than a 1u.
COMBOS = {
    "MX Stem + MX Size": {"prefix": "MX_Stem_MX_Size", "key_pitch": 19.05},
    "MX Stem + Choc Size": {"prefix": "MX_Stem_Choc_Size", "key_pitch": 18.0},
    "Choc Stem + MX Size": {"prefix": "Choc_Stem_MX_Size", "key_pitch": 19.05},
    "Choc Stem + Choc Size": {"prefix": "Choc_Stem_Choc_Size", "key_pitch": 18.0},
}

# Caps sit 1mm apart, bridged by 3x4mm bars like upstream production plates.
CAP_GAP = 1.0
BAR_WIDTH = 3.0
BAR_LENGTH = 4.0
# Bars must weld into the cap skirt walls; these caps are low profile and the
# stem hangs below the skirt, so the bar z-range is measured per combo.
BAR_WELD_HEIGHT = 1.0

# Sofle v2 mix per SOFLE_PRINT_MIX.md: tilted rows outermost, saddle home row,
# normal upper row, thumbs + two 1.25u (Space/Enter) for the wide inner thumb keys.
MIX = [
    ("Saddle_Tilted", 12),
    ("Normal", 12),
    ("Saddle", 10),
    ("Saddle_Homing", 2),
    ("Normal_Tilted", 12),
    ("Thumb", 8),
    ("Thumb_1.25u", 2),
]

# Plate rows, top to bottom; the 1.25u pair gets its own deeper row at the end.
PLATE_ROWS = [
    ["Saddle_Tilted"] * 8,
    ["Saddle_Tilted"] * 4 + ["Normal"] * 4,
    ["Normal"] * 8,
    ["Saddle"] * 8,
    ["Saddle"] * 2 + ["Saddle_Homing"] * 2 + ["Normal_Tilted"] * 4,
    ["Normal_Tilted"] * 8,
    ["Thumb"] * 8,
]
VARIANTS = ["Saddle_Tilted", "Normal", "Saddle", "Saddle_Homing", "Normal_Tilted", "Thumb"]

# The 1.25u stretch cuts sit outside the stem (MX cross and choc posts both stay
# within |y| < 3mm) but inside the cap walls of even the smaller choc caps.
CUT_Y = 5.0

DECIMATE_TARGET = 12000
DECIMATE_TARGET_125U = 16000
DECIMATE_MAX_ERROR = 0.1  # mm; matches SLA print service dimensional tolerance


def load_cap(combo, name):
    """Load a cap STL centered on xy origin, original z preserved."""
    path = os.path.join(REPO_ROOT, "STL", combo, f"{COMBOS[combo]['prefix']}_{name}.stl")
    cap = trimesh.load(path, process=True)
    center = (cap.bounds[0][:2] + cap.bounds[1][:2]) / 2
    cap.vertices[:, :2] -= center
    return cap


def plate_path(combo):
    return os.path.join(
        REPO_ROOT, "Production", combo, f"{COMBOS[combo]['prefix']}_Sofle_Mix.stl"
    )


def skirt_bottom_z(cap):
    """Lowest z of the cap's outer wall (the stem hangs lower and doesn't count)."""
    size = cap.bounds[1] - cap.bounds[0]
    perim = (np.abs(cap.vertices[:, 0]) > size[0] / 2 - 1.0) | (
        np.abs(cap.vertices[:, 1]) > size[1] / 2 - 1.0
    )
    return cap.vertices[perim][:, 2].min()


REPAIR_MAX_ERROR = 0.25  # mm; localized to the crack a repair rebuilds


def repair_if_needed(mesh):
    """Make a mesh watertight, verifying the repair stays close to the original.

    Some upstream mix-and-match STLs (the choc-size Saddle_Tilted ones) ship
    with a thin crack along the front wall that boolean engines reject.
    """
    if mesh.is_watertight:
        return mesh
    verts, faces = pymeshfix.clean_from_arrays(
        np.ascontiguousarray(mesh.vertices, dtype=np.float64),
        np.ascontiguousarray(mesh.faces, dtype=np.int32),
    )
    fixed = trimesh.Trimesh(verts, faces)
    fixed.process()
    if not fixed.is_watertight:
        raise ValueError("repair failed to produce a watertight mesh")
    samples, _ = trimesh.sample.sample_surface(mesh, 10000, seed=42)
    _, dist, _ = trimesh.proximity.closest_point(fixed, samples)
    if dist.max() > REPAIR_MAX_ERROR:
        raise ValueError(f"repair moved surface by {dist.max():.4f}mm")
    return fixed


def to_manifold(mesh):
    m = m3d.Mesh(mesh.vertices.astype(np.float32), mesh.faces.astype(np.uint32))
    m.merge()
    manifold = m3d.Manifold(m)
    if manifold.status() != m3d.Error.NoError:
        raise ValueError(f"mesh is not manifold: {manifold.status()}")
    return manifold


def to_trimesh(manifold):
    out = manifold.to_mesh()
    raw = trimesh.Trimesh(out.vert_properties[:, :3].astype(np.float64), out.tri_verts)
    # manifold3d emits float32 vertices, leaving near-duplicate points that break
    # trimesh's adjacency checks. Weld on a 0.0001mm grid, escalating to 0.001mm
    # (still far below any cap feature) when boolean seams need the coarser snap,
    # and drop the degenerate faces the welding collapses.
    for digits in (4, 3):
        mesh = raw.copy()
        mesh.merge_vertices(digits_vertex=digits)
        mesh.update_faces(mesh.nondegenerate_faces())
        mesh.update_faces(mesh.unique_faces())
        mesh.remove_unreferenced_vertices()
        mesh.process()
        if mesh.is_watertight:
            break
    return mesh


def slab(y_min, y_max):
    """An axis-aligned box covering the full cap footprint between two y planes."""
    box = trimesh.creation.box(
        extents=[100, y_max - y_min, 100],
        transform=trimesh.transformations.translation_matrix([0, (y_min + y_max) / 2, 25]),
    )
    return to_manifold(box)


def build_stretched_thumb(combo):
    """Build the combo's 1.25u thumb from its pristine 1u Thumb cap.

    Mirrors the community stretch from upstream issue #28: the cap is cut at
    y=+-5mm, the outer pieces are shifted apart, and the gaps are filled with
    prisms made by stretching a thin slice taken at each cut. The stem sits
    between the cuts and is therefore geometrically untouched.
    """
    stretch_half = 0.25 * COMBOS[combo]["key_pitch"] / 2
    cap = to_manifold(repair_if_needed(load_cap(combo, "Thumb")))

    left = (cap ^ slab(-100, -CUT_Y)).translate([0, -stretch_half, 0])
    mid = cap ^ slab(-CUT_Y, CUT_Y)
    right = (cap ^ slab(CUT_Y, 100)).translate([0, stretch_half, 0])

    bands = []
    for sign in (-1, 1):
        cut = sign * CUT_Y
        # 0.02mm slice at the cut plane, stretched into a prism that overlaps
        # 0.01mm into the neighboring pieces so the union has no coplanar seams.
        thin = cap ^ slab(cut - 0.01, cut + 0.01)
        prism_len = stretch_half + 0.02
        prism = thin.scale([1, prism_len / 0.02, 1])
        # After scaling about the origin the slice center lands at cut * scale;
        # move the prism so it spans from just inside the mid piece outward.
        prism_center_target = cut + sign * (stretch_half / 2)
        prism = prism.translate([0, prism_center_target - cut * (prism_len / 0.02), 0])
        bands.append(prism)

    stretched = left + bands[0] + mid + bands[1] + right
    result = to_trimesh(stretched)
    if not result.is_watertight:
        # Deliberately no MeshFix fallback here: it rebuilds geometry and has
        # been seen gouging stem posts, which must stay exact.
        raise ValueError("stretched 1.25u thumb is not watertight")
    return result


def decimate(mesh, target):
    """Reduce face count, verifying the surface stays within print tolerance."""
    points, faces = fast_simplification.simplify(
        mesh.vertices.astype(np.float32), mesh.faces.astype(np.uint32), target_count=target
    )
    slim = trimesh.Trimesh(points, faces)
    slim.merge_vertices(digits_vertex=4)
    slim.update_faces(slim.nondegenerate_faces())
    slim.update_faces(slim.unique_faces())
    slim.remove_unreferenced_vertices()
    slim.process()
    # Simplification occasionally leaves small topological defects; repair them.
    slim = repair_if_needed(slim)
    samples, _ = trimesh.sample.sample_surface(mesh, 5000, seed=42)
    _, dist, _ = trimesh.proximity.closest_point(slim, samples)
    if dist.max() > DECIMATE_MAX_ERROR:
        raise ValueError(f"decimation error {dist.max():.4f}mm exceeds {DECIMATE_MAX_ERROR}mm")
    return slim


def bar(x, y, z_range, along_x):
    extents = [BAR_LENGTH, BAR_WIDTH, z_range[1] - z_range[0]]
    if not along_x:
        extents = [BAR_WIDTH, BAR_LENGTH, extents[2]]
    box = trimesh.creation.box(
        extents=extents,
        transform=trimesh.transformations.translation_matrix([x, y, (z_range[0] + z_range[1]) / 2]),
    )
    return to_manifold(box)


def build_plate(combo):
    print(f"[{combo}] preparing cap meshes...")
    caps = {}
    skirts = {}
    for name in VARIANTS:
        raw = repair_if_needed(load_cap(combo, name))
        skirts[name] = skirt_bottom_z(raw)
        caps[name] = decimate(raw, DECIMATE_TARGET)
    stretched = build_stretched_thumb(combo)
    skirts["Thumb_1.25u"] = skirt_bottom_z(stretched)
    caps["Thumb_1.25u"] = decimate(stretched, DECIMATE_TARGET_125U)

    # Bars start at the lowest skirt and reach BAR_WELD_HEIGHT past the highest
    # one, so every adjacent pair of variants gets welded.
    bar_z = (min(skirts.values()), max(skirts.values()) + BAR_WELD_HEIGHT)

    size = caps["Normal"].bounds[1] - caps["Normal"].bounds[0]
    cap_w, cap_d = size[0], size[1]
    pitch_x, pitch_y = cap_w + CAP_GAP, cap_d + CAP_GAP
    stretch_total = 0.25 * COMBOS[combo]["key_pitch"]

    print(f"[{combo}] placing caps and connector bars...")
    parts = []
    used = {name: 0 for name, _ in MIX}
    for r, row in enumerate(PLATE_ROWS):
        y = -r * pitch_y
        for c, name in enumerate(row):
            parts.append(to_manifold(caps[name]).translate([c * pitch_x, y, 0]))
            used[name] += 1
            if c > 0:
                parts.append(bar(c * pitch_x - pitch_x / 2, y, bar_z, along_x=True))
            if r > 0:
                parts.append(bar(c * pitch_x, y + pitch_y / 2, bar_z, along_x=False))

    # 1.25u row: deeper caps, so the row drops by half the standard cap depth
    # plus half the stretched depth plus the standard gap.
    depth_125u = cap_d + stretch_total
    last_row_y = -(len(PLATE_ROWS) - 1) * pitch_y - (cap_d + depth_125u) / 2 - CAP_GAP
    gap_y = -(len(PLATE_ROWS) - 1) * pitch_y - cap_d / 2 - CAP_GAP / 2
    for c in range(2):
        parts.append(to_manifold(caps["Thumb_1.25u"]).translate([c * pitch_x, last_row_y, 0]))
        used["Thumb_1.25u"] += 1
        parts.append(bar(c * pitch_x, gap_y, bar_z, along_x=False))
    parts.append(bar(pitch_x / 2, last_row_y, bar_z, along_x=True))

    expected = dict(MIX)
    if used != expected:
        raise ValueError(f"layout does not match mix: {used} != {expected}")

    print(f"[{combo}] fusing {len(parts)} parts...")
    plate = m3d.Manifold.batch_boolean(parts, m3d.OpType.Add)
    if plate.status() != m3d.Error.NoError:
        raise ValueError(f"union failed: {plate.status()}")
    if len(plate.decompose()) != 1:
        raise ValueError("plate has disconnected bodies")

    result = to_trimesh(plate)
    if not result.is_watertight:
        raise ValueError("plate is not watertight")

    path = plate_path(combo)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    result.export(path)
    size = result.bounds[1] - result.bounds[0]
    print(f"[{combo}] wrote {os.path.basename(path)}: {os.path.getsize(path) / 1e6:.1f} MB, "
          f"{size[0]:.1f} x {size[1]:.1f} x {size[2]:.1f} mm, 58 caps")


def main():
    for combo in COMBOS:
        build_plate(combo)


if __name__ == "__main__":
    main()
