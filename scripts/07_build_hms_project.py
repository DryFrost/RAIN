"""Build the HEC-HMS 4.14 project for East Creek Trib 12 at FEMA bridge
29037ECT030 (Raymore, Cass County, MO) and run the Python QA/QC engine.

Project: HMS/Raymore_Trib12/
  Basin      Existing (FEMA-consistent)   62 subbasins, 2 lakes
  Met        FEMA_<freq>    FEMA RoG hyetographs as-is (Atlas 14 x 0.782 ARF)
             Point_<freq>   same hyetographs scaled to Atlas 14 point depth
  Control    48hr_1min      01Jan2030 00:00 - 03Jan2030 00:00, 1 min
  Runs       one per met model (12)

Index flows for Muskingum-Cunge reaches = 0.5 x the QA engine's 100-yr (FEMA)
peak inflow, as the HMS Technical Reference recommends (pass 2 of 2).

Also writes HMS/QAQC/*.csv (engine peaks, comparison with FEMA RoG).
"""
from pathlib import Path
import sys
import json
import datetime as dt
import numpy as np
import pandas as pd
import geopandas as gpd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hms_check as hc  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
GPKG = ROOT / "GIS/HMS_Raymore.gpkg"
PAR = ROOT / "HMS/parameters"
PRJ_NAME = "Raymore_Trib12"
PRJ = ROOT / "HMS" / PRJ_NAME
QA = ROOT / "HMS/QAQC"
FEMA_DSS = ROOT / "Resources/2D_Raymore/Precip Data/78% AR/Rainfall.dss"
FEMA_PEAKS = ROOT / "FEMA_Results/FEMA_RefLine_Peaks.csv"
FEMA_STRUCT = ROOT / "FEMA_Results/FEMA_Structure_Peaks.csv"
CRS_WKT = (ROOT / "Resources/2D_Raymore/Projection/Projection.prj").read_text().strip()
BASIN = "Existing FEMA-Consistent"
BASIN_FILE = "Existing_FEMA_Consistent.basin"
CONTROL = "48hr_1min"
DT_MIN = 1
START = dt.datetime(2030, 1, 1, 0, 0)
END = dt.datetime(2030, 1, 3, 0, 0)
# (label, FEMA DSS B-part, Atlas 14 point 24-hr depth from FEMA Precip.gdb Basinsfin)
STORMS = [("10yr", "10YR", 5.55), ("25yr", "25YR", 6.83), ("50yr", "50YR", 7.88),
          ("100yr", "100YR", 8.97), ("100yr_plus", "100PLUS", 10.31), ("500yr", "500YR", 11.75)]
NOW = dt.datetime.now()
DATE = f"{NOW.day} {NOW.strftime('%B %Y')}"
TIME = NOW.strftime("%H:%M:%S")
I5 = "     "


# ----------------------------------------------------------------- precip
def read_fema_storms():
    from hecdss import HecDss
    d = HecDss(str(FEMA_DSS))
    out = {}
    for lab, b, pt in STORMS:
        ts = d.get(f"/Raymore/{b}/PRECIP-INC//6Minute//")
        t = pd.to_datetime(ts.times)
        v = np.array(ts.values, float)
        out[lab] = (t, v, pt)
    d.close()
    return out


def to_model_steps(t, v):
    """6-min increments (value at t = depth over (t-6min, t]) -> 1-min
    increments on the control window, uniform within each 6-min block
    (HMS interpolates cumulative depth linearly)."""
    tm = pd.date_range(START, END, freq=f"{DT_MIN}min")
    hrs = lambda x: np.array([(pd.Timestamp(v) - pd.Timestamp(START)).total_seconds() / 3600.0 for v in x])
    th = hrs(t)
    cum_t = np.concatenate([[th[0] - 0.1], th])
    cum_v = np.concatenate([[0.0], np.cumsum(v)])
    c = np.interp(hrs(tm), cum_t, cum_v)
    return tm, np.diff(np.concatenate([[0.0], c]))


