"""A building as the lidar saw it: its real footprint and its real roof planes.

OS OpenMap Local gives a simplified rectangle for a house. The lidar surface model shows the house itself, a height
every metre. This module lays a 1 m grid over an outline, turned to stand square to the building, and reads from the
lidar which cells have a roof over them, which way each part of the roof slopes, and how high it is. Cells that
slope the same way and touch form one roof plane; each plane is fitted to the heights, its slope square to the
building. So a gable, a hip, a rear wing and a lean-to come out as they are, with straight eaves and ridges.

lidar_roof() returns the triangles, or None when the lidar shows no building there (built after the survey).
"""

import warnings

import numpy as np
from scipy import ndimage as ndi

from config import LIDAR_RES, XMIN, YMAX

CELL = 1.0
FLAT = 0.2  # a slope under this (rise per metre) is a flat roof
MIN_ROOF = 2.0  # metres above the ground before a cell counts as roofed
JOIN = 1.5  # roof planes that differ by less than this where they meet share an edge; more is a step with a wall


def frame(poly):
    """Centre and axes of the grid: along the long side of the outline and across it."""
    rc = np.array(poly.minimum_rotated_rectangle.exterior.coords)[:4]
    e1, e2 = rc[1] - rc[0], rc[2] - rc[1]
    e = e1 if np.hypot(*e1) >= np.hypot(*e2) else e2
    eu = e / np.hypot(*e)
    return rc.mean(0), eu, np.array([-eu[1], eu[0]])


def sample(grid, east, north):
    return ndi.map_coordinates(grid, [(YMAX - north) / LIDAR_RES - 0.5, (east - XMIN) / LIDAR_RES - 0.5], order=1, mode="nearest")


def fill_from(valid, values):
    """Every cell takes the value of the nearest valid cell."""
    idx = ndi.distance_transform_edt(~valid, return_distances=False, return_indices=True)
    return values[tuple(idx)]


