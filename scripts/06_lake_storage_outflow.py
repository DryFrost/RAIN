"""Terrain-derived level-pool storage-outflow curves for on-stream lakes.

For each lake (GIS/HMS_Raymore.gpkg layer Lakes):
  * normal pool = lidar (hydro-flattened) water surface, i.e. the lake is full
    at the start of the storm -- the same assumption the FEMA RoG model makes
    because the terrain has no bathymetry;
  * storage(E) = volume above normal pool of the 1 m terrain cells connected
    to the lake and inside the lake's contributing subbasins;
  * outflow(E): broad-crested weir (C = 2.6, FEMA's road/weir coefficient),
    strip-integrated across a 1 m terrain transect at the spill sill.  The
    sill is the location on the D8 outflow path (water's edge to 100 ft past
    the subbasin outlet) whose cross-section low point is highest.  No principal-spillway pipe is represented (none is in
    the FEMA model or the terrain) -- replace with as-built outlet data.

Outputs: HMS/parameters/lake_<name>_rating.csv and lake_ratings.json
"""
from pathlib import Path
import sys
import json
import numpy as np
import pandas as pd
import geopandas as gpd
import rasterio
from rasterio.features import rasterize
from scipy import ndimage
from shapely.geometry import LineString, Point

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hydro  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
GPKG = ROOT / "GIS/HMS_Raymore.gpkg"
R10 = ROOT / "GIS/rasters"
DEM1M = ROOT / "Resources/2D_Raymore/Terrain/FinalTerrain.hydroDEM.tif"
PAR = ROOT / "HMS/parameters"
C_WEIR = 2.6
DE = 0.25         # ft, elevation increment
H_MAX = 10.0      # ft above normal pool
HALF_XS = 500.0   # ft, half-length of the crest transect


def main():
    LK = gpd.read_file(GPKG, layer="Lakes")
    S = gpd.read_file(GPKG, layer="Subbasins")
    with rasterio.open(R10 / "fdir_10ft.tif") as s:
        F = s.read(1).astype(np.int64)
        tr10 = s.transform
    nr, nc = F.shape
    down, step = hydro.downstream_index(F)
    dem = rasterio.open(DEM1M)
    out = {}
    for _, lk in LK.iterrows():
        name, wse, poly = lk.Lake, float(lk.WSE_ft), lk.geometry
        subs = S[(S.Subbasin == f"SB-{name}") | S.Subbasin.str.startswith(f"SB-{name}-IN")]
        region = subs.geometry.union_all()
        # ---- 1 m window
        xmin, ymin, xmax, ymax = region.buffer(HALF_XS).bounds
        win = rasterio.windows.from_bounds(xmin, ymin, xmax, ymax, transform=dem.transform).round_offsets().round_lengths()
        Z = dem.read(1, window=win).astype(float)
        t1 = dem.window_transform(win)
        a1 = t1.a ** 2
        reg = rasterize([(region, 1)], out_shape=Z.shape, transform=t1).astype(bool)
        seed = rasterize([(poly, 1)], out_shape=Z.shape, transform=t1).astype(bool)
        # ---- crest along the D8 path from inside the lake
        c, r = ~tr10 * (poly.representative_point().x, poly.representative_point().y)
        start = int(r) * nc + int(c)
        path = hydro.trace_down(start, down, np.zeros(nr * nc, bool), 5000)
        xy = [tr10 * ((p % nc) + 0.5, (p // nc) + 0.5) for p in path]
        o = int(lk.outlet_cell)
        k_out = list(path).index(o) if o in path else len(path) - 1
        line = LineString(xy)
        d_out = line.project(Point(xy[k_out]))
        dd = np.arange(0, min(line.length, d_out + 100.0), t1.a)
        pts = [line.interpolate(x) for x in dd]
        zp = np.array([v[0] for v in dem.sample([(p.x, p.y) for p in pts])], float)
        outside = np.array([not poly.buffer(3).contains(p) for p in pts])
        k0 = int(np.argmax(outside)) if outside.any() else 0
        offs = np.arange(-HALF_XS, HALF_XS + 1e-6, t1.a)
        ic = int(np.argmin(np.abs(offs)))
        best = None
        poly_b = poly.buffer(5).simplify(2)
        # sill = location on the outflow path whose transect low point is highest
        for k in range(k0, len(pts), 3):
            a_ = line.interpolate(max(dd[k] - 30, 0))
            b_ = line.interpolate(min(dd[k] + 30, line.length))
            ux, uy = b_.x - a_.x, b_.y - a_.y
            nrm = np.hypot(ux, uy) or 1.0
            ux, uy = ux / nrm, uy / nrm
            tx, ty = pts[k].x - uy * offs, pts[k].y + ux * offs
            zt = np.array([v[0] for v in dem.sample(list(zip(tx, ty)))], float)
            inlake = np.array([poly_b.contains(Point(x_, y_)) for x_, y_ in zip(tx, ty)])
            zt[inlake] = np.inf          # the pool itself is not part of the control
            cen = (np.abs(offs) <= 40) & np.isfinite(zt)
            if not cen.any():
                continue
            zmin = float(zt[cen].min())
            if best is None or zmin > best[0]:
                best = (zmin, k, tx, ty, zt)
        zsill, kc, tx, ty, zt = best
        crest_pt = pts[kc]
        z_crest = max(zsill, wse)
        ic = int(np.argmin(np.where(np.abs(offs) <= 40, zt, np.inf)))
        zt = np.where(np.isfinite(zt), zt, 1e9)
        # ---- rating
        E = np.round(np.arange(wse, wse + H_MAX + 1e-6, DE), 3)
        base = None
        rows = []
        for e in E:
            wet = (Z < e) & reg
            lab, _ = ndimage.label(wet | seed, structure=np.ones((3, 3)))
            ids = np.unique(lab[seed])
            comp = np.isin(lab, ids[ids > 0])
            vol = float(np.clip(e - Z[comp], 0, None).sum() * a1 / 43560.0)
            base = vol if base is None else base
            sto = vol - base
            # weir over the connected low run of the crest transect
            q = 0.0
            if e > z_crest:
                w = zt < e
                lo = hi = ic
                while lo > 0 and w[lo - 1]:
                    lo -= 1
                while hi < len(w) - 1 and w[hi + 1]:
                    hi += 1
                hd = np.clip(e - zt[lo:hi + 1], 0, None)
                q = float(C_WEIR * t1.a * (hd ** 1.5).sum())
            rows.append(dict(Elev_ft=e, Storage_acft=sto, Outflow_cfs=q, Area_ac=float(comp.sum() * a1 / 43560.0)))
        df = pd.DataFrame(rows)
        PAR.mkdir(parents=True, exist_ok=True)
        df.round(3).to_csv(PAR / f"lake_{name}_rating.csv", index=False)
        out[name] = dict(wse=wse, crest=z_crest, crest_xy=[crest_pt.x, crest_pt.y],
                         crest_dist_from_waters_edge_ft=float(dd[kc] - dd[k0]),
                         transect=[[tx[0], ty[0]], [tx[-1], ty[-1]]],
                         storage_at_crest_acft=float(np.interp(z_crest, df.Elev_ft, df.Storage_acft)))
        print(f"{name}: WSE {wse:.2f}  crest {z_crest:.2f}  ({dd[kc] - dd[k0]:.0f} ft past water's edge)")
        print(df.iloc[::4].round(1).to_string(index=False))
    (PAR / "lake_ratings.json").write_text(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
