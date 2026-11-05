"""Detention basin inventory and stage-storage-outflow for HMS.

Source polygons: City of Raymore storm GIS layer strm_detetion
(GIS/Raymore_StormGIS.gpkg, scripts/12).  For each basin in the watershed:

  * duplicates (two vintages of the same basin, > 50 % overlap) are merged;
  * outlet = highest-accumulation cell inside the footprint on the terrain +
    storm-sewer flow graph (GIS/rasters/acc_sewer_10ft.tif);
  * drainage area (DA) = every cell whose flow enters the footprint (includes
    upstream basins).  On a flat pool D8 can leave the footprint by a second
    cell; capture links (HMS/parameters/detention_links.csv, used by scripts
    04 and 05) send those cells to the outlet;
  * wet vs dry: lidar water surfaces are flat -- if >= 25 % of the basin's 1 m
    cells lie within 0.1 ft of the most common elevation, the basin is WET
    with a permanent pool at that elevation (storage counted above it);
  * bottom = pool (wet) or the 2nd percentile ground elevation (dry);
  * spill (rim): overflow has to cross every ring 10, 20 and 30 ft outside the
    basin, so the spill is the highest of the rings' lowest points (an inflow
    swale dips the 10 ft ring but rises again further out);
  * storage(E) = volume of 1 m cells below E, connected to the basin, within
    60 ft of it, above the pool / bottom;
  * outflow(E), ASSUMED unless an as-built outlet is entered in
    HMS/parameters/detention_outlets_asbuilt.csv:
      - principal outlet sized to KC APWA 5600 comprehensive control:
        3.0 cfs per acre of drainage area at the spill elevation, rising as an
        orifice (Q ~ sqrt(head)) from the bottom / pool;
      - plus overtopping of the rim: broad-crested weir (C = 2.6) integrated
        along each ring wherever ground < E; the ring that passes the least
        flow controls.
    As-built outlets (one row per element):
      orifice   Size = diameter, Invert = invert
      weir      Size = crest length, Invert = crest (riser window / notch, C = 3.0)
      vnotch    Size = included angle (deg), Invert = vertex, Top_ft = top of
                the notch (constant width above it)
      overflow  Size = crest length, Invert = crest (emergency spillway, C = 2.6)
      barrel    Size = diameter, Invert = invert: caps the flow of the
                orifices, weirs and V-notches that discharge through it
      pool      Invert = design normal (permanent) pool, or the outlet flowline
                of a dry basin whose lidar bottom lies above it.  Below the
                lidar water surface / bottom the storage is extended with the
                area of the pool (or lowest) cells; the rating then starts there.
    The rim term is always added.

Wet ponds shallower than 1 ft (pool at about the rim) get no assumed
structure: they spill over their natural outlet (rim weir only), as the lakes do.

A basin is MODELLED when DA >= 2 ac, it is not one of the on-stream lakes, its
type is not Wet Soil / Treatment / Lake, a dry basin stores at least 0.05 in
of runoff over its DA (rules out small polygons on big creeks), and either storage at spill >= 0.1
ac-ft with depth >= 1 ft, or it is a wet pond of >= 1 ac.  (LK1/LK2 are
routed separately.)

Outputs: GIS/Detention.gpkg (layer basins)
         HMS/parameters/detention_basins.csv
         HMS/parameters/detention_ratings/DET###.csv (Elev_ft, Storage_acft, Outflow_cfs)
"""
from pathlib import Path
import json
import numpy as np
import pandas as pd
import geopandas as gpd
import networkx as nx
import rasterio
from rasterio.features import rasterize
from scipy import ndimage
from shapely.geometry import Point
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import hydro  # noqa: E402
import sewer  # noqa: E402
STORM = ROOT / "GIS/Raymore_StormGIS.gpkg"
HMSG = ROOT / "GIS/HMS_Raymore.gpkg"
DEM1M = ROOT / "Resources/2D_Raymore/Terrain/FinalTerrain.hydroDEM.tif"
ACC = ROOT / "GIS/rasters/acc_sewer_10ft.tif"
FDIR = ROOT / "GIS/rasters/fdir_10ft.tif"
PAR = ROOT / "HMS/parameters"
RAT = PAR / "detention_ratings"
ASBUILT = PAR / "detention_outlets_asbuilt.csv"
OUT = ROOT / "GIS/Detention.gpkg"
CRS = (ROOT / "Resources/2D_Raymore/Projection/Projection.prj").read_text()