# ----------------------------------------------------------------- topology
def build_model():
    S = gpd.read_file(GPKG, layer="Subbasins")
    J = gpd.read_file(GPKG, layer="Junctions")
    R = gpd.read_file(GPKG, layer="Reaches")
    LK = gpd.read_file(GPKG, layer="Lakes")
    sp = pd.read_csv(PAR / "subbasin_parameters.csv", index_col=0)
    rp = pd.read_csv(PAR / "reach_parameters.csv", index_col=0)
    ratings = json.loads((PAR / "lake_ratings.json").read_text())

    lake_j = {f"J-{n}": n for n in LK.Lake}
    kind = dict(zip(J.Junction, J.PointKind))
    jxy = {r.Junction: (r.geometry.x, r.geometry.y) for _, r in J.iterrows()}
    reach_from = {r.FromJ: r for _, r in R.iterrows()}

    el = {}  # name -> dict(type=..., downstream=..., ...)
    for _, l in LK.iterrows():
        c = l.geometry.representative_point()
        pool = f"J-{l.Lake}-Pool"
        el[pool] = dict(type="Junction", downstream=f"L-{l.Lake}", xy=(c.x, c.y),
                        desc=f"{l.Lake} pool inflow point ({l.Area_ac:.1f} ac lake, normal pool {l.WSE_ft:.2f} ft)")
        el[f"L-{l.Lake}"] = dict(type="Lake", downstream=f"J-{l.Lake}", xy=jxy[f"J-{l.Lake}"], from_xy=(c.x, c.y),
                                 lake=l.Lake, table=f"{l.Lake} Storage-Outflow",
                                 desc=f"Level-pool (Modified Puls) routing through {l.Lake}; terrain-derived "
                                      f"storage-outflow, sill {ratings[l.Lake]['crest']:.2f} ft")
    for _, j in J.iterrows():
        name = j.Junction
        k = j.PointKind
        desc = {"Outlet": f"Watershed outlet - FEMA bridge {j.FEMA_Struct}",
                "Structure": f"FEMA crossing {j.FEMA_Struct}",
                "RefLine": f"FEMA reference line {j.FEMA_RefLine}",
                "Confluence": "Stream confluence", "Split": "Main-stem break",
                "Lake": "Lake outlet (spill sill)", "LakeInflow": "Tributary inflow to lake"}[k]
        if j.FEMA_RefLine and k != "RefLine":
            desc += f"; FEMA reference line {j.FEMA_RefLine}"
        if k == "LakeInflow":
            ds = f"J-{name[2:].split('-IN')[0]}-Pool"
        elif name in reach_from:
            ds = reach_from[name].Reach
        else:
            ds = None
        el[name] = dict(type="Junction", downstream=ds, xy=jxy[name], desc=desc, kind=k,
                        fema_struct=j.FEMA_Struct, fema_ref=j.FEMA_RefLine, da=j.DA_sqmi)
    for _, r in R.iterrows():
        if kind.get(r.FromJ) == "LakeInflow":
            continue
        to = r.ToJ
        if to in lake_j:             # reach would cross the pool -> enter at the pool
            to = f"J-{lake_j[to]}-Pool"
        p = rp.loc[r.Reach]
        el[r.Reach] = dict(type="Reach", downstream=to, xy=jxy[r.ToJ], from_xy=jxy[r.FromJ],
                           L=float(p.Length_ft), s=float(p.Slope), n=float(p.Mannings_n),
                           b=float(p.BottomWidth_ft), z=float(p.SideSlope_HtoV), qi=None,
                           desc=f"{r.FromJ} to {r.ToJ}")
    for _, s in S.iterrows():
        p = sp.loc[s.Subbasin]
        ds = s.Junction
        if ds in lake_j:
            ds = f"J-{lake_j[ds]}-Pool"
        c = s.geometry.representative_point()
        el[s.Subbasin] = dict(type="Subbasin", downstream=ds, xy=(c.x, c.y), area=float(p.Area_sqmi),
                              cn=float(p.CN_Perv), imp=float(p.PctImperv), lag=float(p.Lag_TR55_min),
                              desc=f"{p.Area_ac:.1f} ac; composite CN {p.CN_Composite:.1f}; Tc {p.Tc_TR55_min:.1f} min")
    # sanity: every downstream exists
    for k_, e in el.items():
        assert e["downstream"] is None or e["downstream"] in el, (k_, e["downstream"])
    return el, ratings


def topo(el):
    ups = {k: [] for k in el}
    for k, e in el.items():
        if e["downstream"]:
            ups[e["downstream"]].append(k)
    order, seen = [], set()

    def visit(k):
        if k in seen:
            return
        for u in ups[k]:
            visit(u)
        seen.add(k)
        order.append(k)
    sys.setrecursionlimit(10000)
    for k in el:
        visit(k)
    return order, ups


