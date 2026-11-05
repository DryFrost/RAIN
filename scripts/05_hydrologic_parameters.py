"""Compute HMS subbasin and reach parameters.

Subbasins
  * Loss (SCS Curve Number) reproduces the FEMA RoG infiltration layer
    (Land Classification/Infiltration.hdf = LandCover x Soils CN table) at the
    native 1 m (3.28 ft) resolution.  FEMA's CN-98 classes (buildings, roads,
    open water, channels, no-data) are carried as Percent Impervious; the
    remaining classes give an area-weighted pervious CN.  Composite CN is also
    reported.
  * Transform (SCS UH): lag = 0.6 Tc, Tc by TR-55 segments along the longest
    flow path (sheet <=100 ft, shallow concentrated, channel), on the same
    terrain + storm-sewer flow graph as script 04; storm-sewer steps of the
    path (inlet -> outfall) travel at 5 ft/s.  The NRCS lag
    equation is reported as a check.  Minimum Tc = 5 min.
Reaches (Muskingum-Cunge, trapezoid)
  * length = D8 path, slope = regression of burned-DEM elevation vs distance
  * trapezoid (bottom width, side slope) least-squares fit to flow area vs
    depth from 1 m terrain cross sections (3 per reach)
  * Manning's n = Horton composite of the FEMA Manning's n raster over the
    wetted perimeter at the reference depth

Outputs: GIS/HMS_Raymore.gpkg (Subbasins/Reaches attributes updated,
LongestFlowPaths, ReachXS layers) and HMS/parameters/*.csv
"""
from pathlib import Path
import sys
import h5py
import numpy as np
import pandas as pd
import geopandas as gpd
import rasterio
from rasterio.windows import from_bounds
from rasterio.warp import reproject, Resampling
from shapely.geometry import LineString, Point

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hydro  # noqa: E402
import sewer  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
RAS = ROOT / "Resources/2D_Raymore"
LCD = RAS / "Land Classification"
GPKG = ROOT / "GIS/HMS_Raymore.gpkg"
R10 = ROOT / "GIS/rasters"
PAR = ROOT / "HMS/parameters"

P2_24 = 3.66          # in, NOAA Atlas 14 2-yr 24-hr (FEMA Precip.gdb, Basinsfin.P2yr24)
SHEET_MAX = 100.0     # ft (TR-55, 2009 revision)
CH_START_AC = 30.0    # channel flow assumed once drainage area exceeds this
TC_MIN_HR = 5.0 / 60.0
N_CHANNEL_TC = 0.045  # Manning's n for TR-55 channel segments
PIPE_V_FPS = 5.0      # storm-sewer travel velocity for sewer-link steps of the flow path
LC_IMPERV = {0, 1, 2, 3, 4, 6, 11}       # FEMA classes with CN 98 for every soil
CHANNEL_LC = {1, 2, 3}
PAVED_LC = {4, 6}
# TR-55 Table 3-1 sheet-flow n by FEMA land-cover id
SHEET_N = {0: 0.011, 1: 0.011, 2: 0.011, 3: 0.011, 4: 0.011, 6: 0.011, 11: 0.011,
           7: 0.24, 8: 0.24, 9: 0.05, 10: 0.40, 25: 0.17}


def dec(x):
    return x.decode().strip() if isinstance(x, bytes) else str(x)


def cn_lookup():
    lc = h5py.File(LCD / "LandCover.hdf", "r")["Raster Map"][:]
    so = h5py.File(LCD / "Soils.hdf", "r")["Raster Map"][:]
    var = h5py.File(LCD / "Infiltration.hdf", "r")["Variables"][:]
    lc_name = {int(r["ID"]): dec(r["Name"]) for r in lc}
    so_name = {int(r["ID"]): dec(r["Name"]) for r in so}
    cn = {dec(r["Name"]): float(r["Curve Number"]) for r in var}
    table = np.full((max(lc_name) + 1, max(so_name) + 1), np.nan)
    for li, ln in lc_name.items():
        for si, sn in so_name.items():
            key = ln if (ln == "NoData" and sn == "NoData") else f"{ln} : {sn}"
            table[li, si] = cn.get(key, cn.get(ln, 98.0))
    return table, lc_name, so_name


