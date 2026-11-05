"""Extract FEMA HEC-RAS 2D geometry features (perimeter, BC lines, reference
lines, structures, culverts, breaklines, refinement regions) to a GeoPackage.

Usage: python scripts/01_extract_fema_geometry.py
Output: GIS/FEMA_RoG_geometry.gpkg  (CRS: NAD83 MO West ftUS, from Projection.prj)
"""
from pathlib import Path
import h5py
import numpy as np
import geopandas as gpd
from shapely.geometry import LineString, Polygon, Point

ROOT = Path(__file__).resolve().parents[1]
RAS = ROOT / "Resources" / "2D_Raymore"
OUT = ROOT / "GIS" / "FEMA_RoG_geometry.gpkg"
CRS = (RAS / "Projection" / "Projection.prj").read_text()


def dec(v):
    return v.decode(errors="ignore").strip() if isinstance(v, bytes) else v


def polylines(grp, poly=False):
    info = grp["Polyline Info" if not poly else "Polygon Info"][:]
    pts = grp["Polyline Points" if not poly else "Polygon Points"][:]
    geoms = []
    for start, cnt, *_ in info:
        xy = pts[start:start + cnt]
        geoms.append(Polygon(xy) if poly else LineString(xy))
    return geoms


def attrs_df(ds, keep=None):
    a = ds[:]
    cols = keep or list(a.dtype.names)
    return {c: [dec(v) for v in a[c]] for c in cols}


def main():
    OUT.unlink(missing_ok=True)
    f = h5py.File(RAS / "Raymore.g01.hdf", "r")
    g = f["Geometry"]

    # 2D flow area perimeter
    fa = g["2D Flow Areas"]
    geoms = polylines(fa, poly=True)
    d = attrs_df(fa["Attributes"], ["Name", "Mann", "Spacing dx", "Spacing dy", "Cell Count"])
    gpd.GeoDataFrame(d, geometry=geoms, crs=CRS).to_file(OUT, layer="FlowArea2D_Perimeter")

    # BC lines
    bc = g["Boundary Condition Lines"]
    gpd.GeoDataFrame(attrs_df(bc["Attributes"]), geometry=polylines(bc), crs=CRS).to_file(OUT, layer="BC_Lines")

    # Reference lines (FEMA flow reporting locations)
    rl = g["Reference Lines"]
    gpd.GeoDataFrame(attrs_df(rl["Attributes"]), geometry=polylines(rl), crs=CRS).to_file(OUT, layer="Reference_Lines")

    # Breaklines
    bl = g["2D Flow Area Break Lines"]
    gpd.GeoDataFrame(attrs_df(bl["Attributes"], ["Name", "Cell Spacing Near", "Cell Spacing Far"]),
                     geometry=polylines(bl), crs=CRS).to_file(OUT, layer="BreakLines")

    # Refinement regions
    rr = g["2D Flow Area Refinement Regions"]
    gpd.GeoDataFrame(attrs_df(rr["Attributes"], ["Name", "Spacing dx", "Spacing dy"]),
                     geometry=polylines(rr, poly=True), crs=CRS).to_file(OUT, layer="Refinement_Regions")

    # Structures (SA/2D connections)
    st = g["Structures"]
    info = st["Centerline Info"][:]
    pts = st["Centerline Points"][:]
    geoms = [LineString(pts[s:s + c]) for s, c, *_ in info]
    keep = ["Type", "Mode", "Connection", "Description", "Last Edited", "Weir Width",
            "Weir Min Elevation", "Weir Coef", "Culvert Groups", "Use 2D for Overflow"]
    sdf = gpd.GeoDataFrame(attrs_df(st["Attributes"], keep), geometry=geoms, crs=CRS)
    sdf["StructID"] = np.arange(len(sdf))

    # Culvert groups (joined to structures)
    cg = st["Culvert Groups"]
    cga = attrs_df(cg["Attributes"])
    binfo = cg["Barrels/Centerline Info"][:]
    bpts = cg["Barrels/Centerline Points"][:]
    bgeoms = [LineString(bpts[s:s + c]) for s, c, *_ in binfo]
    cdf = gpd.GeoDataFrame(cga, geometry=bgeoms, crs=CRS)
    cdf["Conn"] = [sdf.loc[i, "Connection"] for i in cdf["Structure ID"]]
    cdf.to_file(OUT, layer="Culvert_Barrels")

    summ = cdf.groupby("Structure ID").apply(
        lambda x: "; ".join(f"{int(b)}x {s} {r:g}x{sp:g}ft L={l:g}"
                            for b, s, r, sp, l in zip(x["Barrels"], x["Shape Name"], x["Rise"], x["Span"], x["Length"])),
        include_groups=False)
    sdf["Culverts"] = sdf["StructID"].map(summ).fillna("")
    sdf.to_file(OUT, layer="Structures")

    print(f"Wrote {OUT}")
    for lyr in ["FlowArea2D_Perimeter", "BC_Lines", "Reference_Lines", "BreakLines", "Refinement_Regions",
                "Structures", "Culvert_Barrels"]:
        print(f"  {lyr}: {len(gpd.read_file(OUT, layer=lyr))}")


if __name__ == "__main__":
    main()