def run_engine(el, ups, order, p_inc, lake_tables):
    Q = {}
    for k in order:
        e = el[k]
        if e["type"] == "Subbasin":
            Q[k] = hc.subbasin_hydrograph(p_inc, e["area"], e["cn"], e["imp"], e["lag"], DT_MIN)
        else:
            inflow = sum((Q[u] for u in ups[k]), np.zeros(len(p_inc)))
            if e["type"] == "Junction":
                Q[k] = inflow
            elif e["type"] == "Reach":
                e["_inflow_peak"] = float(inflow.max())
                qi = e["qi"] or max(10.0, 0.5 * inflow.max())
                Q[k], e["_mc"] = hc.muskingum_cunge(inflow, e["L"], e["s"], e["n"], e["b"], e["z"], qi, DT_MIN)
            elif e["type"] == "Lake":
                tab = lake_tables[e["lake"]]
                Q[k], e["_stor"] = hc.modified_puls(inflow, tab[:, 0], tab[:, 1], DT_MIN)
                e["_inflow_peak"] = float(inflow.max())
    return Q


def lake_table(name):
    df = pd.read_csv(PAR / f"lake_{name}_rating.csv")
    s, q = df.Storage_acft.values, df.Outflow_cfs.values
    # HMS needs strictly increasing outflow: keep the first zero-flow row, then
    # give dead storage up to the sill a tiny flow so the table stays monotonic
    keep = [0] + [i for i in range(1, len(q)) if q[i] > q[:i].max() + 1e-9]
    s, q = s[keep], q[keep]
    q = np.maximum.accumulate(q + np.arange(len(q)) * 1e-3)
    return np.column_stack([s, q])


# ----------------------------------------------------------------- writers
def w_header(f, kind, name, desc=None):
    f.write(f"{kind}: {name}\n")
    if desc:
        f.write(f"{I5}Description: {desc}\n")
    f.write(f"{I5}Last Modified Date: {DATE}\n{I5}Last Modified Time: {TIME}\n")