def mannings_lookup():
    rm = h5py.File(LCD / "ManningsN.hdf", "r")["Variables"][:]
    vals = np.array([float(r["ManningsN"]) for r in rm])
    vals[vals < 0] = np.nan
    return vals  # index = raster id


def main():
    PAR.mkdir(parents=True, exist_ok=True)
    S = gpd.read_file(GPKG, layer="Subbasins")
    R = gpd.read_file(GPKG, layer="Reaches")
    J = gpd.read_file(GPKG, layer="Junctions")
    W = gpd.read_file(GPKG, layer="Watershed")

    # ---------------- 10 ft grids
    with rasterio.open(R10 / "subbasins_10ft.tif") as s:
        lab10 = s.read(1).astype(np.int64)
        tr10 = s.transform
        crs = s.crs
    Z10 = rasterio.open(R10 / "dem_burn_10ft.tif").read(1)
    F10 = rasterio.open(R10 / "fdir_10ft.tif").read(1).astype(np.int64)
    nr, nc = lab10.shape
    cs10 = tr10.a
    ac10 = cs10 ** 2 / 43560.0
    # terrain D8 + storm-sewer inlet links (scripts/02b) -- same graph as script 04
    down, step, order, A10 = sewer.flow_graph(F10, cs10, use_sewer=True)
    up_ptr, up_idx = hydro.upstream_csr(down)
    labf = lab10.ravel()

    # ---------------- 1 m window over the watershed
    xmin, ymin, xmax, ymax = W.total_bounds
    pad = 60.0
    dem1 = rasterio.open(RAS / "Terrain/FinalTerrain.hydroDEM.tif")
    # snap window to the 3x3 block grid so 10 ft labels repeat exactly
    c0 = int(np.floor(((xmin - pad) - dem1.transform.c) / cs10)) * 3
    r0 = int(np.floor((dem1.transform.f - (ymax + pad)) / cs10)) * 3
    c1 = int(np.ceil(((xmax + pad) - dem1.transform.c) / cs10)) * 3
    r1 = int(np.ceil((dem1.transform.f - (ymin - pad)) / cs10)) * 3
    win = rasterio.windows.Window(c0, r0, c1 - c0, r1 - r0)
    tr1 = dem1.window_transform(win)
    lab1 = np.repeat(np.repeat(lab10[r0 // 3:r1 // 3, c0 // 3:c1 // 3], 3, 0), 3, 1)
    with rasterio.open(LCD / "LandCover.tif") as s:
        LC = s.read(1, window=win, boundless=True, fill_value=0)
    with rasterio.open(LCD / "ManningsN.tif") as s:
        MN = s.read(1, window=win, boundless=True, fill_value=0)
    SO = np.zeros(LC.shape, np.int32)
    with rasterio.open(LCD / "Soils.tif") as s:
        reproject(s.read(1), SO, src_transform=s.transform, src_crs=crs, dst_transform=tr1, dst_crs=crs,
                  resampling=Resampling.nearest)
    DEM1 = dem1.read(1, window=win)
    print("1 m window", LC.shape, "labels", lab1.shape)

    table, lc_name, so_name = cn_lookup()
    nvals = mannings_lookup()
    cn1 = table[LC.clip(0, table.shape[0] - 1), SO.clip(0, table.shape[1] - 1)]
    imperv1 = np.isin(LC, list(LC_IMPERV))
    ac1 = tr1.a ** 2 / 43560.0

    rows = []
    lc_ids = sorted(lc_name)
    so_ids = sorted(so_name)
    for _, s in S.iterrows():
        m = lab1 == s.label
        npx = m.sum()
        lcs = LC[m]
        sos = SO[m]
        cns = cn1[m]
        imp = imperv1[m]
        perv_cn = float(cns[~imp].mean()) if (~imp).any() else 98.0
        row = dict(Subbasin=s.Subbasin, Area_ac=npx * ac1, Area_sqmi=npx * ac1 / 640,
                   PctImperv=100 * imp.mean(), CN_Perv=perv_cn, CN_Composite=float(cns.mean()))
        for i in lc_ids:
            row[f"LC_{lc_name[i]}_pct"] = 100 * np.mean(lcs == i)
        for i in so_ids:
            row[f"HSG_{so_name[i]}_pct"] = 100 * np.mean(sos == i)
        rows.append(row)
    lu = pd.DataFrame(rows).set_index("Subbasin")

    # ---------------- longest flow paths + TR-55
    uplen = hydro.upstream_length_lab(down, step, order, cs10, labf)
    gy, gx = np.gradient(np.where(Z10 > -9000, Z10, np.nan), cs10)
    slope10 = np.hypot(gx, gy).ravel()

    def lc_at(x, y):
        c, r = ~tr1 * (x, y)
        r, c = int(r), int(c)
        if 0 <= r < LC.shape[0] and 0 <= c < LC.shape[1]:
            return int(LC[r, c])
        return 0

    try:
        LK = gpd.read_file(GPKG, layer="Lakes")
    except Exception:
        LK = gpd.GeoDataFrame(columns=["Lake", "Junction", "geometry"], geometry="geometry", crs=crs)
    lake_of_sub = {"SB-" + j[2:]: g for j, g in zip(LK.Junction, LK.geometry)}
    try:   # detention basins: runoff only has to reach the pool, as for the lakes
        DT = gpd.read_file(GPKG, layer="Detention")
        lake_of_sub.update({"SB-" + j[2:]: g for j, g in zip(DT.Junction, DT.geometry)})
    except Exception:
        pass

    lfp_rows, tc_rows = [], []
    for _, s in S.iterrows():
        o = int(s.outlet_cell)
        path = hydro.longest_path_csr(o, up_ptr, up_idx, step, uplen, labf, cs10, 200000)
        if s.Subbasin in lake_of_sub:
            # runoff only has to reach the pool; storage routing handles the lake
            lk = lake_of_sub[s.Subbasin].buffer(10)
            pin = [k for k, p in enumerate(path) if lk.contains(Point(*(tr10 * ((p % nc) + 0.5, (p // nc) + 0.5))))]
            if pin and pin[0] > 2:
                path = path[:pin[0] + 1]
        xy = np.array([tr10 * ((p % nc) + 0.5, (p // nc) + 0.5) for p in path])
        z = Z10.ravel()[path].astype(float)
        dist = np.concatenate([[0.0], np.cumsum([step[p] * cs10 for p in path[:-1]])])
        L = dist[-1]
        lcp = np.array([lc_at(x, y) for x, y in xy])
        da = A10[path] * ac10
        n = len(path)
        is_pipe = np.array([step[p] >= 1.5 for p in path])   # sewer-link step (inlet -> outfall)

        def seg_slope(i0, i1, smin):
            i0, i1 = max(0, i0), min(n - 1, i1)
            if i1 <= i0:
                return smin
            return max((z[i0] - z[i1]) / max(dist[i1] - dist[i0], 1.0), smin)

        # sheet
        i_sh = int(np.searchsorted(dist, min(SHEET_MAX, L)))
        i_sh = max(min(i_sh, n - 1), 1)
        Lsh = dist[i_sh]
        nsh = float(np.mean([SHEET_N.get(v, 0.24) for v in lcp[:i_sh + 1]]))
        ssh = seg_slope(0, i_sh, 0.005)
        t_sh = 0.007 * (nsh * Lsh) ** 0.8 / (P2_24 ** 0.5 * ssh ** 0.4)
        # channel start: DA threshold or sustained FEMA channel land cover
        ch = np.flatnonzero(da >= CH_START_AC)
        i_ch = int(ch[0]) if ch.size else n - 1
        isch = np.isin(lcp, list(CHANNEL_LC)).astype(float)
        if n > 6:
            run = np.convolve(isch, np.ones(6) / 6, mode="same")
            cand = np.flatnonzero((run >= 0.8) & (np.arange(n) > i_sh))
            if cand.size:
                i_ch = min(i_ch, int(cand[0]))
        i_ch = max(i_ch, i_sh)
        # shallow concentrated
        t_sc = t_pipe = L_pipe = 0.0
        for i in range(i_sh, i_ch):
            dx = dist[i + 1] - dist[i]
            if is_pipe[i]:
                t_pipe += dx / PIPE_V_FPS / 3600.0
                L_pipe += dx
                continue
            s_ = seg_slope(i - 5, i + 5, 0.005)
            v = (20.3282 if lcp[i] in PAVED_LC else 16.1345) * np.sqrt(s_)
            t_sc += dx / v / 3600.0
        # channel
        t_chn = 0.0
        for i in range(i_ch, n - 1):
            dx = dist[i + 1] - dist[i]
            if is_pipe[i]:
                t_pipe += dx / PIPE_V_FPS / 3600.0
                L_pipe += dx
                continue
            s_ = seg_slope(i - 10, i + 10, 0.001)
            Rh = float(np.clip(1.0 * (da[i] / 640.0) ** 0.3, 0.4, 4.0))
            v = min(1.49 / N_CHANNEL_TC * Rh ** (2 / 3) * np.sqrt(s_), 12.0)
            t_chn += dx / v / 3600.0
        tc = max(t_sh + t_sc + t_chn + t_pipe, TC_MIN_HR)
        # NRCS lag equation check
        mask = labf == s.label
        Y = float(np.nanmean(slope10[mask])) * 100.0
        cnc = lu.loc[s.Subbasin, "CN_Composite"]
        Sret = 1000.0 / cnc - 10.0
        lag_eq = L ** 0.8 * (Sret + 1) ** 0.7 / (1900.0 * Y ** 0.5)
        tc_rows.append(dict(Subbasin=s.Subbasin, LFP_ft=L, LFP_Slope=(z[0] - z[-1]) / max(L, 1),
                            Sheet_ft=Lsh, Sheet_n=nsh, Sheet_s=ssh, Sheet_min=t_sh * 60,
                            Shallow_ft=dist[i_ch] - Lsh, Shallow_min=t_sc * 60,
                            Channel_ft=L - dist[i_ch] - L_pipe, Channel_min=t_chn * 60,
                            Pipe_ft=L_pipe, Pipe_min=t_pipe * 60,
                            Tc_TR55_min=tc * 60, Lag_TR55_min=0.6 * tc * 60,
                            AvgLandSlope_pct=Y, Lag_NRCSeq_min=lag_eq * 60))
        lfp_rows.append(dict(Subbasin=s.Subbasin, Length_ft=L, geometry=LineString(xy)))
    tc = pd.DataFrame(tc_rows).set_index("Subbasin")

    # ---------------- reaches: slope, trapezoid fit, composite n
    nvals_f = np.nan_to_num(nvals, nan=0.06)

    def section(x, y, ux, uy, half):
        offs = np.arange(-half, half + 1e-6, tr1.a)
        px, py = x - uy * offs, y + ux * offs
        cc, rr = ~tr1 * (px, py)
        rr = np.clip(rr.astype(int), 0, DEM1.shape[0] - 1)
        cc = np.clip(cc.astype(int), 0, DEM1.shape[1] - 1)
        return offs, DEM1[rr, cc].astype(float), MN[rr, cc]

    xs_rows, r_rows = [], []
    for _, r in R.iterrows():
        g = r.geometry
        L = g.length
        up, dn = int(r.up_cell), int(r.dn_cell)
        da_up = A10[up] * ac10 / 640.0
        da_dn = A10[dn] * ac10 / 640.0
        # slope by regression along the D8 path
        pts = np.array(g.coords)
        d = np.concatenate([[0], np.cumsum(np.hypot(*np.diff(pts, axis=0).T))])
        zz = np.array([Z10[int((~tr10 * (x, y))[1]), int((~tr10 * (x, y))[0])] for x, y in pts], float)
        ok = zz > -9000
        slope = -np.polyfit(d[ok], zz[ok], 1)[0] if ok.sum() > 3 else 0.001
        slope = float(max(slope, 0.0005))
        href = float(np.clip(2.5 + 2.0 * da_dn ** 0.35, 3.0, 10.0))
        half = float(np.clip(150 + 150 * da_dn ** 0.5, 150, 700))
        smooth = g.simplify(30)
        fits = []
        for f in (0.25, 0.5, 0.75):
            p = smooth.interpolate(f, normalized=True)
            a = smooth.interpolate(max(f * smooth.length - 40, 0))
            b = smooth.interpolate(min(f * smooth.length + 40, smooth.length))
            ux, uy = b.x - a.x, b.y - a.y
            nrm = np.hypot(ux, uy) or 1.0
            ux, uy = ux / nrm, uy / nrm
            offs, zs, ns = section(p.x, p.y, ux, uy, half)
            ctr = np.abs(offs) <= 40
            it = int(np.flatnonzero(ctr)[np.argmin(zs[ctr])])
            zt = zs[it]
            hs = np.arange(0.5, href + 1e-6, 0.5)
            areas, tws = [], []
            for h in hs:
                wet = zs < zt + h
                # connected wetted run containing the thalweg
                lo = it
                while lo > 0 and wet[lo - 1]:
                    lo -= 1
                hi = it
                while hi < len(zs) - 1 and wet[hi + 1]:
                    hi += 1
                dep = (zt + h - zs[lo:hi + 1]).clip(0)
                areas.append(dep.sum() * tr1.a)
                tws.append((hi - lo + 1) * tr1.a)
            hs, areas = np.array(hs), np.array(areas)
            # A = b h + z h^2  (least squares, constrained)
            M = np.vstack([hs, hs ** 2]).T
            bz, *_ = np.linalg.lstsq(M, areas, rcond=None)
            bw, zs_ = float(np.clip(bz[0], 2.0, 400.0)), float(np.clip(bz[1], 0.5, 60.0))
            # conveyance-weighted n at href (strip method): the single n that gives the
            # same total conveyance as the FEMA n raster across the wetted section
            wet = zs < zt + href
            lo = it
            while lo > 0 and wet[lo - 1]:
                lo -= 1
            hi = it
            while hi < len(zs) - 1 and wet[hi + 1]:
                hi += 1
            dep = (zt + href - zs[lo:hi + 1]).clip(0)
            nn = nvals_f[np.clip(ns[lo:hi + 1], 0, len(nvals_f) - 1)]
            nn = np.where((nn > 0) & (nn < 0.3), nn, 0.3)   # buildings/obstructions capped
            k53 = dep ** (5.0 / 3.0)
            ncomp = float(k53.sum() / (k53 / nn).sum()) if k53.sum() > 0 else 0.05
            fits.append((bw, zs_, ncomp, tws[-1], areas[-1]))
            xs_rows.append(dict(Reach=r.Reach, frac=f, BottomWidth=bw, SideSlope=zs_, n=ncomp,
                                TopWidth_href=tws[-1], Area_href=areas[-1], href=href,
                                geometry=LineString([(p.x - uy * offs[0], p.y + ux * offs[0]),
                                                     (p.x - uy * offs[-1], p.y + ux * offs[-1])])))
        fits = np.array(fits)
        r_rows.append(dict(Reach=r.Reach, Length_ft=L, Slope=slope, DA_up_sqmi=da_up, DA_dn_sqmi=da_dn,
                           BottomWidth_ft=float(np.median(fits[:, 0])), SideSlope_HtoV=float(np.median(fits[:, 1])),
                           Mannings_n=float(np.clip(np.median(fits[:, 2]), 0.03, 0.12)),
                           TopWidth_href_ft=float(np.median(fits[:, 3])), Href_ft=href))
    rp = pd.DataFrame(r_rows).set_index("Reach")

    # ---------------- write
    sub = lu.join(tc)
    sub.round(4).to_csv(PAR / "subbasin_parameters.csv")
    rp.round(5).to_csv(PAR / "reach_parameters.csv")
    gpd.GeoDataFrame(lfp_rows, crs=crs).to_file(GPKG, layer="LongestFlowPaths")
    gpd.GeoDataFrame(xs_rows, crs=crs).to_file(GPKG, layer="ReachXS")
    S2 = S.merge(sub[["PctImperv", "CN_Perv", "CN_Composite", "Tc_TR55_min", "Lag_TR55_min", "Lag_NRCSeq_min"]],
                 left_on="Subbasin", right_index=True)
    S2.to_file(GPKG, layer="Subbasins")
    R2 = R.merge(rp[["Slope", "BottomWidth_ft", "SideSlope_HtoV", "Mannings_n"]], left_on="Reach", right_index=True)
    R2.to_file(GPKG, layer="Reaches")
    pd.set_option("display.width", 200)
    print(sub[["Area_ac", "PctImperv", "CN_Perv", "CN_Composite", "LFP_ft", "Tc_TR55_min", "Lag_TR55_min",
               "Lag_NRCSeq_min"]].round(1).describe().to_string())
    print(rp.round(4).describe().to_string())


if __name__ == "__main__":
    main()