RELEASE_CFS_PER_AC = 3.0     # KC APWA 5600 100-yr comprehensive control
C_WEIR = 2.6                 # broad-crested: rim overtopping, emergency spillways
C_WEIR_STRUCT = 3.0          # riser windows / sharp-crested weirs
CD_VNOTCH = 0.58
C_ORIFICE = 0.6
RINGS_FT = (10.0, 20.0, 30.0)
STORAGE_REACH_FT = 60.0
DE = 0.25
ABOVE_RIM_FT = 5.0
AB_COLS = ["Basin", "Kind", "Size_ft", "Invert_ft", "Top_ft", "Source", "Note"]
MIN_STORAGE_IN = 0.05        # dry basins storing less runoff than this over their DA are ignored
TYPE_RANK = {"Detention": 0, "Retention": 1, "Pond": 2, "Lake": 3, "Stream/Pond": 4, "Treatment": 5, "Wet Soil": 6}
NOT_MODELLED_TYPES = {"Wet Soil", "Treatment", "Lake"}


def merge_duplicates(d):
    d = d.reset_index(drop=True)
    g = nx.Graph()
    g.add_nodes_from(d.index)
    sj = gpd.sjoin(d[["geometry"]], d[["geometry"]], predicate="intersects")
    for i, j in zip(sj.index, sj.index_right):
        if i < j:
            a, b = d.geometry[i], d.geometry[j]
            if a.intersection(b).area / max(min(a.area, b.area), 1.0) > 0.5:
                g.add_edge(i, j)
    rows = []
    for comp in nx.connected_components(g):
        sub = d.loc[sorted(comp)]
        types = [t for t in sub.Type if isinstance(t, str)]
        t = min(types, key=lambda x: TYPE_RANK.get(x, 9)) if types else None
        rows.append(dict(City_OBJECTIDs=";".join(str(int(o)) for o in sub.OBJECTID), Type=t,
                         geometry=sub.geometry.union_all().buffer(0)))
    return gpd.GeoDataFrame(rows, crs=d.crs)


def orifice(Q_design, head_design, head):
    """Orifice-like rating scaled so Q(head_design) = Q_design."""
    h = np.clip(head, 0, None)
    return Q_design * np.sqrt(h / max(head_design, 0.1))


def _orifice_full(d, inv, E):
    return C_ORIFICE * np.pi * (d / 2) ** 2 * np.sqrt(2 * 32.2 * np.clip(E - (inv + d / 2), 0, None))


def _vnotch(theta_deg, h):
    return 8 / 15 * CD_VNOTCH * np.sqrt(2 * 32.2) * np.tan(np.radians(theta_deg) / 2) * np.clip(h, 0, None) ** 2.5


def asbuilt_outflow(rows, E):
    """Structure outflow (without the rim) from as-built rows; see the module doc."""
    q = np.zeros_like(E)
    over = np.zeros_like(E)
    for _, r in rows.iterrows():
        if r.Kind == "orifice":
            full = _orifice_full(r.Size_ft, r.Invert_ft, E)
            # partially submerged: weir over the opening below its crown
            part = C_WEIR * r.Size_ft * np.clip(E - r.Invert_ft, 0, None) ** 1.5
            q += np.where(E >= r.Invert_ft + r.Size_ft, full, part)
        elif r.Kind == "weir":
            q += C_WEIR_STRUCT * r.Size_ft * np.clip(E - r.Invert_ft, 0, None) ** 1.5
        elif r.Kind == "vnotch":
            h = E - r.Invert_ft
            top = r.get("Top_ft", np.nan)
            hv = (top - r.Invert_ft) if pd.notna(top) else np.inf
            # width stays at the notch's top width above Top_ft
            q += _vnotch(r.Size_ft, h) - (_vnotch(r.Size_ft, h - hv) if np.isfinite(hv) else 0.0)
        elif r.Kind == "overflow":
            over += C_WEIR * r.Size_ft * np.clip(E - r.Invert_ft, 0, None) ** 1.5
    for _, r in rows[rows.Kind == "barrel"].iterrows():
        q = np.minimum(q, _orifice_full(r.Size_ft, r.Invert_ft, E))
    return q + over


