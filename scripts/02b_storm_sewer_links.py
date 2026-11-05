"""Build the storm-sewer inlet-capture links (see scripts/sewer.py for the rules).

Needs: GIS/rasters/{fdir,acc,dem_burn}_10ft.tif (script 02) and
       GIS/Raymore_StormGIS.gpkg (script 12).
Outputs: HMS/parameters/sewer_links.csv (inlet cell -> outfall cell)
         GIS/StormSewer_Links.gpkg (systems with outfall; inlet->outfall link lines)
         GIS/rasters/acc_sewer_10ft.tif (flow accumulation with sewer links)
"""
from pathlib import Path
import sys
import numpy as np
import geopandas as gpd
import rasterio
from shapely.geometry import LineString

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sewer  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
R10 = ROOT / "GIS/rasters"
OUT = ROOT / "GIS/StormSewer_Links.gpkg"


def main():
    with rasterio.open(R10 / "fdir_10ft.tif") as s:
        F = s.read(1).astype(np.int64)
        tr, crs, prof = s.transform, s.crs, s.profile
    A = rasterio.open(R10 / "acc_10ft.tif").read(1).ravel().astype(np.float64)
    Z = rasterio.open(R10 / "dem_burn_10ft.tif").read(1)
    nc = F.shape[1]
    systems, links = sewer.build_links(F, A, Z, tr, crs)
    sewer.LINKS_CSV.parent.mkdir(parents=True, exist_ok=True)
    links.to_csv(sewer.LINKS_CSV, index=False)
    OUT.unlink(missing_ok=True)
    systems.to_file(OUT, layer="systems")
    gpd.GeoDataFrame(links.drop(columns=["ic", "oc"]),
                     geometry=[LineString([(x, y), tr * ((oc % nc) + 0.5, (oc // nc) + 0.5)])
                               for x, y, oc in zip(links.x, links.y, links.oc)], crs=crs).to_file(OUT, layer="links")
    _, _, _, acc = sewer.flow_graph(F, tr.a, use_sewer=True)
    prof.update(dtype="float32", nodata=-1, compress="deflate", predictor=3)
    with rasterio.open(R10 / "acc_sewer_10ft.tif", "w", **prof) as d:
        d.write(acc.reshape(F.shape).astype(np.float32), 1)
    print(f"{len(systems)} pipe systems; {len(links)} inlet links re-route flow "
          f"({links.attrs['n_inline']} in-line links follow the terrain and are not needed)")


if __name__ == "__main__":
    main()