def write_basin(el, order):
    xs = [e["xy"][0] for e in el.values()]
    ys = [e["xy"][1] for e in el.values()]
    with open(PRJ / BASIN_FILE, "w", newline="\r\n") as f:
        w_header(f, "Basin", BASIN, "East Creek Trib 12 to FEMA bridge 29037ECT030. Loss/precip consistent with "
                                    "FEMA preliminary RoG model; no subdivision detention yet.")
        f.write(f"{I5}Version: 4.14\n{I5}Filepath Separator: \\\n{I5}Unit System: English\n"
                f"{I5}Missing Flow To Zero: No\n{I5}Enable Flow Ratio: No\n"
                f"{I5}Compute Local Flow At Junctions: No\n{I5}Unregulated Output Required: No\n\n"
                f"{I5}Enable Sediment Routing: No\nEnd:\n\n")
        for k in order:
            e = el[k]
            t = e["type"]
            if t == "Subbasin":
                w_header(f, "Subbasin", k, e["desc"])
                f.write(f"{I5}Canvas X: {e['xy'][0]:.3f}\n{I5}Canvas Y: {e['xy'][1]:.3f}\n"
                        f"{I5}Label X: 16.0\n{I5}Label Y: 0.0\n{I5}Area: {e['area']:.5f}\n"
                        f"{I5}Downstream: {e['downstream']}\n\n{I5}Discretization: None\n\n"
                        f"{I5}Canopy: None\n{I5}Allow Simultaneous Precip Et: No\n{I5}Plant Uptake Method: None\n\n"
                        f"{I5}Surface: None\n\n"
                        f"{I5}LossRate: SCS\n{I5}Percent Impervious Area: {e['imp']:.2f}\n"
                        f"{I5}Curve Number: {e['cn']:.2f}\n\n"
                        f"{I5}Transform: SCS\n{I5}Lag: {e['lag']:.2f}\n{I5}Unitgraph Type: STANDARD\n\n"
                        f"{I5}Baseflow: None\nEnd:\n\n")
            elif t == "Junction":
                w_header(f, "Junction", k, e["desc"])
                f.write(f"{I5}Canvas X: {e['xy'][0]:.3f}\n{I5}Canvas Y: {e['xy'][1]:.3f}\n"
                        f"{I5}Label X: 16.0\n{I5}Label Y: 0.0\n")
                if e["downstream"]:
                    f.write(f"{I5}Downstream: {e['downstream']}\n")
                else:
                    f.write(f"{I5}Computation Point: Yes\n")
                f.write("End:\n\n")
            elif t == "Reach":
                w_header(f, "Reach", k, e["desc"])
                f.write(f"{I5}Canvas X: {e['xy'][0]:.3f}\n{I5}Canvas Y: {e['xy'][1]:.3f}\n"
                        f"{I5}From Canvas X: {e['from_xy'][0]:.3f}\n{I5}From Canvas Y: {e['from_xy'][1]:.3f}\n"
                        f"{I5}Label X: 16.0\n{I5}Label Y: 0.0\n{I5}Downstream: {e['downstream']}\n\n"
                        f"{I5}Route: Muskingum Cunge\n{I5}Initial Variable: Combined Inflow\n"
                        f"{I5}Channel: Trapezoid\n{I5}Length: {e['L']:.1f}\n{I5}Energy Slope: {e['s']:.5f}\n"
                        f"{I5}Mannings n: {e['n']:.4f}\n{I5}Bottom Width: {e['b']:.2f}\n"
                        f"{I5}Side Slope: {e['z']:.2f}\n{I5}Index Parameter Type: Index Flow\n"
                        f"{I5}Index Flow: {e['qi']:.1f}\n{I5}Space-Time Method: Automatic DX and DT\n"
                        f"{I5}Channel Loss: None\nEnd:\n\n")
            elif t == "Lake":
                w_header(f, "Reach", k, e["desc"])
                f.write(f"{I5}Canvas X: {e['xy'][0]:.3f}\n{I5}Canvas Y: {e['xy'][1]:.3f}\n"
                        f"{I5}From Canvas X: {e['from_xy'][0]:.3f}\n{I5}From Canvas Y: {e['from_xy'][1]:.3f}\n"
                        f"{I5}Label X: 16.0\n{I5}Label Y: 0.0\n{I5}Downstream: {e['downstream']}\n\n"
                        f"{I5}Route: Modified Puls\n{I5}Initial Variable: Combined Inflow\n"
                        f"{I5}Number of Reaches: 1\n{I5}Storage Outflow Table Name: {e['table']}\n"
                        f"{I5}Channel Loss: None\nEnd:\n\n")
        f.write("Basin Layer Properties:\n")
        f.write(f"{I5}Element Layer:\n{I5}     Name: Icons\n{I5}     Layer shown: Yes\n{I5}End Layer:\n")
        for lyr in ["Watershed", "Subbasins", "Streams", "Lakes"]:
            f.write(f"{I5}Map Layer:\n{I5}     Filename: maps\\{lyr}.shp\n{I5}     Layer:0\n"
                    f"{I5}     Display name: {lyr}\n{I5}     Minimum Scale: Undefined\n"
                    f"{I5}     Maximum Scale: Undefined\n{I5}     Layer shown: Yes\n"
                    f"{I5}     Properties Filename: maps\\{lyr}.gdr\n{I5}End Layer:\n")
        f.write("End:\n\n")
        f.write(f"Basin Spatial Properties:\n{I5}Coordinate System: {CRS_WKT}\nEnd:\n\n")
        pad = 1500
        f.write(f"Basin Schematic Properties:\n{I5}Last View N: {max(ys) + pad:.1f}\n{I5}Last View S: {min(ys) - pad:.1f}\n"
                f"{I5}Last View W: {min(xs) - pad:.1f}\n{I5}Last View E: {max(xs) + pad:.1f}\n"
                f"{I5}Maximum View N: {max(ys) + pad:.1f}\n{I5}Maximum View S: {min(ys) - pad:.1f}\n"
                f"{I5}Maximum View W: {min(xs) - pad:.1f}\n{I5}Maximum View E: {max(xs) + pad:.1f}\n"
                f"{I5}Extent Method: Elements\n{I5}Buffer: 0\n{I5}Draw Icons: Yes\n{I5}Draw Icon Labels: Name\n"
                f"{I5}Draw Map Objects: No\n{I5}Draw Gridlines: No\n{I5}Draw Flow Direction: No\n"
                f"{I5}Fix Element Locations: No\n{I5}Fix Hydrologic Order: No\nEnd:\n")


