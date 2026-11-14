# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy", "pillow"]
# ///
"""The buildings and trees of the live 3D viewer (viewer/live.html).

That viewer has no tiles: it draws the land, the buildings and the trees itself, lit by the sun of the hour. A building
there is its footprint pulled up to a flat top: the outline that scripts/build_buildings.py settled on, standing on the
lowest ground under it, as high as the lidar's first return stands over that ground (the 85th percentile of the cells
inside the outline, so a chimney or a tree that leans over does not set the height). Trees are the ones the map has.

All numbers are decimetres in local coordinates (x east, z south from the centre of the area), heights in decimetres
above Ordnance Datum. Output: data/build/live.json
  {"buildings": [[ground, top, x0, z0, x1, z1, ...], ...], "trees": [x, z, ground, height, radius, ...]}
"""

import json

import numpy as np
from PIL import Image, ImageDraw

from config import BUILD, CX, CY, LIDAR_RES, XMIN, YMAX


def main():
    dtm, dsm = np.load(BUILD / "dtm.npy"), np.load(BUILD / "dsm.npy")
    buildings = []
    for ring in json.load(open(BUILD / "footprints.json")):
        px = [((x + CX - XMIN) / LIDAR_RES, (YMAX - (CY - z)) / LIDAR_RES) for x, z in ring]
        c0, r0 = int(min(p[0] for p in px)), int(min(p[1] for p in px))
        c1, r1 = int(max(p[0] for p in px)) + 2, int(max(p[1] for p in px)) + 2
        if c0 < 0 or r0 < 0 or c1 > dtm.shape[1] or r1 > dtm.shape[0]:
            continue
        mask = Image.new("L", (c1 - c0, r1 - r0), 0)
        ImageDraw.Draw(mask).polygon([(x - c0, y - r0) for x, y in px], fill=1)
        inside = np.asarray(mask) > 0
        if not inside.any():
            continue
        ground = float(dtm[r0:r1, c0:c1][inside].min())
        top = max(ground + 2.4, float(np.percentile(dsm[r0:r1, c0:c1][inside], 85)))
        buildings.append([round(ground * 10), round(top * 10)] + [round(c * 10) for point in ring for c in point])
    t = np.fromfile(BUILD / "trees.bin", dtype=np.float32).reshape(-1, 11)  # x, z, height, crown radius, ..., ground
    trees = np.round(t[:, [0, 1, 10, 2, 3]] * 10).astype(int).ravel().tolist()
    (BUILD / "live.json").write_text(json.dumps({"buildings": buildings, "trees": trees}, separators=(",", ":")))
    print(f"{len(buildings)} buildings and {len(t)} trees for the live viewer")


if __name__ == "__main__":
    main()
