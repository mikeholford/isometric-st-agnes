# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy", "scipy", "scikit-image", "pillow"]
# ///
"""Find individual trees in the lidar canopy height model (first-return surface minus bare earth).

Output (data/build/):
  trees.bin   float32 per tree: x, z, height, crown radius, crown base, kind, r, g, b, seed, ground height
  chm.npy     canopy height model at LIDAR_RES (row 0 north), used for hedges, scrub and shadows
"""

import json

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage as ndi
from skimage.segmentation import watershed

from config import BUILD, CX, CY, LIDAR_RES as RES, RAW, XMIN, YMAX
from geo import wgs_to_grid

COLS = 11


def footprint_mask(shape, grow_m):
    img = Image.new("L", (shape[1], shape[0]), 0)
    d = ImageDraw.Draw(img)
    for ring in json.load(open(BUILD / "footprints.json")):
        d.polygon([((x + CX - XMIN) / RES, (YMAX - (CY - z)) / RES) for x, z in ring], fill=255)
    m = np.array(img) > 0
    return ndi.binary_dilation(m, iterations=max(1, int(grow_m / RES)))


def main():
    dtm, dsm, sea = np.load(BUILD / "dtm.npy"), np.load(BUILD / "dsm.npy"), np.load(BUILD / "sea.npy")
    chm = np.clip(dsm - dtm, 0, None)
    chm[footprint_mask(chm.shape, 1.5)] = 0
    chm[sea] = 0
    # On a cliff the first return and the bare earth differ by metres without anything growing there: the two
    # models smooth a near-vertical face differently. Nothing counts as canopy where the ground is that steep.
    gy, gx = np.gradient(ndi.gaussian_filter(dtm, 1.0), RES)
    steep = np.hypot(gx, gy) > 1.0  # 45 degrees
    chm[ndi.binary_dilation(steep, iterations=2)] = 0
    chm[chm > 35] = 0  # a bird, a wire
    np.save(BUILD / "chm.npy", chm.astype(np.float16))

    smooth = ndi.gaussian_filter(chm, 0.7)
    canopy = smooth > 2.5
    peaks = (smooth == ndi.maximum_filter(smooth, size=3)) & (smooth > 3.5)
    ys, xs = np.nonzero(peaks)
    hs = smooth[ys, xs]

    # Greedy suppression: taller trees claim a radius that grows with their height.
    order = np.argsort(-hs)
    taken = np.zeros_like(peaks)
    keep = []
    for i in order:
        y, x, h = ys[i], xs[i], hs[i]
        if taken[y, x]:
            continue
        keep.append(i)
        r = int(round(np.clip(0.12 * h + 1.0, 1.5, 4.5) / RES))
        taken[max(0, y - r) : y + r + 1, max(0, x - r) : x + r + 1] = True
    ys, xs, hs = ys[keep], xs[keep], hs[keep]

    markers = np.zeros(chm.shape, dtype=np.int32)
    markers[ys, xs] = np.arange(1, len(ys) + 1)
    labels = watershed(-smooth, markers, mask=canopy)
    areas = ndi.sum_labels(np.ones_like(labels), labels, index=np.arange(1, len(ys) + 1)) * RES * RES
    radius = np.clip(np.sqrt(areas / np.pi), 1.0, 7.5)

    # No open aerial photo here to tell evergreens from the rest. On this coast nearly every tree is a wind-cut
    # sycamore, ash or thorn; a few gardens and shelter belts have Monterey pine and cypress.
    rng = np.random.default_rng(7)
    kind = (rng.random(len(hs)) < 0.06).astype(np.float32)
    wx = XMIN + (xs + 0.5) * RES
    wy = YMAX - (ys + 0.5) * RES
    base = np.clip(hs * rng.uniform(0.25, 0.4, len(hs)), 1.2, 6)
    ground = dtm[ys, xs]
    grey = np.full(len(hs), 0.35)
    trees = np.stack([wx - CX, CY - wy, hs, radius, base, kind, grey, grey + 0.07, grey - 0.1, rng.random(len(hs)), ground], -1).astype(np.float32)

    # Single trees mapped in OpenStreetMap that the canopy model missed (young street trees).
    extra = []
    path = RAW / "osm_landmarks.json"
    if path.exists():
        have = np.zeros(chm.shape, bool)
        have[ys, xs] = True
        have = ndi.binary_dilation(have, iterations=int(3 / RES))
        for el in json.loads(path.read_text())["elements"]:
            if el["type"] != "node" or el.get("tags", {}).get("natural") != "tree":
                continue
            x, y = wgs_to_grid(el["lat"], el["lon"])
            col, row = int((x - XMIN) / RES), int((YMAX - y) / RES)
            if not (0 <= col < chm.shape[1] and 0 <= row < chm.shape[0]) or have[row, col] or sea[row, col]:
                continue
            h = max(float(chm[row, col]), 4.0 + rng.random() * 3)
            extra.append([x - CX, CY - y, h, 1.2 + h * 0.15, 1.5, 0, 0.35, 0.42, 0.25, rng.random(), dtm[row, col]])
    if extra:
        trees = np.concatenate([trees, np.array(extra, dtype=np.float32)])
    # Masts and mine stacks show up in the canopy model as very tall, thin "trees"; so do the roofless walls of an
    # engine house.
    lm = BUILD / "landmarks.json"
    named = json.loads(lm.read_text()) if lm.exists() else {}
    tall = list(named.get("masts", []))
    for b in named.get("buildings", {}).values():
        tall += b.get("stacks", [])
        if b.get("style") == "engine" and b.get("stacks"):
            tall += [{"x": s["x"] - s["dx"], "y": s["y"] - s["dy"]} for s in b["stacks"]]
    for m in tall:
        trees = trees[np.hypot(trees[:, 0] - (m["x"] - CX), trees[:, 1] - (CY - m["y"])) > 9]
    trees.tofile(BUILD / "trees.bin")
    print(f"{len(trees)} trees ({len(extra)} from OpenStreetMap), {int(kind.sum())} evergreen, mean radius {radius.mean():.1f} m")


if __name__ == "__main__":
    main()