def write_maps():
    mp = PRJ / "maps"
    mp.mkdir(exist_ok=True)
    gdr = """<?xml version="1.0" encoding="UTF-8"?>
<ShapefileProperties>
  <DefaultRGB>-16777216</DefaultRGB>
  <HighlightRGB>-65536</HighlightRGB>
  <DrawUsingDefaultColor>true</DrawUsingDefaultColor>
  <DrawLabels>false</DrawLabels>
  <DrawLines>true</DrawLines>
  <DrawArea>{area}</DrawArea>
  <Alpha>{alpha}</Alpha>
  <BorderColor>{border}</BorderColor>
  <BorderWidth>{bw}</BorderWidth>
  <BorderStyle />
  <FillColor>{fill}</FillColor>
  <FillStyle>Solid</FillStyle>
  <SymbolDrawType>0</SymbolDrawType>
  <PolygonDrawType>0</PolygonDrawType>
  <LabelFont Name="SansSerif.plain" Style="0" Size="12" />
  <DisplayFieldIndex>0</DisplayFieldIndex>
  <ColorContourStartColor>blue</ColorContourStartColor>
  <ColorContourEndColor>red</ColorContourEndColor>
  <NumContourSteps>10</NumContourSteps>
  <LabelRotation>0.0</LabelRotation>
  <LabelPosition>0</LabelPosition>
  <LabelFieldIndex>-1</LabelFieldIndex>
  <PointSize>5</PointSize>
  <SymbolIndex>0</SymbolIndex>
  <UseGradations>false</UseGradations>
  <NumGradations>5</NumGradations>
  <AttributeMap />
</ShapefileProperties>
"""
    style = {"Watershed": ("false", "100.0", "black", 3, "white"), "Subbasins": ("true", "20.0", "gray", 1, "yellow"),
             "Streams": ("false", "100.0", "blue", 2, "blue"), "Lakes": ("true", "60.0", "blue", 1, "cyan")}
    for lyr, (area, alpha, border, bw, fill) in style.items():
        g = gpd.read_file(GPKG, layer=lyr)
        keep = [c for c in g.columns if c in ("Name", "Subbasin", "Lake", "Area_ac", "Area_sqmi", "DA_sqmi", "geometry")]
        g[keep].to_file(mp / f"{lyr}.shp")
        with open(mp / f"{lyr}.gdr", "w", newline="\r\n") as fh:
            fh.write(gdr.format(area=area, alpha=alpha, border=border, bw=bw, fill=fill))


