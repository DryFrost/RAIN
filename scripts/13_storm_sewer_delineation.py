"""Compare the subbasins with and without the storm sewer.

Labels every 10 ft cell to the current HMS junction cells (GIS/HMS_Raymore.gpkg)
twice: on the terrain-only D8 graph and on the terrain + storm-sewer graph
(scripts/02b, sewer.py).  The difference is the drainage area the city storm
sewer moves between subbasins.  The model itself (scripts/04-05) uses the
sewer graph.

Outputs: HMS/parameters/sewer_transfer_by_subbasin.csv
         HMS/parameters/sewer_transfers.csv   (from -> to, with network relation)
         GIS/StormSewer_Links.gpkg layer changed_area (cells that change subbasin)
"""
from pathlib import Path
import sys
import numpy as np
import pandas as pd
import geopandas as gpd
import networkx as nx
import rasterio
from rasterio.features import shapes
from shapely.geometry import shape

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hydro  # noqa: E402
import sewer  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
R10 = ROOT / "GIS/rasters"
HMSG = ROOT / "GIS/HMS_Raymore.gpkg"
OUT = ROOT / "GIS/StormSewer_Links.gpkg"
PAR = ROOT / "HMS/parameters"


def relation(D, a, b):
    if "outside" in a or "outside" in b:
        return "watershed boundary"
    ja, jb = "J-" + a[3:], "J-" + b[3:]
    if ja not in D or jb not in D:
        return "?"
    if nx.has_path(D, ja, jb):
        return f"downstream ({nx.shortest_path_length(D, ja, jb)} junctions)"
    if nx.has_path(D, jb, ja):
        return "upstream"
    return "cross-branch"


def main():
    with rasterio.open(R10 / "fdir_10ft.tif") as s:
        F = s.read(1).astype(np.int64)
        tr, crs = s.transform, s.crs
    nr, nc = F.shape
    ac = tr.a ** 2 / 43560.0
    J = gpd.read_file(HMSG, layer="Junctions")
    S = gpd.read_file(HMSG, layer="Subbasins")
    R = gpd.read_file(HMSG, layer="Reaches")
    name_of = dict(zip(S.label, S.Subbasin))
    outlet = int(J.loc[J.PointKind == "Outlet", "cell"].iloc[0])

    labs = {}
    for key, use in (("terrain", False), ("sewer", True)):
        down, step, order, _ = sewer.flow_graph(F, tr.a, use_sewer=use)
        ol = np.zeros(down.size, np.int64)
        ol[J.cell.astype(int).to_numpy()] = J.label.astype(int).to_numpy()
        lab = hydro.label_basins(down, order, ol)
        o2 = np.zeros(down.size, np.int64)
        o2[outlet] = 1
        lab[hydro.label_basins(down, order, o2) != 1] = 0
        labs[key] = lab
    lt, ls = labs["terrain"], labs["sewer"]
    m = max(lt.max(), ls.max()) + 1
    at, as_ = np.bincount(lt, minlength=m) * ac, np.bincount(ls, minlength=m) * ac
    sb = pd.DataFrame([dict(Subbasin=nm, Area_terrain_ac=at[l_], Area_sewer_ac=as_[l_]) for l_, nm in name_of.items()])
    sb["Change_ac"] = sb.Area_sewer_ac - sb.Area_terrain_ac
    sb["Change_pct"] = 100 * sb.Change_ac / sb.Area_terrain_ac.replace(0, np.nan)

    D = nx.DiGraph()
    for _, r in R.iterrows():
        D.add_edge(r.FromJ, r.ToJ)
    for j, k in zip(J.Junction, J.PointKind):
        if k == "LakeInflow":
            D.add_edge(j, "J-" + j[2:].split("-IN")[0])
    chg = lt != ls
    tf = pd.DataFrame(dict(old=lt[chg], new=ls[chg])).value_counts().reset_index(name="cells")
    tf["Area_ac"] = tf.cells * ac
    tf["From"] = tf.old.map(name_of).fillna("(outside watershed)")
    tf["To"] = tf.new.map(name_of).fillna("(outside watershed)")
    tf["Relation"] = [relation(D, a, b) for a, b in zip(tf.From, tf.To)]
    tf = tf.sort_values("Area_ac", ascending=False)[["From", "To", "Area_ac", "Relation"]]
    PAR.mkdir(parents=True, exist_ok=True)
    sb.round(2).sort_values("Change_ac").to_csv(PAR / "sewer_transfer_by_subbasin.csv", index=False)
    tf.round(2).to_csv(PAR / "sewer_transfers.csv", index=False)

    code = np.where(chg, ls + 1, 0).reshape(nr, nc).astype(np.int32)
    polys = [dict(To=name_of.get(int(v) - 1, "(outside watershed)"), geometry=shape(g))
             for g, v in shapes(code, mask=code > 0, transform=tr)]
    if polys:
        cg = gpd.GeoDataFrame(polys, crs=crs).dissolve(by="To").reset_index()
        cg["Area_ac"] = cg.area / 43560.0
        cg.to_file(OUT, layer="changed_area")
    print(f"watershed: terrain {(lt > 0).sum() * ac / 640:.3f} sq mi, with sewer {(ls > 0).sum() * ac / 640:.3f} sq mi")
    print(f"area the sewer moves between subbasins: {chg.sum() * ac:.1f} ac "
          f"({100 * chg.sum() / (ls > 0).sum():.1f} % of the watershed)")
    print(tf[tf.Area_ac >= 3].round(1).to_string(index=False))


if __name__ == "__main__":
    main()
