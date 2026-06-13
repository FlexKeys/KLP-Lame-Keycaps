# ABOUTME: Generates production STLs with the full 58-key Sofle KLP Lame mix for every
# ABOUTME: stem/size combo, caps fused by connector bars like the upstream Production plates.

import os
import shutil
import subprocess
import tempfile

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

# Caps sit 1mm apart, bridged by connector bars that weld into the cap skirts.
# JLC3DP's connected-parts rule requires every connection cross-section to be
# at least 1.5mm (3.0mm to guarantee the parts stay unified and aren't flagged
# as loose small parts), so the bars are a 3.0mm-wide x 3.0mm-tall solid that
# bridges the gap and overlaps each cap wall.
# https://jlc3dp.com/help/article/213-Connected-Parts-Printing-Guide
CAP_GAP = 1.0
BAR_WIDTH = 3.0
BAR_LENGTH = 4.0
BAR_HEIGHT = 3.0

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

# The 1.25u stretch ramp is zero over the stem (MX cross and choc posts both
# stay within |y| < 3mm) and reaches the full shift before the cap walls of
# even the smaller choc caps.
STRETCH_INNER = 3.5
STRETCH_OUTER = 7.0

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
    # manifold3d's output is topologically closed by vertex index — keep it
    # unprocessed if trimesh agrees (position-welding can fuse distinct vertices
    # that merely touch, breaking topology that was fine).
    raw = trimesh.Trimesh(
        out.vert_properties[:, :3].astype(np.float64), out.tri_verts, process=False
    )
    if raw.is_watertight:
        return raw
    # Otherwise weld float32 near-duplicates on a 0.0001mm grid, escalating to
    # 0.001mm (still far below any cap feature) when boolean seams need the
    # coarser snap, and drop the degenerate faces the welding collapses.
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

    Vertices are displaced along y with a smoothstep ramp: zero over the stem
    (|y| < STRETCH_INNER), the full quarter-pitch shift past STRETCH_OUTER, and
    a C1-smooth blend between — like the CAD stretch of the community cap from
    upstream issue #28, with no seams. Topology is untouched, so the result is
    watertight by construction and the stem stays geometrically exact.
    """
    stretch_half = 0.25 * COMBOS[combo]["key_pitch"] / 2
    cap = repair_if_needed(load_cap(combo, "Thumb"))

    y = cap.vertices[:, 1]
    t = np.clip((np.abs(y) - STRETCH_INNER) / (STRETCH_OUTER - STRETCH_INNER), 0.0, 1.0)
    ramp = t * t * (3.0 - 2.0 * t)
    verts = cap.vertices.copy()
    verts[:, 1] = y + np.sign(y) * stretch_half * ramp

    result = trimesh.Trimesh(verts, cap.faces.copy(), process=False)
    if not result.is_watertight:
        raise ValueError("stretched 1.25u thumb is not watertight")
    return result


def separate_touching_sheets(mesh):
    """Nudge apart surface points that touch at identical positions.

    The mesh must be watertight by vertex index. Distinct vertices sharing one
    position are self-touch pinches: exact, so any STL round trip welds them
    into non-manifold junctions. Each one is moved half a micron along its own
    vertex normal, which keeps the sheets apart through export and re-import.
    """
    from scipy.spatial import cKDTree

    pairs = cKDTree(mesh.vertices).query_pairs(r=1e-7)
    if not pairs:
        return mesh
    verts = mesh.vertices.copy()
    normals = mesh.vertex_normals
    for pair in pairs:
        for v in pair:
            verts[v] = verts[v] + normals[v] * 0.0005
    return trimesh.Trimesh(verts, mesh.faces.copy(), process=False)


def community_thumb_125(combo):
    """Load the community-stretched 1.25u (upstream issue #28) when the combo
    ships one. The file is not watertight as-shipped and resists ordinary
    decimation, so it is healed via a manifold3d merge and decimated with
    Blender's collapse modifier, then verified against the original surface.
    Returns None when the combo has no community file or Blender is missing.
    """
    path = os.path.join(
        REPO_ROOT, "STL", combo, f"{COMBOS[combo]['prefix']}_Thumb_1.25u.stl"
    )
    if not os.path.exists(path) or shutil.which("blender") is None:
        return None
    orig = trimesh.load(path, process=True)
    m = m3d.Mesh(orig.vertices.astype(np.float32), orig.faces.astype(np.uint32))
    m.merge()
    out = m3d.Manifold(m).to_mesh()
    healed = trimesh.Trimesh(
        out.vert_properties[:, :3].astype(np.float64), out.tri_verts, process=False
    )
    healed = separate_touching_sheets(healed)
    with tempfile.TemporaryDirectory() as tmp:
        src, dst = os.path.join(tmp, "in.stl"), os.path.join(tmp, "out.stl")
        healed.export(src)
        script = os.path.join(tmp, "decimate.py")
        with open(script, "w") as f:
            f.write(
                "import bpy, sys\n"
                "argv = sys.argv[sys.argv.index('--')+1:]\n"
                "bpy.ops.wm.read_factory_settings(use_empty=True)\n"
                "bpy.ops.wm.stl_import(filepath=argv[0])\n"
                "obj = bpy.context.selected_objects[0]\n"
                "mod = obj.modifiers.new('dec', 'DECIMATE')\n"
                "mod.ratio = float(argv[2])\n"
                "bpy.context.view_layer.objects.active = obj\n"
                "bpy.ops.object.modifier_apply(modifier='dec')\n"
                "bpy.ops.wm.stl_export(filepath=argv[1], export_selected_objects=True)\n"
            )
        ratio = DECIMATE_TARGET_125U / len(healed.faces)
        subprocess.run(
            ["blender", "-b", "-P", script, "--", src, dst, str(ratio)],
            check=True, capture_output=True,
        )
        slim = trimesh.load(dst, process=True)
    if not slim.is_watertight:
        raise ValueError("community 1.25u lost watertightness through decimation")
    samples, _ = trimesh.sample.sample_surface(orig, 10000, seed=42)
    _, dist, _ = trimesh.proximity.closest_point(slim, samples)
    if dist.max() > DECIMATE_MAX_ERROR:
        raise ValueError(f"community 1.25u decimation error {dist.max():.4f}mm")
    center = (slim.bounds[0] + slim.bounds[1]) / 2
    slim.vertices -= [center[0], center[1], slim.bounds[0][2]]
    return slim


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


def build_plate(combo, wide_thumb="Thumb_1.25u", connected=True):
    """wide_thumb: "Thumb_1.25u" (stretched, community shape from issue #28)
    or "1.5U_Thumb_V" / "1.5U_Thumb_H" (upstream sculpted 1.5U caps).
    Pass a tuple of names to put several wide caps on the plate.

    connected=True fuses the caps with bars into one SLA-ready shell;
    connected=False emits the caps as separate bodies for MJF/SLS nylon."""
    wide_thumbs = (wide_thumb,) * 2 if isinstance(wide_thumb, str) else tuple(wide_thumb)
    print(f"[{combo}] preparing cap meshes (wide thumbs: {', '.join(wide_thumbs)})...")
    caps = {}
    skirts = {}
    for name in VARIANTS:
        raw = repair_if_needed(load_cap(combo, name))
        skirts[name] = skirt_bottom_z(raw)
        caps[name] = decimate(raw, DECIMATE_TARGET)
    for name in set(wide_thumbs):
        if name == "Thumb_1.25u":
            # Prefer the community cap (smooth CAD stretch); fall back to our
            # cut-and-fill stretch for combos that have no community file.
            wide_cap = community_thumb_125(combo)
            if wide_cap is None:
                wide_cap = decimate(build_stretched_thumb(combo), DECIMATE_TARGET_125U)
        else:
            wide_cap = decimate(repair_if_needed(load_cap(combo, name)), DECIMATE_TARGET_125U)
        skirts[name] = skirt_bottom_z(wide_cap)
        caps[name] = wide_cap

    # Bars span BAR_HEIGHT upward from the lowest skirt, so every cap's wall is
    # overlapped and the connection cross-section is a solid BAR_WIDTH x
    # BAR_HEIGHT. Verify the bar welds into the highest-skirt caps and stays
    # below the shortest cap top (so it never breaks through a dished surface).
    min_skirt, max_skirt = min(skirts.values()), max(skirts.values())
    shortest_top = min(c.bounds[1][2] for c in caps.values())
    bar_z = (min_skirt, min_skirt + BAR_HEIGHT)
    if connected:
        assert bar_z[1] > max_skirt + 1.0, "bar too short to weld into the tallest skirt"
        assert bar_z[1] < shortest_top - 0.3, "bar would break through the shortest cap top"

    size = caps["Normal"].bounds[1] - caps["Normal"].bounds[0]
    cap_w, cap_d = size[0], size[1]
    pitch_x, pitch_y = cap_w + CAP_GAP, cap_d + CAP_GAP

    print(f"[{combo}] placing caps{' and connector bars' if connected else ' (loose)'}...")
    parts = []           # manifolds (caps + bars) for the fused plate
    bodies = []          # trimeshes (caps only) for the loose nylon file
    used = {name: 0 for name, _ in MIX}
    used.pop("Thumb_1.25u")
    for name in wide_thumbs:
        used.setdefault(name, 0)
    for r, row in enumerate(PLATE_ROWS):
        y = -r * pitch_y
        for c, name in enumerate(row):
            parts.append(to_manifold(caps[name]).translate([c * pitch_x, y, 0]))
            bodies.append(caps[name].copy().apply_translation([c * pitch_x, y, 0]))
            used[name] += 1
            if connected and c > 0:
                parts.append(bar(c * pitch_x - pitch_x / 2, y, bar_z, along_x=True))
            if connected and r > 0:
                parts.append(bar(c * pitch_x, y + pitch_y / 2, bar_z, along_x=False))

    # Wide-thumb row: caps may differ in footprint, so align their top edges
    # one gap below the thumb row and advance the x cursor per cap width.
    top_edge_y = -(len(PLATE_ROWS) - 1) * pitch_y - cap_d / 2 - CAP_GAP
    gap_y = top_edge_y + CAP_GAP / 2
    cursor = 0.0
    prev_edge = None
    for name in wide_thumbs:
        w, d = (caps[name].bounds[1] - caps[name].bounds[0])[:2]
        cx = cursor + w / 2
        parts.append(to_manifold(caps[name]).translate([cx, top_edge_y - d / 2, 0]))
        bodies.append(caps[name].copy().apply_translation([cx, top_edge_y - d / 2, 0]))
        used[name] += 1
        if connected:
            # weld upward into whichever thumb-row column sits above this cap
            col_x = min(7, max(0, round(cx / pitch_x))) * pitch_x
            col_x = min(max(col_x, cx - w / 2 + BAR_WIDTH), cx + w / 2 - BAR_WIDTH)
            parts.append(bar(col_x, gap_y, bar_z, along_x=False))
            if prev_edge is not None:
                # weld sideways to the previous wide cap, near their aligned tops
                parts.append(bar(prev_edge + CAP_GAP / 2, top_edge_y - 8.0, bar_z, along_x=True))
        prev_edge = cursor + w
        cursor += w + CAP_GAP

    expected = dict(MIX)
    expected.pop("Thumb_1.25u")
    for name in wide_thumbs:
        expected[name] = expected.get(name, 0) + 1
    if used != expected:
        raise ValueError(f"layout does not match mix: {used} != {expected}")

    if connected:
        print(f"[{combo}] fusing {len(parts)} parts...")
        plate = m3d.Manifold.batch_boolean(parts, m3d.OpType.Add)
        if plate.status() != m3d.Error.NoError:
            raise ValueError(f"union failed: {plate.status()}")
        if len(plate.decompose()) != 1:
            raise ValueError("plate has disconnected bodies")
        result = to_trimesh(plate)
        if not result.is_watertight:
            raise ValueError("plate is not watertight")
    else:
        # Nylon (MJF/SLS): loose, non-touching, watertight bodies in one STL.
        print(f"[{combo}] placing {len(bodies)} loose caps...")
        result = trimesh.util.concatenate(bodies)
        if len(result.split(only_watertight=False)) != len(bodies):
            raise ValueError("loose caps unexpectedly merged")

    path = plate_path(combo)
    kinds = set(wide_thumbs)
    if len(kinds) > 1:
        pass  # both wide-thumb options is the standard plate
    elif kinds == {"Thumb_1.25u"}:
        path = path.replace("_Sofle_Mix.stl", "_Sofle_Mix_125U.stl")
    else:
        path = path.replace("_Sofle_Mix.stl", "_Sofle_Mix_15U.stl")
    if not connected:
        path = path.replace("_Sofle_Mix", "_Sofle_Mix_Nylon")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    result.export(path)
    size = result.bounds[1] - result.bounds[0]
    n_caps = 56 + len(wide_thumbs)
    kind = "fused plate" if connected else "loose bodies"
    print(f"[{combo}] wrote {os.path.basename(path)} ({kind}): "
          f"{os.path.getsize(path) / 1e6:.1f} MB, "
          f"{size[0]:.1f} x {size[1]:.1f} x {size[2]:.1f} mm, {n_caps} caps")


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--combo", choices=list(COMBOS), help="build a single combo")
    parser.add_argument("--thumb", default="both", choices=["1.25u", "1.5uV", "1.5uH", "both"],
                        help="wide thumb caps: both (default), 1.25u only, or upstream 1.5U only")
    parser.add_argument("--only", choices=["sla", "nylon"],
                        help="build only the SLA fused plate or only the nylon loose file")
    args = parser.parse_args()
    wide = {
        "1.25u": ("Thumb_1.25u",) * 2,
        "1.5uV": ("1.5U_Thumb_V",) * 2,
        "1.5uH": ("1.5U_Thumb_H",) * 2,
        "both": ("Thumb_1.25u", "Thumb_1.25u", "1.5U_Thumb_V", "1.5U_Thumb_V"),
    }[args.thumb]
    kinds = {"sla": [True], "nylon": [False]}.get(args.only, [True, False])
    for combo in ([args.combo] if args.combo else COMBOS):
        for connected in kinds:
            build_plate(combo, wide_thumb=wide, connected=connected)


if __name__ == "__main__":
    main()
