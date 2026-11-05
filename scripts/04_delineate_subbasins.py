"""Delineate the subject watershed and HMS subbasins / reaches / junctions.

Outlet: user point 38.770832, -94.492901 -> FEMA bridge 29037ECT030 (East Creek
Trib 12).  Subbasin break points:
  * every FEMA SA/2D connection (road crossing) inside the watershed
  * every FEMA reference line inside the watershed (for RoG comparison)
  * stream confluences where both branches drain >= CONF_AC
  * extra main-stem points so no subbasin exceeds MAX_AC
Points that land within MERGE_FT (flow distance) of a higher-priority point are
merged into it.

Outputs: GIS/HMS_Raymore.gpkg  (layers: Watershed, Subbasins, Junctions,
Reaches, Streams, LongestFlowPaths) and GIS/rasters/subbasins_10ft.tif
"""
from pathlib import Path
import sys
import json
import numpy as np
import rasterio
from rasterio.features import rasterize, shapes
import geopandas as gpd
import pandas as pd
from shapely.geometry import shape, Point, LineString
from pyproj import Transformer

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hydro  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
FEMA = ROOT / "GIS/FEMA_RoG_geometry.gpkg"
RAS = ROOT / "GIS/rasters"
OUT = ROOT / "GIS/HMS_Raymore.gpkg"

USER_LATLON = (38.770831896544465, -94.49290058921302)
OUTLET_STRUCT = "29037ECT030"
STREAM_AC = 25.0     # streams drawn / reach network threshold
CONF_AC = 60.0       # both branches must exceed this to place a confluence point
MIN_PT_AC = 15.0     # ignore structure/ref points draining less than this
MERGE_FT = 250.0     # merge points closer than this along the flow path
MAX_AC = 260.0       # split subbasins larger than this along the main stem
MIN_LOCAL_AC = 8.0   # drop confluence/split points whose local area is smaller
LAKE_MIN_AC = 5.0    # open-water bodies on the stream network at least this big become lakes
LAKE_TRIB_AC = 40.0  # tributaries entering a lake with at least this area get their own subbasin
LAKE_BUF_FT = 25.0   # dissolve distance for water polygons split by causeways / bridges
LCOVER = ROOT / "Resources/2D_Raymore/Land Classification/LandCover.tif"
DEM1M = ROOT / "Resources/2D_Raymore/Terrain/FinalTerrain.hydroDEM.tif"


def find_lakes(tr, crs, inws2d, acc2d, cell_ac):
    """Open-water polygons (FEMA land cover id 11) inside the watershed that
    sit on the stream network (>= STREAM_AC) and are >= LAKE_MIN_AC."""
    from rasterio.windows import from_bounds
    rows, cols = np.nonzero(inws2d)
    xmin, ymax = tr * (cols.min(), rows.min())
    xmax, ymin = tr * (cols.max() + 1, rows.max() + 1)
    with rasterio.open(LCOVER) as s:
        w = from_bounds(xmin, ymin, xmax, ymax, transform=s.transform)
        lc = s.read(1, window=w)
        t = s.window_transform(w)
    water = (lc == 11).astype(np.uint8)
    polys = [shape(g) for g, v in shapes(water, mask=water == 1, transform=t)]
    if not polys:
        return []
    merged = gpd.GeoSeries(polys, crs=crs).buffer(LAKE_BUF_FT).union_all().buffer(-LAKE_BUF_FT)
    parts = list(merged.geoms) if hasattr(merged, "geoms") else [merged]
    stream = (acc2d >= STREAM_AC / cell_ac) & inws2d
    dem = rasterio.open(DEM1M)
    out = []
    for p in parts:
        if p.area / 43560.0 < LAKE_MIN_AC:
            continue
        m = rasterize([(p.buffer(15), 1)], out_shape=stream.shape, transform=tr, all_touched=True).astype(bool)
        if not (m & stream).any():
            continue
        c = p.representative_point()
        out.append(dict(geometry=p, wse=float(list(dem.sample([(c.x, c.y)]))[0][0])))
    return sorted(out, key=lambda d: -d["geometry"].area)