def write_met_gage_control_run(el):
    subs = [k for k, e in el.items() if e["type"] == "Subbasin"]
    mets = []
    for src in ("FEMA", "Point"):
        for lab, b, pt in STORMS:
            mets.append((src, lab, b, pt))
    # gage file
    with open(PRJ / f"{PRJ_NAME}.gage", "w", newline="\r\n") as f:
        f.write(f"Gage Manager: {PRJ_NAME}\n{I5}Gage Manager: {PRJ_NAME}\n{I5}Version: 4.14\n"
                f"{I5}Filepath Separator: \\\nEnd: \n\n")
        for src, lab, b, pt in mets:
            g = f"{src}_{lab}"
            if src == "FEMA":
                fn, path = "data\\FEMA_Rainfall_ARF78.dss", f"/Raymore/{b}/PRECIP-INC//6Minute/FEMA-ARF78/"
                d = f"FEMA RoG hyetograph {b} (Atlas 14 point x 0.782 areal reduction)"
            else:
                fn, path = "data\\Atlas14_PointRainfall.dss", f"/Raymore/{b}/PRECIP-INC//6Minute/ATLAS14-POINT/"
                d = f"FEMA RoG {b} pattern scaled to Atlas 14 point depth {pt:.2f} in (no areal reduction)"
            f.write(f"Gage: {g}\n{I5}Gage: {g}\n{I5}Gage Type: Precipitation\n{I5}Description: {d}\n"
                    f"{I5}Last Modified Date: {DATE}\n{I5}Last Modified Time: {TIME}\n"
                    f"{I5}Reference Height Units: Feet\n{I5}Reference Height: 32808\n"
                    f"{I5}Data Source Type: External DSS\n{I5}Filename: {fn}\n{I5}Pathname: {path}\n"
                    f"{I5}Variant: Variant-1\n       Start Time: 1 January 2030, 00:00\n"
                    f"       End Time: 10 January 2030, 00:00\n{I5}End Variant: Variant-1\nEnd: \n\n")
    met_entries = []
    for src, lab, b, pt in mets:
        mname = f"{src}_{lab}"
        fname = f"{mname}.met"
        desc = ("FEMA RoG precipitation (78% ARF)" if src == "FEMA" else "Atlas 14 point precipitation (no ARF)") + f" - {lab}"
        met_entries.append((mname, fname, desc))
        with open(PRJ / fname, "w", newline="\r\n") as f:
            w_header(f, "Meteorology", mname, desc)
            f.write(f"{I5}Version: 4.14\n{I5}Unit System: English\n{I5}Set Missing Data to Default: Yes\n"
                    f"{I5}Precipitation Method: Specified Average\n{I5}Air Temperature Method: None\n"
                    f"{I5}Atmospheric Pressure Method: None\n{I5}Dew Point Method: None\n{I5}Wind Speed Method: None\n"
                    f"{I5}Shortwave Radiation Method: None\n{I5}Longwave Radiation Method: None\n"
                    f"{I5}Snowmelt Method: None\n{I5}Evapotranspiration Method: No Evapotranspiration\n"
                    f"{I5}Use Basin Model: {BASIN}\nEnd:\n\n")
            f.write(f"Precip Method Parameters: Specified Average\n{I5}Last Modified Date: {DATE}\n"
                    f"{I5}Last Modified Time: {TIME}\n{I5}Allow Depth Override: No\nEnd:\n\n")
            for s in subs:
                f.write(f"Subbasin: {s}\n{I5}Last Modified Date: {DATE}\n{I5}Last Modified Time: {TIME}\n"
                        f"{I5}Gage: {mname}\nEnd:\n\n")
    with open(PRJ / f"{CONTROL}.control", "w", newline="\r\n") as f:
        w_header(f, "Control", CONTROL, "Matches FEMA RoG simulation window; 1-minute step")
        f.write(f"{I5}Version: 4.14\n{I5}Start Date: 1 January 2030\n{I5}Start Time: 00:00\n"
                f"{I5}End Date: 3 January 2030\n{I5}End Time: 00:00\n{I5}Time Interval: {DT_MIN}\nEnd:\n")
    with open(PRJ / f"{PRJ_NAME}.run", "w", newline="\r\n") as f:
        for mname, _, desc in met_entries:
            f.write(f"Run: {mname}\n{I5}Description: {desc}\n{I5}Log File: {mname}.log\n"
                    f"{I5}DSS File: results\\{mname}.dss\n{I5}Is Save Spatial Results: No\n"
                    f"{I5}Last Modified Date: {DATE}\n{I5}Last Modified Time: {TIME}\n"
                    f"{I5}Basin: {BASIN}\n{I5}Precip: {mname}\n{I5}Control: {CONTROL}\n"
                    f"{I5}Save State Type: None\n{I5}Time-Series Output: Save All\n"
                    f"{I5}Time Series Results Manager Start:\n{I5}Time Series Results Manager End:\nEnd:\n\n")
    with open(PRJ / f"{PRJ_NAME}.hms", "w", newline="\r\n") as f:
        f.write(f"Project: {PRJ_NAME}\n{I5}Description: East Creek Trib 12 (Raymore, Cass Co. MO) to FEMA bridge "
                f"29037ECT030 at 38.770832,-94.492901. Built from the FEMA preliminary Rain-on-Grid model.\n"
                f"{I5}Version: 4.14\n{I5}Filepath Separator: \\\n{I5}DSS File Name: {PRJ_NAME}.dss\n"
                f"{I5}Time Zone ID: America/Chicago\nEnd:\n\n")
        for mname, fname, desc in met_entries:
            f.write(f"Precipitation: {mname}\n{I5}Filename: {fname}\n{I5}Description: {desc}\n"
                    f"{I5}Last Modified Date: {DATE}\n{I5}Last Modified Time: {TIME}\nEnd:\n\n")
        f.write(f"Basin: {BASIN}\n{I5}Filename: {BASIN_FILE}\n{I5}Description: Existing conditions, FEMA-consistent "
                f"loss and precipitation\n{I5}Last Modified Date: {DATE}\n{I5}Last Modified Time: {TIME}\nEnd:\n\n")
        f.write(f"Control: {CONTROL}\n{I5}FileName: {CONTROL}.control\n{I5}Description: 48 hr, 1 min\nEnd:\n\n")


