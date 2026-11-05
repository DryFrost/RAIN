"""Hydro-condition the FEMA terrain for delineation.

1. Burn every FEMA culvert barrel (97 barrels, surveyed inverts) into the 1 m
   (3.28 ft) FEMA terrain; road embankments otherwise dam every crossing.
   Bridges are already open in the bare-earth terrain and are left alone.
2. Aggregate 3x3 with a block MINIMUM -> 9.84 ft cells (keeps burned channels
   and narrow ditches connected while cutting the cell count 9x).
3. pysheds: fill pits -> fill depressions -> resolve flats -> D8 flow
   direction -> flow accumulation.

Outputs (GIS/rasters/): dem_burn_10ft.tif, fdir_10ft.tif, acc_10ft.tif, fill_depth_10ft.tif
"""
from pathlib import Path
import numpy as np
if not hasattr(np, "in1d"):  # pysheds 0.5 uses np.in1d (removed in NumPy 2.4+)
    np.in1d = np.isin
import rasterio
from rasterio.transform import Affine
import geopandas as gpd
from pysheds.grid import Grid
from pysheds.sview import Raster, ViewFinder
import pyproj

ROOT = Path(__file__).resolve().parents[1]
DEM = ROOT / "Resources/2D_Raymore/Terrain/FinalTerrain.hydroDEM.tif"
GPKG = ROOT / "GIS/FEMA_RoG_geometry.gpkg"
OUT = ROOT / "GIS/rasters"
AGG = 3
NODATA = -9999.0
D8 = (64, 128, 1, 2, 4, 8, 16, 32)  # N NE E SE S SW W NW (pysheds/ESRI)


def burn_culverts(z, transform):
    inv = ~transform
    cb = gpd.read_file(GPKG, layer="Culvert_Barrels")
    n = 0
    for _, r in cb.iterrows():
        line = r.geometry
        us, ds = float(r["US Invert"]), float(r["DS Invert"])
        if not (np.isfinite(us) and np.isfinite(ds)):
            continue
        # 2 ft beyond each end so the burn ties into the channel
        npts = int(line.length / 1.0) + 2
        for f in np.linspace(0, 1, npts):
            p = line.interpolate(f, normalized=True)
            zi = us + (ds - us) * f
            c, rr = inv * (p.x, p.y)
            c, rr = int(c), int(rr)
            for dr in (-1, 0, 1):
                for dc in (-1, 0, 1):
                    i, j = rr + dr, c + dc
                    if 0 <= i < z.shape[0] and 0 <= j < z.shape[1] and z[i, j] != NODATA:
                        z[i, j] = min(z[i, j], zi)
        n += 1
    return n


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    with rasterio.open(DEM) as src:
        z = src.read(1)
        tr = src.transform
        crs = src.crs or rasterio.crs.CRS.from_wkt((ROOT / "Resources/2D_Raymore/Projection/Projection.prj").read_text())
    print("DEM", z.shape, tr)
    nb = burn_culverts(z, tr)
    print("burned barrels:", nb)

    # block-min aggregation (nodata excluded)
    H, W = (z.shape[0] // AGG) * AGG, (z.shape[1] // AGG) * AGG
    zz = z[:H, :W].astype(np.float32)
    zz[zz == NODATA] = np.inf
    agg = zz.reshape(H // AGG, AGG, W // AGG, AGG).min(axis=(1, 3))
    agg[~np.isfinite(agg)] = NODATA
    del z, zz
    atr = tr * Affine.scale(AGG)
    print("aggregated", agg.shape, atr.a)

    vf = ViewFinder(affine=atr, shape=agg.shape, nodata=NODATA, crs=pyproj.Proj(crs.to_wkt(), preserve_units=True))
    dem = Raster(agg.astype(np.float64), viewfinder=vf)
    grid = Grid(viewfinder=vf)
    pit = grid.fill_pits(dem)
    flooded = grid.fill_depressions(pit)
    inflated = grid.resolve_flats(flooded)
    fdir = grid.flowdir(inflated, dirmap=D8)
    acc = grid.accumulation(fdir, dirmap=D8)

    prof = dict(driver="GTiff", height=agg.shape[0], width=agg.shape[1], count=1, crs=crs,
                transform=atr, compress="deflate", tiled=True, blockxsize=256, blockysize=256)
    with rasterio.open(OUT / "dem_burn_10ft.tif", "w", dtype="float32", nodata=NODATA, predictor=3, **prof) as d:
        d.write(agg.astype(np.float32), 1)
    fd = np.where(agg == NODATA, NODATA, np.asarray(flooded) - agg).astype(np.float32)
    with rasterio.open(OUT / "fill_depth_10ft.tif", "w", dtype="float32", nodata=NODATA, predictor=3, **prof) as d:
        d.write(fd, 1)
    with rasterio.open(OUT / "fdir_10ft.tif", "w", dtype="int16", nodata=0, **prof) as d:
        d.write(np.asarray(fdir).astype(np.int16), 1)
    with rasterio.open(OUT / "acc_10ft.tif", "w", dtype="float32", nodata=-1, predictor=3, **prof) as d:
        d.write(np.asarray(acc).astype(np.float32), 1)
    print("done")


if __name__ == "__main__":
    main()
