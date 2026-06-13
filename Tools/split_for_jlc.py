# ABOUTME: Splits a multi-body keycap STL into files of <=9 caps joined by overlapping
# ABOUTME: connector bars, matching the upstream Production layout that passes JLC3DP review.

# JLC3DP accepts at most ~10 small parts per file (upstream uses 9). Connection
# thickness is NOT enforced at that count — upstream's own bars are only ~0.9mm
# tall — so the bars here exist only to hold the group together for handling;
# they overlap the caps and are left un-unioned, exactly like upstream.
# https://jlc3dp.com/help/article/213-Connected-Parts-Printing-Guide

import argparse
import os

import numpy as np
import trimesh

GROUP = 9          # caps per file (<= 10; upstream uses 9)
BAR_LENGTH = 4.0   # bridges the ~1mm inter-cap gap with overlap into each cap
BAR_WIDTH = 3.0
BAR_HEIGHT = 2.0   # sturdier than upstream's 0.9mm so groups survive shipping
ADJACENT = 1.4     # pair caps whose centre distance is within this * grid pitch


def skirt_bottom(cap):
    """Lowest z of the cap's outer wall (a protruding stem sits lower)."""
    c = (cap.bounds[0] + cap.bounds[1]) / 2
    sz = cap.bounds[1] - cap.bounds[0]
    v = cap.vertices
    perim = (np.abs(v[:, 0] - c[0]) > sz[0] / 2 - 1.0) | (np.abs(v[:, 1] - c[1]) > sz[1] / 2 - 1.0)
    return v[perim][:, 2].min()


def bar_between(a, b):
    """A box bridging two caps, in the wall band, oriented along their offset."""
    ca, cb = a.centroid, b.centroid
    mid = (ca + cb) / 2
    z0 = min(skirt_bottom(a), skirt_bottom(b))
    along_x = abs(cb[0] - ca[0]) >= abs(cb[1] - ca[1])
    extents = [BAR_LENGTH, BAR_WIDTH, BAR_HEIGHT] if along_x else [BAR_WIDTH, BAR_LENGTH, BAR_HEIGHT]
    return trimesh.creation.box(
        extents=extents,
        transform=trimesh.transformations.translation_matrix([mid[0], mid[1], z0 + BAR_HEIGHT / 2]),
    )


def split_file(path, group=GROUP, out_dir=None):
    mesh = trimesh.load(path, process=True)
    caps = mesh.split(only_watertight=False)
    cents = np.array([c.centroid for c in caps])
    # grid pitch = typical nearest-neighbour distance between caps
    d = np.linalg.norm(cents[:, None] - cents[None, :], axis=2)
    np.fill_diagonal(d, np.inf)
    pitch = float(np.median(d.min(axis=1)))

    order = sorted(range(len(caps)), key=lambda i: (-round(cents[i][1], 1), round(cents[i][0], 1)))
    n_files = (len(caps) + group - 1) // group
    base = os.path.splitext(os.path.basename(path))[0].replace("_Nylon", "")
    out_dir = out_dir or os.path.dirname(path)
    os.makedirs(out_dir, exist_ok=True)

    written = []
    for f in range(n_files):
        idx = order[f * group:(f + 1) * group]
        members = [caps[i] for i in idx]
        bars = []
        for a in range(len(idx)):
            for b in range(a + 1, len(idx)):
                if np.linalg.norm(cents[idx[a]] - cents[idx[b]]) < ADJACENT * pitch:
                    bars.append(bar_between(caps[idx[a]], caps[idx[b]]))
        out_mesh = trimesh.util.concatenate(members + bars)
        out_mesh.apply_translation(-out_mesh.bounds[0])
        out = os.path.join(out_dir, f"{base}_{group}pc_{f + 1}of{n_files}.stl")
        out_mesh.export(out)
        written.append((out, len(members), len(bars)))
    return written


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("files", nargs="+", help="multi-body STL(s) to split")
    parser.add_argument("--group", type=int, default=GROUP, help="caps per file (<=10)")
    parser.add_argument("--out", help="output directory (default: next to source)")
    args = parser.parse_args()
    for path in args.files:
        for out, caps, bars in split_file(path, args.group, args.out):
            print(f"wrote {os.path.basename(out)} ({caps} caps, {bars} bars)")


if __name__ == "__main__":
    main()
