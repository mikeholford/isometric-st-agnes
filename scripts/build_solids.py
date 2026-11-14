# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy", "scipy"]
# ///
"""What stands on the land, for the viewer: every building as an outline with the height of its ground and its top,
and every tree and bush as a spot, a height and a width.

The viewer draws the giant over the map and then needs to know what is in front of him: a house or a hedge nearer to
the camera is drawn again over him. All numbers are decimetres in local coordinates (x east, z south from the centre
of the area), heights in decimetres above Ordnance Datum. Output: data/build/solids.json
  {"buildings": [[ground, top, x0, z0, x1, z1, ...], ...], "trees": [x, z, ground, height, radius, ...]}
"""

import json

import numpy as np
from scipy.spatial import ConvexHull

from config import BUILD


def main():
    v = np.fromfile(BUILD / "buildings.bin", dtype=np.float32).reshape(-1, 12)  # x y z, normal, u v, kind, building, atlas u v
    order = np.argsort(v[:, 9], kind="stable")
    v = v[order]
    starts = np.flatnonzero(np.r_[True, np.diff(v[:, 9]) != 0, True])
    buildings = []
    for a, b in zip(starts[:-1], starts[1:]):
        pts = np.unique(np.round(v[a:b, [0, 2]], 1), axis=0)
        if len(pts) < 3:
            continue
        try:
            ring = pts[ConvexHull(pts).vertices]
        except Exception:  # noqa: BLE001  all in one line: nothing to stand behind
            continue
        y = v[a:b, 1]
        buildings.append([round(float(y.min()) * 10), round(float(y.max()) * 10)] + [round(float(c) * 10) for c in ring.ravel()])
    t = np.fromfile(BUILD / "trees.bin", dtype=np.float32).reshape(-1, 11)  # x, z, height, crown radius, ..., ground
    trees = np.round(t[:, [0, 1, 10, 2, 3]] * 10).astype(int).ravel().tolist()
    (BUILD / "solids.json").write_text(json.dumps({"buildings": buildings, "trees": trees}, separators=(",", ":")))
    print(f"{len(buildings)} buildings and {len(t)} trees for the viewer")


if __name__ == "__main__":
    main()