def main():
    with rasterio.open(RAS / "fdir_10ft.tif") as src:
        F = src.read(1).astype(np.int64)
        tr, crs = src.transform, src.crs
    A = rasterio.open(RAS / "acc_10ft.tif").read(1).ravel().astype(np.float64)
    nr, nc = F.shape
    cs = tr.a
    cell_ac = cs * cs / 43560.0
    down, step = hydro.downstream_index(F)
    order = hydro.topo_order(down)

    def xy(i):
        return tr * ((i % nc) + 0.5, (i // nc) + 0.5)

    def max_acc_on(geom, buf=0.0):
        m = rasterize([(geom.buffer(buf) if buf else geom, 1)], out_shape=F.shape, transform=tr,
                      all_touched=True).astype(bool).ravel()
        idx = np.flatnonzero(m)
        return int(idx[A[idx].argmax()]) if idx.size else -1

    st = gpd.read_file(FEMA, layer="Structures")
    rl = gpd.read_file(FEMA, layer="Reference_Lines")

    # ---- outlet & watershed
    out_i = max_acc_on(st.loc[st.Connection == OUTLET_STRUCT].geometry.iloc[0])
    ol = np.zeros(nr * nc, np.int64)
    ol[out_i] = 1
    ws_lab = hydro.label_basins(down, order, ol)
    inws = ws_lab == 1
    print(f"watershed area {inws.sum() * cell_ac / 640:.3f} sq mi")

    # ---- candidate points: (flat index, name, kind, priority)
    pts = {out_i: dict(name=OUTLET_STRUCT.replace("29037", ""), kind="Outlet", prio=0,
                       fema_struct=OUTLET_STRUCT, fema_ref="")}
    for _, r in st.iterrows():
        if r.Connection == OUTLET_STRUCT or r.Connection == "HydrographBL":
            continue
        i = max_acc_on(r.geometry)
        if i < 0 or not inws[i] or A[i] * cell_ac < MIN_PT_AC:
            continue
        pts.setdefault(i, dict(name=r.Connection.replace("29037", ""), kind="Structure", prio=1,
                               fema_struct=r.Connection, fema_ref=""))
    for _, r in rl.iterrows():
        i = max_acc_on(r.geometry, buf=15)
        if i < 0 or not inws[i] or A[i] * cell_ac < MIN_PT_AC:
            continue
        nm = "RL_" + r.Name.replace("sqmi", "")
        if i in pts:
            pts[i]["fema_ref"] = r.Name
        else:
            pts[i] = dict(name=nm, kind="RefLine", prio=2, fema_struct="", fema_ref=r.Name)

    # confluences: cell whose >=2 upstream neighbours each drain >= CONF_AC
    thr = CONF_AC / cell_ac
    big = np.flatnonzero(inws & (A >= thr))
    cnt = np.zeros(nr * nc, np.int32)
    np.add.at(cnt, down[big][down[big] >= 0], 1)
    conf = np.flatnonzero((cnt >= 2) & inws)
    for k, i in enumerate(sorted(conf, key=lambda j: -A[j])):
        if i not in pts:
            pts[i] = dict(name=f"CNF{k + 1:02d}", kind="Confluence", prio=3, fema_struct="", fema_ref="")

    # ---- on-stream lakes (FEMA land cover "Open Water"), modelled as level-pool storage
    lakes = find_lakes(tr, crs, inws.reshape(nr, nc), A.reshape(nr, nc), cell_ac)
    lake_rows = []
    lake_mask = np.zeros(nr * nc, bool)
    for k, lk in enumerate(lakes, start=1):
        poly = lk["geometry"]
        inside = rasterize([(poly.buffer(LAKE_BUF_FT), 1)], out_shape=F.shape, transform=tr,
                           all_touched=True).astype(bool).ravel()
        lake_mask |= inside
        for i in [i for i in pts if inside[i] and pts[i]["kind"] != "Outlet"]:
            del pts[i]
        o = max_acc_on(poly.buffer(LAKE_BUF_FT))
        nm = f"LK{k}"
        pts[o] = dict(name=nm, kind="Lake", prio=0.5, fema_struct="", fema_ref="")
        lake_rows.append(dict(Lake=nm, Area_ac=poly.area / 43560.0, WSE_ft=lk["wse"], outlet_cell=int(o),
                              geometry=poly))
        print(f"lake {nm}: {poly.area / 43560:.1f} ac, WSE {lk['wse']:.1f}, DA {A[o] * cell_ac / 640:.2f} sq mi")
        # tributary inflow points: last cell outside the pool on every stream >= LAKE_TRIB_AC
        trib = np.flatnonzero(inws & ~inside & (A >= LAKE_TRIB_AC / cell_ac))
        trib = [i for i in trib if down[i] >= 0 and inside[down[i]]]
        for t, i in enumerate(sorted(trib, key=lambda j: -A[j]), start=1):
            pts[i] = dict(name=f"{nm}-IN{t}", kind="LakeInflow", prio=2.5, fema_struct="", fema_ref="")
            print(f"   inflow {nm}-IN{t}: {A[i] * cell_ac:.0f} ac")

    # ---- merge points that are close along the flow path
    def flow_dist_down(i, j_set, maxft):
        d, cur = 0.0, i
        while True:
            nxt = down[cur]
            if nxt < 0:
                return None
            d += step[cur] * cs
            if d > maxft:
                return None
            if nxt in j_set:
                return nxt, d
            cur = nxt

    def merge_close():
        changed = True
        while changed:
            changed = False
            keys = set(pts)
            for i in sorted(pts, key=lambda j: A[j]):
                r = flow_dist_down(i, keys - {i}, MERGE_FT)
                if r is None:
                    continue
                j, d = r
                pi, pj = pts[i], pts[j]
                if pi["prio"] < pj["prio"]:          # keep the more important upstream point
                    pi["fema_ref"] = pi["fema_ref"] or pj["fema_ref"]
                    pi["fema_struct"] = pi["fema_struct"] or pj["fema_struct"]
                    del pts[j]
                else:
                    pj["fema_ref"] = pj["fema_ref"] or pi["fema_ref"]
                    pj["fema_struct"] = pj["fema_struct"] or pi["fema_struct"]
                    del pts[i]
                changed = True
                break

    merge_close()

    def relabel():
        lab_in = np.zeros(nr * nc, np.int64)
        ids = sorted(pts, key=lambda j: -A[j])
        for n, i in enumerate(ids, start=1):
            lab_in[i] = n
        lab = hydro.label_basins(down, order, lab_in)
        lab[~inws] = 0
        return ids, lab

    # ---- split oversize subbasins along their main stem
    nosplit = set()
    for _ in range(60):
        ids, lab = relabel()
        areas = np.bincount(lab, minlength=len(ids) + 1) * cell_ac
        cand = [n for n, i in enumerate(ids, start=1) if i not in nosplit and areas[n] > MAX_AC]
        if not cand:
            break
        worst = max(cand, key=lambda n: areas[n])
        o = ids[worst - 1]
        # inflow from upstream points into this subbasin
        target = A[o] - (areas[worst] / cell_ac) / 2.0
        # walk upstream along the max-accumulation neighbour inside this subbasin
        cur = o
        while True:
            r_, c_ = divmod(cur, nc)
            best, bv = -1, -1.0
            for k in range(8):
                rr, cc = r_ - hydro.DR[k], c_ - hydro.DC[k]
                if 0 <= rr < nr and 0 <= cc < nc:
                    j = rr * nc + cc
                    if down[j] == cur and lab[j] == worst and A[j] > bv:
                        best, bv = j, A[j]
            if best < 0 or A[best] < target or lake_mask[best]:
                break
            cur = best
        if cur == o or cur in pts:
            print("cannot split", pts[o]["name"], round(areas[worst]))
            nosplit.add(o)
            continue
        k = sum(1 for p in pts.values() if p["kind"] == "Split") + 1
        pts[cur] = dict(name=f"SPL{k:02d}", kind="Split", prio=4, fema_struct="", fema_ref="")
        n_before = len(pts)
        merge_close()
        if len(pts) < n_before:       # split landed next to an existing point
            print("split merged away for", pts[o]["name"] if o in pts else o, round(areas[worst]))
            nosplit.add(o)

    # ---- drop tiny confluence / split subbasins
    for _ in range(50):
        ids, lab = relabel()
        areas = np.bincount(lab, minlength=len(ids) + 1) * cell_ac
        small = [(areas[n], i) for n, i in enumerate(ids, start=1)
                 if pts[i]["kind"] in ("Confluence", "Split") and areas[n] < MIN_LOCAL_AC]
        if not small:
            break
        del pts[min(small)[1]]

    # ---- nothing but the lake outlet may sit inside a lake
    for i in [i for i in pts if lake_mask[i] and pts[i]["kind"] not in ("Lake", "Outlet", "LakeInflow")]:
        del pts[i]

    ids, lab = relabel()
    areas = np.bincount(lab, minlength=len(ids) + 1) * cell_ac

    # ---- topology: downstream point of each point
    idset = set(ids)
    dn_of, reach_path = {}, {}
    for i in ids:
        path, cur = [i], down[i]
        while cur >= 0 and inws[cur] and cur not in idset:
            path.append(cur)
            cur = down[cur]
        if cur >= 0 and cur in idset:
            path.append(cur)
            dn_of[i] = cur
            reach_path[i] = path
        else:
            dn_of[i] = None

    # ---- names
    tf = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
    jrows, srows, rrows = [], [], []
    name_of = {i: pts[i]["name"] for i in ids}
    for n, i in enumerate(ids, start=1):
        p = pts[i]
        x, y = xy(i)
        lon, lat = tf.transform(x, y)
        jrows.append(dict(Junction=f"J-{p['name']}", PointKind=p["kind"], FEMA_Struct=p["fema_struct"],
                          FEMA_RefLine=p["fema_ref"], DA_sqmi=A[i] * cell_ac / 640, Local_ac=areas[n],
                          Downstream=(f"R-{p['name']}" if dn_of[i] is not None else ""),
                          Lat=lat, Lon=lon, cell=int(i), label=n, geometry=Point(x, y)))
        if dn_of[i] is not None:
            coords = [xy(k) for k in reach_path[i]]
            rrows.append(dict(Reach=f"R-{p['name']}", FromJ=f"J-{p['name']}", ToJ=f"J-{name_of[dn_of[i]]}",
                              Length_ft=float(sum(step[k] * cs for k in reach_path[i][:-1])),
                              up_cell=int(i), dn_cell=int(dn_of[i]), geometry=LineString(coords)))

    # subbasin polygons
    labr = lab.reshape(nr, nc).astype(np.int32)
    polys = {}
    for geom, v in shapes(labr, mask=labr > 0, transform=tr):
        v = int(v)
        g = shape(geom)
        polys.setdefault(v, []).append(g)
    for n, i in enumerate(ids, start=1):
        g = gpd.GeoSeries(polys[n]).union_all()
        p = pts[i]
        srows.append(dict(Subbasin=f"SB-{p['name']}", Junction=f"J-{p['name']}", Area_ac=areas[n],
                          Area_sqmi=areas[n] / 640, label=n, outlet_cell=int(i), geometry=g))

    J = gpd.GeoDataFrame(jrows, crs=crs)
    S = gpd.GeoDataFrame(srows, crs=crs)
    R = gpd.GeoDataFrame(rrows, crs=crs)

    # watershed + streams
    wsg = gpd.GeoSeries([g for g in S.geometry]).union_all()
    W = gpd.GeoDataFrame(dict(Name=["East Creek Trib 12 @ " + OUTLET_STRUCT], Area_sqmi=[wsg.area / 27878400],
                              Outlet_Lat=[USER_LATLON[0]], Outlet_Lon=[USER_LATLON[1]]), geometry=[wsg], crs=crs)
    stream = inws & (A >= STREAM_AC / cell_ac)
    sidx = np.flatnonzero(stream)
    segs = [LineString([xy(i), xy(down[i])]) for i in sidx if down[i] >= 0 and stream[down[i]]]
    from shapely.ops import linemerge
    merged = linemerge(segs)
    lines = list(merged.geoms) if hasattr(merged, "geoms") else [merged]
    ST = gpd.GeoDataFrame(dict(id=range(len(lines))), geometry=lines, crs=crs)
    ST["DA_sqmi"] = [A[int((~tr * l.coords[-1])[1]) * nc + int((~tr * l.coords[-1])[0])] * cell_ac / 640 for l in lines]

    OUT.unlink(missing_ok=True)
    W.to_file(OUT, layer="Watershed")
    S.to_file(OUT, layer="Subbasins")
    J.to_file(OUT, layer="Junctions")
    R.to_file(OUT, layer="Reaches")
    ST.to_file(OUT, layer="Streams")
    if lake_rows:
        LK = gpd.GeoDataFrame(lake_rows, crs=crs)
        jmap = {int(c): n for n, c in zip(J.Junction, J.cell)}
        LK["Junction"] = [jmap.get(int(c), "") for c in LK.outlet_cell]
        LK.to_file(OUT, layer="Lakes")
    prof = dict(driver="GTiff", height=nr, width=nc, count=1, crs=crs, transform=tr, compress="deflate",
                dtype="int16", nodata=0)
    with rasterio.open(RAS / "subbasins_10ft.tif", "w", **prof) as d:
        d.write(labr.astype(np.int16), 1)

    print(f"{len(S)} subbasins, {len(R)} reaches, {len(J)} junctions")
    print(S.Area_ac.describe().round(1).to_string())
    print(J.PointKind.value_counts().to_string())


if __name__ == "__main__":
    main()