def write_pdata_and_dss(el, lake_tables, storms):
    from hecdss import HecDss, PairedData, RegularTimeSeries
    (PRJ / "data").mkdir(exist_ok=True)
    (PRJ / "results").mkdir(exist_ok=True)
    # FEMA's Rainfall.dss stores PRECIP-INC as INST-VAL, which HEC-RAS accepts but
    # HEC-HMS rejects for a precipitation gage (WARNING 10614 / ERROR 20660).  Both
    # files are therefore written fresh as PER-CUM; the FEMA values are unchanged.
    for fname, fpart, scale in (("FEMA_Rainfall_ARF78.dss", "FEMA-ARF78", False),
                                ("Atlas14_PointRainfall.dss", "ATLAS14-POINT", True)):
        pfile = PRJ / "data" / fname
        pfile.unlink(missing_ok=True)
        d = HecDss(str(pfile))
        for lab, b, pt in STORMS:
            t, v, _ = storms[lab]
            ratio = pt / v.sum() if scale else 1.0
            ts = RegularTimeSeries.create((v * ratio).astype(float), units="INCH", data_type="PER-CUM",
                                          interval="6Minute", start_date=t[0].to_pydatetime(),
                                          path=f"/Raymore/{b}/PRECIP-INC//6Minute/{fpart}/")
            d.put(ts)
        d.close()
    pdss = PRJ / f"{PRJ_NAME}.dss"
    pdss.unlink(missing_ok=True)
    d = HecDss(str(pdss))
    with open(PRJ / f"{PRJ_NAME}.pdata", "w", newline="\r\n") as f:
        f.write(f"Paired Data Manager: {PRJ_NAME}\n{I5}Version: 4.14\n{I5}Filepath Separator: \\\nEnd:\n\n")
        for name, tab in lake_tables.items():
            tname = f"{name} Storage-Outflow"
            path = f"//{tname}/STORAGE-FLOW///TABLE/"
            pdo = PairedData.create(tab[:, 0].astype(float), tab[:, 1].reshape(-1, 1).astype(float),
                                    x_units="ACRE-FT", x_type="UNT", y_units="CFS", y_type="UNT", path=path)
            d.put(pdo)
            f.write(f"Table: {tname}\n{I5}Table Type: Storage-Outflow\n"
                    f"{I5}Description: {name} terrain-derived level pool above normal pool (see HMS/parameters)\n"
                    f"{I5}Last Modified Date: {DATE}\n{I5}Last Modified Time: {TIME}\n"
                    f"{I5}X-Units: ACRE-FT\n{I5}Y-Units: CFS\n{I5}Use External DSS File: NO\n"
                    f"{I5}DSS File: {PRJ_NAME}.dss\n{I5}Pathname: {path}\n"
                    f"{I5}Interpolation: Linear Interpolation\nEnd:\n\n")
    d.close()


