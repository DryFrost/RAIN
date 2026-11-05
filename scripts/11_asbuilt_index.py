"""Index the City of Raymore as-built plan library for the study watershed.

Source: public ArcGIS Online dashboard "Infrastructure Plans - Asbuilt"
(https://raymore.maps.arcgis.com/apps/dashboards/9829c82db8cc4348beb81beaf757dc63)
-> web map 8200971f76bc4ae5b7bae84cd5758bdb
-> feature layer eng2386/FeatureServer/10 (Engineering.DBO.Asbuilts, project
   footprints in NAD83 MO West ft, WKID 102698 = the model's CRS).
The "Public File Share" button is the `linkShare` field (Google Drive).

Water-main-only projects are excluded (per the user).  Remaining documents are
ranked for the stormwater review:
  1 = storm sewer / storm water / grading / detention in the type or name
  2 = type unknown or blank (needs a look)
  3 = sanitary, street, lighting, etc. only

Outputs: GIS/Raymore_Asbuilt_Index.gpkg (layer asbuilts_in_watershed)
         docs/as-builts/raymore_asbuilt_index.csv
"""
from pathlib import Path
import re
import json
import urllib.request
import geopandas as gpd
import pandas as pd
from shapely.geometry import Polygon
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parents[1]
LAYER = "https://services5.arcgis.com/Xl0cAd6WMhA7fHTz/arcgis/rest/services/eng2386/FeatureServer/10"
CRS = (ROOT / "Resources/2D_Raymore/Projection/Projection.prj").read_text()
OUT_GPKG = ROOT / "GIS/Raymore_Asbuilt_Index.gpkg"
OUT_CSV = ROOT / "docs/as-builts/raymore_asbuilt_index.csv"

STORM = re.compile(r"storm|strom|grading|detention|drainage|basin|lake|pond|channel|culvert", re.I)
WATER_ONLY_NAME = re.compile(r"water\s*(?:system|main|line|tower|improvement|upate|update)", re.I)


def drive_id(url):
    if not isinstance(url, str):
        return None
    m = re.search(r"/d/([A-Za-z0-9_-]{20,})", url) or re.search(r"[?&]id=([A-Za-z0-9_-]{20,})", url)
    return m.group(1) if m else None


def fetch():
    q = f"{LAYER}/query?where=1%3D1&outFields=*&returnGeometry=true&outSR=102698&f=json"
    with urllib.request.urlopen(q, timeout=120) as r:
        d = json.load(r)
    rows, geoms = [], []
    for f in d["features"]:
        polys = [Polygon(r) for r in f.get("geometry", {}).get("rings", []) if len(r) >= 4]
        geoms.append(unary_union(polys).buffer(0) if polys else None)
        rows.append(f["attributes"])
    g = gpd.GeoDataFrame(rows, geometry=geoms, crs=CRS)
    for c in ("RES_DATE", "ASBUILT_DATE", "CreationDate", "EditDate"):
        g[c] = pd.to_datetime(g[c], unit="ms", errors="coerce")
    return g[g.geometry.notna()].copy()


def main():
    g = fetch()
    ws = gpd.read_file(ROOT / "GIS/HMS_Raymore.gpkg", layer="Watershed").geometry.iloc[0]
    sb = gpd.read_file(ROOT / "GIS/HMS_Raymore.gpkg", layer="Subbasins")[["Subbasin", "geometry"]]
    g = g[g.intersects(ws)].copy()
    g["Overlap_ac"] = g.geometry.intersection(ws).area / 43560.0
    typ = g.Type.fillna("").astype(str)
    name = g.NAME.fillna("").astype(str)
    water_only = (typ.str.strip().str.lower() == "water") | (name.str.contains(WATER_ONLY_NAME) & ~typ.str.contains(STORM))  # noqa
    g = g[~water_only].copy()
    typ, name = g.Type.fillna("").astype(str), g.NAME.fillna("").astype(str)
    g["Priority"] = 3
    g.loc[typ.str.strip().isin(["", "Unknown", "Survey"]), "Priority"] = 2
    g.loc[typ.str.contains(STORM) | name.str.contains(STORM), "Priority"] = 1
    g["DriveID"] = g.linkShare.map(drive_id)
    # subbasins each document touches (by overlap area)
    hits = gpd.overlay(g[["OBJECTID", "geometry"]], sb, how="intersection", keep_geom_type=True)
    hits["ac"] = hits.area / 43560.0
    hits = hits[hits.ac >= 0.5].sort_values("ac", ascending=False)
    g["Subbasins"] = g.OBJECTID.map(hits.groupby("OBJECTID").Subbasin.apply(lambda s: ";".join(s)))
    g = g.sort_values(["Priority", "Overlap_ac"], ascending=[True, False])
    cols = ["OBJECTID", "NAME", "Type", "Priority", "ASBUILT_DATE", "RES_DATE", "RESOLUTION", "Overlap_ac",
            "Subbasins", "DriveID", "linkShare"]
    OUT_GPKG.unlink(missing_ok=True)
    g[cols + ["geometry"]].to_file(OUT_GPKG, layer="asbuilts_in_watershed")
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    g[cols].assign(NAME=g.NAME.str.replace(r"\s+", " ", regex=True)).round(2).to_csv(OUT_CSV, index=False)
    print(f"{len(g)} documents in the watershed after dropping water-main projects")
    print(g.Priority.value_counts().sort_index().to_string())
    print("unique Drive files:", g.DriveID.nunique(), " missing public link:", g.DriveID.isna().sum())


if __name__ == "__main__":
    main()
