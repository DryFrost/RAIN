"""Extract FEMA RoG peak flows (and time of peak) at every reference line and
SA/2D connection (structure) for each frequency plan. Structure flow is flow
through the structure only (2D overflow across the road is not included);
reference lines carry the total flow.

Output: FEMA_Results/FEMA_RefLine_Peaks.csv, FEMA_Results/FEMA_Structure_Peaks.csv
"""
from pathlib import Path
import h5py
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAS = ROOT / "Resources/2D_Raymore"
OUT = ROOT / "FEMA_Results"
PLANS = {"p04": "10yr", "p05": "25yr", "p06": "50yr", "p01": "100yr", "p07": "100yr_plus", "p02": "500yr"}
BASE = "Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series"


def dec(a):
    return [x.decode().strip() if isinstance(x, bytes) else str(x) for x in a]


def main():
    OUT.mkdir(exist_ok=True)
    rl_rows, st_rows = {}, {}
    for p, ev in PLANS.items():
        with h5py.File(RAS / f"Raymore.{p}.hdf", "r") as f:
            g = f[BASE]
            t = np.array(g["Time"][:]) * 24.0  # days -> hours from sim start
            names = [n.split("|")[0] for n in dec(g["Reference Lines/Name"][:])]
            q = g["Reference Lines/Flow"][:]
            for j, n in enumerate(names):
                i = int(np.argmax(q[:, j]))
                rl_rows.setdefault(n, {})[f"Q_{ev}"] = float(q[i, j])
                rl_rows[n][f"Tpk_hr_{ev}"] = float(t[i])
            conn = g["SA 2D Area Conn"]
            for name in conn.keys():
                grp = conn[name]
                if "Structure Variables" not in grp:
                    continue
                sv = np.array(grp["Structure Variables"][:])  # Flow, Stage HW, Stage TW
                key = name.replace("Raymore ", "").strip()
                i = int(np.argmax(sv[:, 0]))
                st_rows.setdefault(key, {})[f"Q_{ev}"] = float(sv[i, 0])
                st_rows[key][f"Tpk_hr_{ev}"] = float(t[i])
    rl = pd.DataFrame.from_dict(rl_rows, orient="index")
    rl.index.name = "RefLine"
    rl.round(2).to_csv(OUT / "FEMA_RefLine_Peaks.csv")
    st = pd.DataFrame.from_dict(st_rows, orient="index")
    st.index.name = "Connection"
    st.round(2).to_csv(OUT / "FEMA_Structure_Peaks.csv")
    print(rl[[c for c in rl.columns if c.startswith("Q_")]].round(0).to_string())
    print(len(st), "structures")
    lake_stages()


def lake_stages():
    """FEMA max WSE inside each on-stream lake (needs GIS/HMS_Raymore.gpkg Lakes)."""
    import geopandas as gpd
    import shapely
    gp = ROOT / "GIS/HMS_Raymore.gpkg"
    try:
        LK = gpd.read_file(gp, layer="Lakes")
    except Exception:
        return
    rows = []
    summ = "Results/Unsteady/Output/Output Blocks/Base Output/Summary Output/2D Flow Areas/Raymore"
    for p, ev in PLANS.items():
        with h5py.File(RAS / f"Raymore.{p}.hdf", "r") as f:
            wse = f[summ + "/Maximum Water Surface"][0]
            cc = f["Geometry/2D Flow Areas/Raymore/Cells Center Coordinate"][: len(wse)]
        pts = shapely.points(cc[:, 0], cc[:, 1])
        for _, l in LK.iterrows():
            v = wse[shapely.contains(l.geometry, pts)]
            rows.append(dict(Lake=l.Lake, Event=ev, NormalPool_ft=round(float(l.WSE_ft), 2),
                             FEMA_MaxWSE_ft=round(float(np.median(v)), 2), Cells=int(v.size)))
    pd.DataFrame(rows).to_csv(OUT / "FEMA_Lake_MaxWSE.csv", index=False)


if __name__ == "__main__":
    main()
