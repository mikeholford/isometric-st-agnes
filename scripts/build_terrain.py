# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy", "scipy", "tifffile", "imagecodecs", "pillow"]
# ///
"""The shape of the land: Environment Agency lidar mosaicked into height grids for every later step.

St Agnes is all relief: cliffs of 60 to 90 m, the Beacon at 192 m, coombes cut down to the coves. So unlike the flat
Peel of the example, the ground here is a real surface that buildings, trees, roads and cars stand on.

Output (data/build/):
  dtm.npy       bare-earth height at LIDAR_RES (1 m), row 0 north, metres above Ordnance Datum; the sea is SEA_LEVEL
  dsm.npy       first-return surface height on the same grid (tree tops, roofs)
  sea.npy       bool mask of the sea on the same grid
  terrain.bin   float32 grid at TERRAIN_RES (2 m), (ny + 1) x (nx + 1) heights, for render/scene.js
  height.bin    the same at VIEWER_RES (4 m) for the viewer: uint16 width and height, then (height + 100 m) in decimetres
  area.json     gains "terrain": {res, nx, ny, sea, min, max} and "height": {res, nx, ny}
"""

import json

import numpy as np
import tifffile
from PIL import Image, ImageDraw
from scipy import ndimage as ndi

from config import BUILD, LIDAR_RES, RAW, SEA_LEVEL, TERRAIN_RES, VIEWER_RES, XMAX, XMIN, YMAX, YMIN, write_area


def mosaic(kind):
    """Every downloaded block of one model (lidar/<kind>_<x0>_<y0>_<w>_<h>.tif, scripts/fetch.py) in one grid."""
    out = np.full((int((YMAX - YMIN) / LIDAR_RES), int((XMAX - XMIN) / LIDAR_RES)), np.nan, dtype=np.float32)
    for path in sorted((RAW / "lidar").glob(f"{kind}_*.tif")):
        x0, y0, w, h = (int(v) for v in path.stem.split("_")[1:])
        a = tifffile.imread(path).astype(np.float32)
        a[(a > 2000) | (a < -50)] = np.nan  # no-data comes as a huge negative number
        rows, cols = int(h / LIDAR_RES), int(w / LIDAR_RES)
        row, col = int((YMAX - (y0 + h)) / LIDAR_RES), int((x0 - XMIN) / LIDAR_RES)
        out[row : row + rows, col : col + cols] = a[:rows, :cols]
    return out


def os_mask(layer, shape):
    """An OS OpenMap Local polygon layer (scripts/fetch.py) as a mask on the lidar grid, or None without the file."""
    path = RAW / f"os_{layer}.geojson"
    if not path.exists():
        return None
    img = Image.new("L", (shape[1], shape[0]), 0)
    d = ImageDraw.Draw(img)
    px = lambda ring: [((x - XMIN) / LIDAR_RES, (YMAX - y) / LIDAR_RES) for x, y, *_ in ring]
    for f in json.loads(path.read_text())["features"]:
        g = f["geometry"]
        for rings in [g["coordinates"]] if g["type"] == "Polygon" else g["coordinates"] if g["type"] == "MultiPolygon" else []:
            d.polygon(px(rings[0]), fill=1)
            for hole in rings[1:]:
                d.polygon(px(hole), fill=0)
    return np.array(img) > 0


def fill_nearest(a, bad):
    idx = ndi.distance_transform_edt(bad, return_distances=False, return_indices=True)
    return a[tuple(idx)]


def sample(grid, res):
    """Heights at the corners of a coarser grid (nx + 1 by ny + 1 points), from the 1 m cells around each corner."""
    step = int(res / LIDAR_RES)
    smooth = ndi.uniform_filter(grid, size=step, mode="nearest") if step > 1 else grid
    ny, nx = grid.shape[0] // step, grid.shape[1] // step
    rows = np.clip(np.arange(ny + 1) * step, 0, grid.shape[0] - 1)
    cols = np.clip(np.arange(nx + 1) * step, 0, grid.shape[1] - 1)
    return smooth[np.ix_(rows, cols)], nx, ny


def main():
    BUILD.mkdir(parents=True, exist_ok=True)  # the first step to write there, on a fresh checkout
    dtm, dsm = mosaic("dtm"), mosaic("dsm")
    # The sea. The lidar is no help: it measured the water surface, anywhere from -3.8 to +0.4 m depending on the
    # tide when each strip was flown. The Ordnance Survey's low water mark is: the sea is OpenMap Local's tidal
    # water less its foreshore. Without that layer, fall back on height: low ground joined to the map's edge.
    sea = os_mask("tidalwater", dtm.shape)
    if sea is not None:
        shore = os_mask("foreshore", dtm.shape)
        sea &= ~shore if shore is not None else True
        sea = ndi.binary_opening(sea, iterations=1)
    else:
        low = np.isnan(dtm) | (dtm < SEA_LEVEL)
        lab, _ = ndi.label(low)
        edge = np.unique(np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]]))
        sizes = ndi.sum_labels(low, lab, np.arange(lab.max() + 1))
        sea = np.isin(lab, [int(k) for k in edge if k and sizes[k] > 20000])
    # Holes inland (ponds, shafts, a missing swath) take the height next to them.
    hole = np.isnan(dtm) & ~sea
    dtm = fill_nearest(np.where(sea, np.nan, dtm), hole) if hole.any() else dtm
    # The foreshore was partly under water when the lidar flew; nothing on land lies below the tide we draw.
    dtm = np.where(sea, SEA_LEVEL, np.maximum(dtm, SEA_LEVEL + 0.15)).astype(np.float32)
    dsm = np.where(np.isnan(dsm) | sea, dtm, dsm).astype(np.float32)
    dsm = np.maximum(dsm, dtm)
    np.save(BUILD / "dtm.npy", dtm)
    np.save(BUILD / "dsm.npy", dsm)
    np.save(BUILD / "sea.npy", sea)

    grid, nx, ny = sample(dtm, TERRAIN_RES)
    grid.astype(np.float32).tofile(BUILD / "terrain.bin")
    small, vx, vy = sample(dtm, VIEWER_RES)
    q = np.clip(np.round((small + 100) * 10), 0, 65535).astype(np.uint16)
    # Plain numbers, not a picture: a browser may adjust the colours of a picture for the screen, and one step of
    # red is 25 m of height. Two uint16 for width and height, then the rows from the north, little-endian.
    (BUILD / "height.bin").write_bytes(np.array(q.shape[::-1], "<u2").tobytes() + q.astype("<u2").tobytes())

    write_area()
    area = json.loads((BUILD / "area.json").read_text())
    area["terrain"] = {"res": TERRAIN_RES, "nx": nx, "ny": ny, "sea": SEA_LEVEL, "min": float(dtm.min()), "max": float(dtm.max())}
    area["height"] = {"res": VIEWER_RES, "nx": vx, "ny": vy}
    (BUILD / "area.json").write_text(json.dumps(area))
    print(f"terrain {nx}x{ny} at {TERRAIN_RES} m, {dtm.min():.1f} to {dtm.max():.1f} m, {sea.mean():.0%} sea, {int(hole.sum())} cells filled")


if __name__ == "__main__":
    main()