def passthrough_links(polys, outlet):
    """Storm pipe systems that run THROUGH a basin (a pipe node inside it, the
    system outfall beyond it), e.g. inflow pipe -> pond -> outlet pipe under Dean
    Ave digitized as one network.  scripts/02b links every inlet of a system to
    its outfall, so inlets upstream of the pond would skip it.  Returns
    {basin: [(ic, oc, kind)]}: 'pipe_in' sends an inlet whose pipe path passes
    the basin to the basin outlet; 'pipe_out' sends the basin outlet to the
    system outfall (the outlet pipe)."""
    links_csv = PAR / "sewer_links.csv"
    sys_gpkg = ROOT / "GIS/StormSewer_Links.gpkg"
    if not links_csv.exists() or not sys_gpkg.exists():
        return {}
    P, G, xy = sewer.pipe_network()
    comps = [sorted(c) for c in nx.connected_components(G)]
    sy = gpd.read_file(sys_gpkg, layer="systems").set_index("System")
    lk = pd.read_csv(links_csv)
    ends_of_pipe = {dd["pipe"]: (u, v) for u, v, dd in G.edges(data=True)}
    tree = gpd.GeoSeries(P.geometry).sindex
    nodes = np.array(sorted(xy))
    nxy = np.array([xy[nd] for nd in nodes])
    out = {}
    for bid, poly in polys.items():
        zone = poly.buffer(15.0)
        b = zone.bounds
        near = nodes[(nxy[:, 0] >= b[0]) & (nxy[:, 0] <= b[2]) & (nxy[:, 1] >= b[1]) & (nxy[:, 1] <= b[3])]
        inside = {int(nd) for nd in near if zone.contains(Point(xy[nd]))}
        if not inside:
            continue
        res, outs = [], []
        for k in {next(i for i, c in enumerate(comps) if nd in c) for nd in inside}:
            if k not in sy.index:
                continue
            o_pt = Point(sy.loc[k, "Outfall_x"], sy.loc[k, "Outfall_y"])
            if o_pt.within(poly.buffer(40.0)):
                continue                      # the system already discharges into the basin
            n_out = min(comps[k], key=lambda nd: np.hypot(xy[nd][0] - o_pt.x, xy[nd][1] - o_pt.y))
            mine = lk[lk.System == k]
            if not len(mine):
                continue
            n_in_links = 0
            for _, L in mine.iterrows():
                pt = Point(L.x, L.y)
                cand = tree.query(pt.buffer(15.0))
                if not len(cand):
                    continue
                j = min(cand, key=lambda c: P.geometry[c].distance(pt))
                u, v = ends_of_pipe[j]
                n_in = u if np.hypot(xy[u][0] - pt.x, xy[u][1] - pt.y) <= np.hypot(xy[v][0] - pt.x, xy[v][1] - pt.y) else v
                if n_in in inside:
                    continue                  # the pond's own outlet structure
                path = nx.shortest_path(G, n_in, n_out)
                if inside.intersection(path) and int(L.ic) != outlet[bid]:
                    res.append((int(L.ic), int(outlet[bid]), "pipe_in"))
                    n_in_links += 1
            outs.append((n_in_links == 0, o_pt.distance(poly), int(mine.oc.iloc[0])))
        # one outlet pipe per basin: the system carrying re-routed inlets, else the
        # one whose outfall is nearest (a short outlet pipe, not a trunk passing by)
        if outs:
            res.append((int(outlet[bid]), min(outs)[2], "pipe_out"))
        if res:
            out[bid] = res
    return out


def apply_checked(down, links):
    """Set down[ic] = oc for each link unless it would close a cycle; returns kept links."""
    kept = []
    for L in links:
        ic, oc = L[0], L[1]
        if ic == oc or hydro.on_downstream_path(oc, ic, down, down.size):
            continue
        down[ic] = oc
        kept.append(L)
    return kept