def lidar_roof(poly, dtm, dsm, floor, max_height=None):
    """Returns (roof triangles (n, 3, 3) in grid x, y, z; wall quads (m, 4, 3); wall u (m, 4); cell centres per roof
    triangle and wall quad; eaves height above the floor), or None."""
    from shapely import contains_xy

    c, eu, ev = frame(poly)
    ring = (np.array(poly.exterior.coords) - c) @ np.column_stack([eu, ev])
    u0, v0 = np.floor(ring.min(0)) - 2, None
    u0, v0 = u0[0], u0[1]
    nu, nv = int(np.ceil(ring[:, 0].max() - u0)) + 2, int(np.ceil(ring[:, 1].max() - v0)) + 2
    if nu * nv > 40000:
        return None
    uu, vv = np.meshgrid(u0 + (np.arange(nu) + 0.5) * CELL, v0 + (np.arange(nv) + 0.5) * CELL)
    east, north = c[0] + uu * eu[0] + vv * ev[0], c[1] + uu * eu[1] + vv * ev[1]
    ground, top = sample(dtm, east, north), sample(dsm, east, north)
    h = top - ground
    near = contains_xy(poly.buffer(1.0, join_style="mitre"), east, north)
    mask = near & (h > MIN_ROOF)
    mask = ndi.binary_opening(mask, structure=np.ones((2, 2)))
    inside = contains_xy(poly, east, north)
    if mask.sum() < 6 or (mask & inside).sum() < 0.5 * max(inside.sum(), 1):
        return None
    z = top.copy()
    # A tree over the roof: far higher than the rest, and rough. Those cells take the height of the roof beside them.
    med = ndi.median_filter(z, size=3)
    typical = np.median(z[mask])
    rough = np.abs(z - med) > 0.8
    tree = mask & (((z > typical + 3.5) & ndi.binary_dilation(rough, iterations=1)) | (max_height is not None and False))
    if max_height is not None:
        tree |= mask & (z - floor > max_height)
    if tree.sum() > 0.6 * mask.sum():
        return None
    if tree.any():
        z = fill_from(mask & ~tree, z)
    z = np.where(mask, ndi.median_filter(z, size=3), z)

    # Which way each cell slopes, read on the cells well inside the roof: a cell on the edge is half ground.
    core = ndi.binary_erosion(mask)
    zs = fill_from(mask, z)  # so a gradient at the edge of the roof does not see the ground
    gv, gu = np.gradient(ndi.uniform_filter(zs, size=3, mode="nearest"), CELL)
    cls = np.zeros(mask.shape, np.int8)  # 0 flat, 1 falls toward +u, 2 toward -u, 3 toward +v, 4 toward -v
    steep = np.hypot(gu, gv) >= FLAT
    along_u = np.abs(gu) >= np.abs(gv)
    cls[steep & along_u & (gu < 0)], cls[steep & along_u & (gu > 0)] = 1, 2
    cls[steep & ~along_u & (gv < 0)], cls[steep & ~along_u & (gv > 0)] = 3, 4
    cls = fill_from(core, cls) if core.any() else np.zeros_like(cls)
    cls = np.where(mask, ndi.median_filter(cls, size=3), 0)  # a lone odd cell joins its neighbours

    # Roof planes: touching cells of one class. A plane of a few cells joins the largest plane beside it.
    region = np.zeros(mask.shape, np.int32)
    n = 0
    for k in range(5):
        lab, m = ndi.label(mask & (cls == k))
        region[lab > 0] = lab[lab > 0] + n
        n += m
    sizes = np.bincount(region.ravel(), minlength=n + 1)
    small = mask & (sizes[region] < 5)
    if small.any() and (mask & ~small).any():
        region = np.where(small, fill_from(mask & ~small, region), region)
    height = np.full(mask.shape + (4,), np.nan)  # per cell, at its corners: (u0,v0), (u1,v0), (u1,v1), (u0,v1)
    du, dv = np.array([-0.5, 0.5, 0.5, -0.5]) * CELL, np.array([-0.5, -0.5, 0.5, 0.5]) * CELL
    for r in np.unique(region[mask]):
        cells = region == r
        k = int(np.bincount(cls[cells]).argmax())
        fit = cells & core if (cells & core).sum() >= 4 else cells
        zf = z[fit]
        if k == 0:
            a, su, sv = float(np.median(zf)), 0.0, 0.0
        else:
            t = uu[fit] if k in (1, 2) else vv[fit]
            s, a = np.polyfit(t, zf, 1) if np.ptp(t) > 0 else (0.0, float(np.median(zf)))
            sign = -1 if k in (1, 3) else 1
            s = sign * float(np.clip(sign * s, 0.0, 1.3))
            a = float(np.median(zf - s * t))
            su, sv = (s, 0.0) if k in (1, 2) else (0.0, s)
        for q in range(4):
            height[..., q] = np.where(cells, a + su * (uu + du[q]) + sv * (vv + dv[q]), height[..., q])
    height = np.maximum(height, ground[..., None] + MIN_ROOF)

    # Where planes meet, they share the corner (a ridge, a hip, a valley), unless one stands well above the other.
    pad = np.pad(height, ((1, 1), (1, 1), (0, 0)), constant_values=np.nan)
    # The four cells around a grid vertex each see it as a different corner.
    views = [(slice(0, -1), slice(0, -1), 2), (slice(0, -1), slice(1, None), 3), (slice(1, None), slice(1, None), 0), (slice(1, None), slice(0, -1), 1)]
    stack = np.stack([pad[a, b, q] for a, b, q in views])  # (4, nv + 1, nu + 1)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)  # a vertex with no roof around it is all NaN
        lo, hi, mean = np.nanmin(stack, 0), np.nanmax(stack, 0), np.nanmean(stack, 0)
    shared = (hi - lo) <= JOIN
    for a, b, q in views:
        pad[a, b, q] = np.where(shared & ~np.isnan(pad[a, b, q]), mean, pad[a, b, q])
    height = pad[1:-1, 1:-1]

    def xyz(ui, vi, zz):
        return np.stack([c[0] + ui * eu[0] + vi * ev[0], c[1] + ui * eu[1] + vi * ev[1], zz], -1)

    ii, jj = np.nonzero(mask)
    cu, cv = uu[ii, jj], vv[ii, jj]
    corners = np.stack([xyz(cu + du[q], cv + dv[q], height[ii, jj, q]) for q in range(4)], 1)  # (cells, 4, 3)
    roof = np.concatenate([corners[:, [0, 1, 2]], corners[:, [0, 2, 3]]])
    roof_at = np.concatenate([np.column_stack([east[ii, jj], north[ii, jj]])] * 2)

    walls, wall_u, wall_at = [], [], []
    base = fill_from(mask, ground) - 0.4
    # Each side of a cell: the two corners on it, the neighbour beyond it, and that neighbour's corners on the same line.
    sides = [((1, 2), (0, 1), (0, 3), 1), ((3, 0), (0, -1), (2, 1), 1), ((2, 3), (1, 0), (1, 0), 0), ((0, 1), (-1, 0), (3, 2), 0)]
    for (qa, qb), (di, dj), (na, nb), along_v in sides:
        ni, nj = ii + di, jj + dj
        ok = (ni >= 0) & (ni < nv) & (nj >= 0) & (nj < nu)
        neighbour = np.zeros(len(ii), bool)
        neighbour[ok] = mask[ni[ok], nj[ok]]
        za, zb = height[ii, jj, qa], height[ii, jj, qb]
        low_a, low_b = base[ii, jj].copy(), base[ii, jj].copy()
        nia, nja = np.clip(ni, 0, nv - 1), np.clip(nj, 0, nu - 1)
        low_a[neighbour], low_b[neighbour] = height[nia, nja, na][neighbour], height[nia, nja, nb][neighbour]
        # An outside wall, or a step down to a lower roof: this cell stands above what is beyond the side.
        show = ~neighbour | ((za - low_a > 0.05) | (zb - low_b > 0.05))
        low_a, low_b = np.minimum(low_a, za), np.minimum(low_b, zb)
        ua, va, ub, vb = cu + du[qa], cv + dv[qa], cu + du[qb], cv + dv[qb]
        quad = np.stack([xyz(ua, va, low_a), xyz(ub, vb, low_b), xyz(ub, vb, zb), xyz(ua, va, za)], 1)[show]
        t = np.stack([va, vb, vb, va], 1)[show] if along_v else np.stack([ua, ub, ub, ua], 1)[show]
        walls.append(quad)
        wall_u.append(t)
        wall_at.append(np.column_stack([east[ii, jj], north[ii, jj]])[show])
    eaves = float(np.percentile(height[mask].min(-1), 15)) - floor
    return roof, roof_at, np.concatenate(walls), np.concatenate(wall_u), np.concatenate(wall_at), eaves
