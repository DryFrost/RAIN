"""Download the City of Raymore's public stormwater GIS for the study watershed.

Service: services5.arcgis.com/Xl0cAd6WMhA7fHTz/.../RaymoreGIS2386_S1/FeatureServer
  4 strm_detetion (detention basins, polygons)   5 strm_inlet (structures, points)
  10 strm_swr (storm pipes, lines)               + outfall/FeatureServer/0
All in NAD83 MO West ft (WKID 102698 = the model's CRS) except outfalls (3857).

Features within 500 ft of the watershed are kept and tagged with the HMS
subbasin they fall in.
Output: GIS/Raymore_StormGIS.gpkg (layers detention, inlets, pipes, outfalls)
"""
from pathlib import Path
import json
import urllib.request
import urllib.parse
import geopandas as gpd
import pandas as pd
from shapely.geometry import Point, LineString, Polygon, MultiLineString
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parents[1]
BASE = "https://services5.arcgis.com/Xl0cAd6WMhA7fHTz/arcgis/rest/services"
LAYERS = {"detention": "RaymoreGIS2386_S1/FeatureServer/4", "inlets": "RaymoreGIS2386_S1/FeatureServer/5",
          "pipes": "RaymoreGIS2386_S1/FeatureServer/10", "outfalls": "outfall/FeatureServer/0"}
CRS = (ROOT / "Resources/2D_Raymore/Projection/Projection.prj").read_text()
OUT = ROOT / "GIS/Raymore_StormGIS.gpkg"
BUFFER_FT = 500.0


def to_geom(g):
    if not g:
        return None
    if "x" in g:
        return Point(g["x"], g["y"])
    if "paths" in g:
        ls = [LineString(p) for p in g["paths"] if len(p) >= 2]
        return ls[0] if len(ls) == 1 else MultiLineString(ls)
    if "rings" in g:
        return unary_union([Polygon(r) for r in g["rings"] if len(r) >= 4]).buffer(0)
    return None


def fetch(path, envelope):
    rows, geoms, off = [], [], 0
    while True:
        q = dict(where="1=1", outFields="*", returnGeometry="true", outSR="102698", f="json",
                 geometry=json.dumps(dict(xmin=envelope[0], ymin=envelope[1], xmax=envelope[2], ymax=envelope[3],
                                          spatialReference=dict(wkid=102698))),
                 geometryType="esriGeometryEnvelope", inSR="102698", spatialRel="esriSpatialRelIntersects",
                 resultOffset=str(off), resultRecordCount="1000")
        with urllib.request.urlopen(f"{BASE}/{path}/query?" + urllib.parse.urlencode(q), timeout=180) as r:
            d = json.load(r)
        feats = d.get("features", [])
        for f in feats:
            rows.append(f["attributes"])
            geoms.append(to_geom(f.get("geometry")))
        if not d.get("exceededTransferLimit") or not feats:
            break
        off += len(feats)
    g = gpd.GeoDataFrame(rows, geometry=geoms, crs=CRS)
    for c in g.columns:
        if c.lower().endswith("date") or c in ("Date", "Date_"):
            g[c] = pd.to_datetime(g[c], unit="ms", errors="coerce")
    return g[g.geometry.notna()]


def main():
    ws = gpd.read_file(ROOT / "GIS/HMS_Raymore.gpkg", layer="Watershed").geometry.iloc[0]
    sb = gpd.read_file(ROOT / "GIS/HMS_Raymore.gpkg", layer="Subbasins")[["Subbasin", "geometry"]]
    area = ws.buffer(BUFFER_FT)
    OUT.unlink(missing_ok=True)
    for name, path in LAYERS.items():
        g = fetch(path, area.bounds)
        g = g[g.intersects(area)].copy()
        rep = g.geometry.representative_point() if name in ("detention", "pipes") else g.geometry
        tag = gpd.sjoin(gpd.GeoDataFrame(geometry=rep, crs=CRS), sb, how="left", predicate="within")
        g["Subbasin"] = tag.groupby(level=0).Subbasin.first().reindex(g.index).values
        g["InWatershed"] = g.intersects(ws)
        g.to_file(OUT, layer=name)
        print(f"{name}: {len(g)} features ({int(g.InWatershed.sum())} inside the watershed)")
    detention_table()


def detention_table():
    """One row per city detention polygon in the watershed, with the as-built
    plan sets (scripts/11 index) whose footprint covers it -> where to look
    for the outlet structure."""
    d = gpd.read_file(OUT, layer="detention")
    d = d[d.InWatershed].copy()
    d["Area_ac"] = d.area / 43560.0
    c = d.geometry.representative_point()
    d["x"], d["y"] = c.x.round(1), c.y.round(1)
    idx = ROOT / "GIS/Raymore_Asbuilt_Index.gpkg"
    if idx.exists():
        a = gpd.read_file(idx, layer="asbuilts_in_watershed")
        a = a[a.Priority <= 2]
        j = gpd.sjoin(gpd.GeoDataFrame(d[["OBJECTID"]], geometry=c, crs=CRS), a[["NAME", "DriveID", "geometry"]],
                      how="left", predicate="within")
        j["NAME"] = j.NAME.fillna("").str.replace(r"\s+", " ", regex=True)
        d["AsBuilt_Docs"] = j.groupby(level=0).NAME.apply(lambda s: " | ".join(sorted(set(x for x in s if x))))
        d["AsBuilt_DriveIDs"] = j.groupby(level=0).DriveID.apply(lambda s: ";".join(sorted(set(x for x in s.dropna()))))
    d = d.sort_values("Area_ac", ascending=False)
    cols = ["OBJECTID", "Type", "Area_ac", "Subbasin", "x", "y", "AsBuilt_Docs", "AsBuilt_DriveIDs"]
    out = ROOT / "HMS/parameters/detention_city_gis.csv"
    d[[c_ for c_ in cols if c_ in d]].round(3).to_csv(out, index=False)
    print(f"detention table: {len(d)} basins -> {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