def main():
    RAT.mkdir(parents=True, exist_ok=True)
    d = gpd.read_file(STORM, layer="detention")
    d = merge_duplicates(d[d.InWatershed].copy())
    lakes = gpd.read_file(HMSG, layer="Lakes")
    lake_u = lakes.geometry.union_all()
    sb = gpd.read_file(HMSG, layer="Subbasins")[["Subbasin", "geometry"]]
    ab = pd.read_csv(ASBUILT) if ASBUILT.exists() else pd.DataFrame(columns=AB_COLS)

    acc = rasterio.open(ACC)
    A = acc.read(1)
    tr10 = acc.transform
    ac10 = tr10.a ** 2 / 43560.0
    dem = rasterio.open(DEM1M)
    with rasterio.open(FDIR) as s_:
        F = s_.read(1)
    down, _step, order, _acc = sewer.flow_graph(F, tr10.a, use_sewer=True)
    nc10 = A.shape[1]
    capture = {}

    d["Area_ac"] = d.area / 43560.0
    d = d.sort_values("Area_ac", ascending=False).reset_index(drop=True)
    # pipe systems passing through basins (see passthrough_links); applied for every
    # basin when computing drainage areas, written for the modelled ones only
    polys, outl = {}, {}
    for k, r in d.iterrows():
        bid = f"DET{k + 1:03d}"
        m10 = rasterize([(r.geometry, 1)], out_shape=A.shape, transform=tr10, all_touched=True).astype(bool)
        if not m10.any():
            m10 = rasterize([(r.geometry.buffer(10), 1)], out_shape=A.shape, transform=tr10, all_touched=True).astype(bool)
        ix = np.flatnonzero(m10.ravel())
        polys[bid], outl[bid] = r.geometry, int(ix[np.argmax(A.ravel()[ix])])
    pthru = passthrough_links(polys, outl)
    down_r = down.copy()
    for bid in pthru:
        apply_checked(down_r, pthru[bid])
    order_r = hydro.topo_order(down_r)
    if order_r.size != down_r.size:
        down_r, order_r = down, order
    print(f"pipe systems through basins: {sum(len(v) for v in pthru.values())} links at {len(pthru)} basins")
    rows = []
    for k, r in d.iterrows():
        bid = f"DET{k + 1:03d}"
        poly = r.geometry
        # ---- outlet & drainage area (10 ft sewer graph)
        # outlet inside the footprint only: a basin beside a creek must not take the creek
        m10 = rasterize([(poly, 1)], out_shape=A.shape, transform=tr10, all_touched=True).astype(bool)
        if not m10.any():
            m10 = rasterize([(poly.buffer(10), 1)], out_shape=A.shape, transform=tr10, all_touched=True).astype(bool)
        idx = np.flatnonzero(m10.ravel())
        oc = int(idx[np.argmax(A.ravel()[idx])])
        ox, oy = tr10 * ((oc % A.shape[1]) + 0.5, (oc // A.shape[1]) + 0.5)
        # drainage area = everything that enters the footprint: on a flat pool
        # D8 can leave by a second cell, but in reality all of it passes the outlet
        da = float(hydro.drains_into(down_r, order_r, m10.ravel()).sum() * ac10)
        capture[bid] = (idx, oc)
        # ---- 1 m terrain window
        xmin, ymin, xmax, ymax = poly.buffer(STORAGE_REACH_FT + 20).bounds
        win = rasterio.windows.from_bounds(xmin, ymin, xmax, ymax, transform=dem.transform).round_offsets().round_lengths()
        Z = dem.read(1, window=win).astype(float)
        t1 = dem.window_transform(win)
        a1 = t1.a ** 2
        inside = rasterize([(poly, 1)], out_shape=Z.shape, transform=t1, all_touched=True).astype(bool)
        reach = rasterize([(poly.buffer(STORAGE_REACH_FT), 1)], out_shape=Z.shape, transform=t1).astype(bool)
        zi = Z[inside & (Z > -9000)]
        if zi.size < 4:
            continue
        vals, cnt = np.unique(np.round(zi, 1), return_counts=True)
        mode = float(vals[np.argmax(cnt)])
        flat_frac = float(np.mean(np.abs(zi - mode) <= 0.1))
        wet = flat_frac >= 0.25
        bottom = mode if wet else float(np.percentile(zi, 2))
        zrs = []
        for rf in RINGS_FT:
            rb = poly.buffer(rf)
            ring = rb.exterior if rb.geom_type == "Polygon" else rb.boundary
            rp = [ring.interpolate(s_) for s_ in np.arange(0, ring.length, t1.a)]
            zr = np.array([v[0] for v in dem.sample([(p.x, p.y) for p in rp])], float)
            zrs.append(np.where(zr > -9000, zr, np.nan))
        rim = float(max(np.nanmin(z) for z in zrs))
        if not np.isfinite(rim) or rim <= bottom + 0.3:
            rim = bottom + 0.3
        depth = rim - bottom
        E = np.round(np.arange(bottom, rim + ABOVE_RIM_FT + 1e-6, DE), 3)
        sto = []
        seed = inside & (Z < bottom + 0.05) if not wet else inside & (np.abs(Z - mode) <= 0.1)
        if not seed.any():
            seed = inside
        for e in E:
            wetm = ((Z < e) & reach) | seed
            lab, _ = ndimage.label(wetm, structure=np.ones((3, 3)))
            ids = np.unique(lab[seed])
            comp = np.isin(lab, ids[ids > 0])
            sto.append(float(np.clip(e - np.maximum(Z[comp], bottom), 0, None).sum() * a1 / 43560.0))
        sto = np.array(sto)
        lidar_bottom = bottom
        mine = ab[ab.Basin == bid] if len(ab) else ab
        pool_rows = mine[mine.Kind == "pool"] if len(mine) else mine
        if len(pool_rows):
            # design normal pool: below a lidar water surface, add the pool's own storage
            pv = float(pool_rows.Invert_ft.iloc[0])
            if pv < bottom:
                a_pool = float(seed.sum() * a1 / 43560.0)
                ext = np.round(np.arange(pv, bottom - 1e-6, DE), 3)
                sto = np.concatenate([a_pool * (ext - pv), sto + a_pool * (bottom - pv)])
                E = np.concatenate([ext, E])
            else:
                sto = np.clip(sto - np.interp(pv, E, sto), 0, None)
                keep = E >= pv
                E, sto = np.concatenate([[pv], E[keep & (E > pv)]]), np.concatenate([[0.0], sto[keep & (E > pv)]])
            bottom = pv
            depth = rim - bottom
        s_rim = float(np.interp(rim, E, sto))
        # ---- outflow
        q_rim = RELEASE_CFS_PER_AC * da
        # rim overtopping: every ring must pass the flow, the tightest controls;
        # nothing drains below the (lidar) pool / basin bottom
        q_ring = np.min([[np.nansum(C_WEIR * t1.a * np.clip(e - np.maximum(z, lidar_bottom), 0, None) ** 1.5)
                          for e in E] for z in zrs], axis=0)
        shallow_pond = wet and depth < 1.0
        if len(mine):
            q_out = asbuilt_outflow(mine, E)
            source = "as-built: " + "; ".join(sorted(set(mine.Source.astype(str))))
        elif shallow_pond:
            q_out = np.zeros_like(E)          # spills over its natural outlet (rim weir only)
            source = "terrain: wet pond spilling over its rim (no structure assumed)"
        else:
            q_out = np.minimum(orifice(q_rim, depth, E - bottom), q_rim)
            source = "assumed: APWA 5600 3.0 cfs/ac at spill"
        q = q_out + q_ring
        hit = poly.representative_point()
        sbn = sb[sb.contains(hit)].Subbasin
        overlaps_lake = poly.intersection(lake_u).area > 0.3 * poly.area
        big_pond = wet and r.Area_ac >= 1.0
        negligible = (not wet) and s_rim < da * MIN_STORAGE_IN / 12.0   # e.g. a small polygon on a big creek
        modelled = (da >= 2.0 and not overlaps_lake and (r.Type not in NOT_MODELLED_TYPES) and not negligible
                    and ((s_rim >= 0.1 and depth >= 1.0) or big_pond))
        why = [] if modelled else [w for w, c in (("DA<2ac", da < 2.0), ("storage<0.1acft", s_rim < 0.1 and not big_pond),
                                                  ("depth<1ft", depth < 1.0 and not big_pond), ("lake LK1/LK2", overlaps_lake),
                                                  ("storage<0.05in over DA", negligible),
                                                  (f"type {r.Type}", r.Type in NOT_MODELLED_TYPES)) if c]
        rows.append(dict(Basin=bid, City_OBJECTIDs=r.City_OBJECTIDs, Type=r.Type, Area_ac=r.Area_ac,
                         Subbasin=sbn.iloc[0] if len(sbn) else "", DA_ac=da, Wet=wet, Lidar_pool_or_bottom_ft=lidar_bottom,
                         Pool_or_Bottom_ft=bottom,
                         Spill_ft=rim, Depth_ft=depth, Storage_at_spill_acft=s_rim, Q_at_spill_cfs=float(np.interp(rim, E, q)),
                         Outlet=source, Modelled=modelled, Not_modelled_because=";".join(why),
                         Outlet_x=ox, Outlet_y=oy, outlet_cell=oc, geometry=poly))
        pd.DataFrame(dict(Elev_ft=E, Storage_acft=sto, Outflow_cfs=q)).round(4).to_csv(RAT / f"{bid}.csv", index=False)
    g = gpd.GeoDataFrame(rows, crs=CRS)
    # capture links for modelled basins: footprint cells whose D8 flow leaves the
    # footprint go to the basin outlet (read by sewer.flow_graph in scripts 04/05)
    down2 = down.copy()
    lk = []
    # pipe links for every basin (keeps the drainage areas above consistent); for an
    # unmodelled basin they only pass its outlet cell on the way to the same outfall
    for bid in g.Basin:
        lk += [(bid, ic, oc, kind) for ic, oc, kind in apply_checked(down2, pthru.get(bid, []))]
    inside = np.zeros(down.size, bool)
    for bid in g.Basin[g.Modelled]:
        idx, oc = capture[bid]
        inside[:] = False
        inside[idx] = True
        for j in idx:
            d_ = down2[j]
            if j == oc or (d_ >= 0 and inside[d_]):
                continue
            if hydro.on_downstream_path(oc, int(j), down2, down.size):
                continue            # would close a cycle through the outlet
            down2[j] = oc
            lk.append((bid, int(j), int(oc), "footprint"))
    lk = pd.DataFrame(lk, columns=["Basin", "ic", "oc", "Kind"])
    lk.to_csv(sewer.DET_LINKS_CSV, index=False)
    print(f"detention links: {lk.Kind.value_counts().to_dict()} -> {sewer.DET_LINKS_CSV.relative_to(ROOT)}")
    for bid, grp in lk[lk.Kind != "footprint"].groupby("Basin"):
        print(f"   {bid}: {int((grp.Kind == 'pipe_in').sum())} inlets re-routed into the basin, "
              f"outlet pipe link {'yes' if (grp.Kind == 'pipe_out').any() else 'no'}")
    OUT.unlink(missing_ok=True)
    g.to_file(OUT, layer="basins")
    g.drop(columns="geometry").round(3).to_csv(PAR / "detention_basins.csv", index=False)
    if not ASBUILT.exists():
        pd.DataFrame(columns=AB_COLS).to_csv(ASBUILT, index=False)
    mod = g[g.Modelled]
    print(f"{len(g)} basins after merging duplicates; {len(mod)} modelled "
          f"(wet {int(mod.Wet.sum())}, dry {int((~mod.Wet).sum())})")
    print(f"modelled storage at spill: {mod.Storage_at_spill_acft.sum():.1f} ac-ft; DA range {mod.DA_ac.min():.0f}-{mod.DA_ac.max():.0f} ac")
    print(g.Not_modelled_because[~g.Modelled].str.split(";").explode().value_counts().to_string())


if __name__ == "__main__":
    main()