# ----------------------------------------------------------------- main
def main():
    try:
        from hecdss import HecDss
        HecDss.set_global_debug_level(0)
    except Exception:
        pass
    PRJ.mkdir(parents=True, exist_ok=True)
    QA.mkdir(parents=True, exist_ok=True)
    el, ratings = build_model()
    order, ups = topo(el)
    lake_tables = {e["lake"]: lake_table(e["lake"]) for e in el.values() if e["type"] == "Lake"}
    storms = read_fema_storms()
    steps = {}
    for src in ("FEMA", "Point"):
        for lab, b, pt in STORMS:
            t, v, _ = storms[lab]
            tm, p = to_model_steps(t, v)
            if src == "Point":
                p = p * pt / v.sum()
            steps[f"{src}_{lab}"] = (tm, p)

    # pass 1: index flow = 0.5 x local peak inflow (computed on the fly); pass 2 fixes it
    tm, p100 = steps["FEMA_100yr"]
    run_engine(el, ups, order, p100, lake_tables)
    for e in el.values():
        if e["type"] == "Reach":
            e["qi"] = max(10.0, round(0.5 * e["_inflow_peak"], 0))

    results, mc_rows, lrows = {}, [], []
    for run, (tm, p) in steps.items():
        Q = run_engine(el, ups, order, p, lake_tables)
        results[run] = Q
        for k, e in el.items():
            if e["type"] == "Lake":
                rt = pd.read_csv(PAR / f"lake_{e['lake']}_rating.csv")
                smax = float(e["_stor"].max())
                lrows.append(dict(Run=run, Lake=e["lake"], PeakInflow_cfs=e["_inflow_peak"],
                                  PeakOutflow_cfs=float(Q[k].max()), MaxStorage_acft=smax,
                                  MaxStage_ft=float(np.interp(smax, rt.Storage_acft, rt.Elev_ft))))
    for k, e in el.items():
        if e["type"] == "Reach":
            m = e["_mc"]
            mc_rows.append(dict(Reach=k, IndexFlow_cfs=e["qi"], Celerity_fps=m["celerity"], NormalDepth_ft=m["depth"],
                                Subreaches=m["nsub"], K_min=m["K_s"] / 60, X=m["X"]))
    pd.DataFrame(mc_rows).round(3).to_csv(QA / "engine_muskingum_cunge.csv", index=False)

    # peaks table
    rows = []
    for k in order:
        e = el[k]
        if e["type"] not in ("Junction", "Subbasin"):
            continue
        r = dict(Element=k, Type=e["type"], FEMA_Struct=e.get("fema_struct", ""), FEMA_RefLine=e.get("fema_ref", ""))
        for run, Q in results.items():
            q = Q[k]
            r[f"Q_{run}"] = float(q.max())
            r[f"Tpk_hr_{run}"] = float(np.argmax(q) * DT_MIN / 60.0)
        rows.append(r)
    peaks = pd.DataFrame(rows)
    peaks.round(2).to_csv(QA / "engine_peaks_all_elements.csv", index=False)
    lr = pd.DataFrame(lrows)
    fl = ROOT / "FEMA_Results/FEMA_Lake_MaxWSE.csv"
    if fl.exists():
        fw = pd.read_csv(fl)
        fw["Run"] = "FEMA_" + fw.Event
        lr = lr.merge(fw[["Run", "Lake", "FEMA_MaxWSE_ft"]], on=["Run", "Lake"], how="left")
        lr["Stage_minus_FEMA_ft"] = lr.MaxStage_ft - lr.FEMA_MaxWSE_ft
    lr.round(2).to_csv(QA / "engine_lake_routing.csv", index=False)
    write_basin(el, order)
    write_maps()
    write_met_gage_control_run(el)
    write_pdata_and_dss(el, lake_tables, storms)

    # FEMA comparison at reference lines and structures
    fr = pd.read_csv(FEMA_PEAKS, index_col=0)
    fs = pd.read_csv(FEMA_STRUCT, index_col=0)
    cmp_rows = []
    for k in order:
        e = el[k]
        if e["type"] != "Junction" or not (e.get("fema_ref") or e.get("fema_struct")):
            continue
        r = dict(Junction=k, DA_sqmi=e.get("da"), FEMA_RefLine=e.get("fema_ref", ""), FEMA_Struct=e.get("fema_struct", ""))
        for lab, _, _ in STORMS:
            hq = results[f"FEMA_{lab}"][k].max()
            r[f"HMSchk_{lab}"] = hq
            if e.get("fema_ref") and e["fema_ref"] in fr.index:
                r[f"FEMA_RL_{lab}"] = fr.loc[e["fema_ref"], f"Q_{lab}"]
            if e.get("fema_struct") and e["fema_struct"] in fs.index:
                r[f"FEMA_ST_{lab}"] = fs.loc[e["fema_struct"], f"Q_{lab}"]
        r["Tpk_HMSchk_100yr"] = float(np.argmax(results["FEMA_100yr"][k]) * DT_MIN / 60.0)
        if e.get("fema_ref") and e["fema_ref"] in fr.index:
            r["Tpk_FEMA_RL_100yr"] = fr.loc[e["fema_ref"], "Tpk_hr_100yr"]
        cmp_rows.append(r)
    cmp = pd.DataFrame(cmp_rows)
    cmp.round(1).to_csv(QA / "comparison_with_FEMA_RoG.csv", index=False)
    pd.set_option("display.width", 250)
    show = ["Junction", "DA_sqmi", "FEMA_RefLine", "HMSchk_100yr", "FEMA_RL_100yr", "FEMA_ST_100yr",
            "Tpk_HMSchk_100yr", "Tpk_FEMA_RL_100yr"]
    print(cmp[[c for c in show if c in cmp]].round(2).to_string(index=False))
    out = results["FEMA_100yr"]["J-ECT030"]
    print("Outlet J-ECT030 peaks:", {r: round(float(Q["J-ECT030"].max())) for r, Q in results.items()})
    n = {t: sum(1 for e in el.values() if e["type"] == t) for t in ("Subbasin", "Junction", "Reach", "Lake")}
    print("elements:", n)


if __name__ == "__main__":
    main()
