"""Extract HEC-HMS results (peak flow, time of peak) for every element and
run, and compare with the Python QA engine and the FEMA RoG model.

Usage: python scripts/09_hms_results.py [path/to/Raymore_Trib12]   (default HMS/Raymore_Trib12)
Outputs: HMS/Results/hms_peaks_all_elements.csv
         HMS/Results/hms_vs_engine.csv
         HMS/Results/hms_vs_fema_reflines.csv
"""
from pathlib import Path
import sys
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "HMS/Results"
RUNS = [f"{s}_{e}" for s in ("FEMA", "Point") for e in ("10yr", "25yr", "50yr", "100yr", "100yr_plus", "500yr")]
T0 = pd.Timestamp("2030-01-01 00:00")


def main():
    from hecdss import HecDss
    try:
        HecDss.set_global_debug_level(0)
    except Exception:
        pass
    prj = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "HMS/Raymore_Trib12"
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    for run in RUNS:
        f = prj / "results" / f"{run}.dss"
        if not f.exists():
            print("missing", f)
            continue
        d = HecDss(str(f))
        els = sorted({p.split("/")[2] for p in d.get_catalog().uncondensed_paths if p.split("/")[3] == "FLOW"})
        for el in els:
            ts = d.get(f"//{el}/FLOW//1Minute/RUN:{run}/")
            v = np.array(ts.values, float)
            t = pd.to_datetime(ts.times)
            i = int(np.nanargmax(v))
            rows.append(dict(Run=run, Element=el, Qpeak_cfs=float(v[i]),
                             Tpeak_hr=(t[i] - T0).total_seconds() / 3600.0,
                             Volume_acft=float(np.nansum(v) * 60.0 / 43560.0)))
        d.close()
    pk = pd.DataFrame(rows)
    pk.round(3).to_csv(OUT / "hms_peaks_all_elements.csv", index=False)

    # vs QA engine (junctions + subbasins)
    eng = pd.read_csv(ROOT / "HMS/QAQC/engine_peaks_all_elements.csv")
    cmp_rows = []
    for _, r in eng.iterrows():
        for run in RUNS:
            h = pk[(pk.Run == run) & (pk.Element == r.Element)]
            if h.empty:
                continue
            cmp_rows.append(dict(Element=r.Element, Type=r.Type, Run=run, HMS_cfs=h.Qpeak_cfs.iloc[0],
                                 Engine_cfs=r[f"Q_{run}"], HMS_Tpk_hr=h.Tpeak_hr.iloc[0],
                                 Engine_Tpk_hr=r[f"Tpk_hr_{run}"]))
    c = pd.DataFrame(cmp_rows)
    c["Ratio_HMS_Engine"] = c.HMS_cfs / c.Engine_cfs
    c["dT_min"] = (c.HMS_Tpk_hr - c.Engine_Tpk_hr) * 60
    c.round(3).to_csv(OUT / "hms_vs_engine.csv", index=False)

    # vs FEMA reference lines
    j = pd.read_csv(ROOT / "HMS/QAQC/comparison_with_FEMA_RoG.csv")
    fr = pd.read_csv(ROOT / "FEMA_Results/FEMA_RefLine_Peaks.csv", index_col=0)
    frows = []
    for _, r in j[j.FEMA_RefLine.notna()].iterrows():
        row = dict(Junction=r.Junction, FEMA_RefLine=r.FEMA_RefLine, DA_sqmi=r.DA_sqmi)
        for e in ("10yr", "25yr", "50yr", "100yr", "100yr_plus", "500yr"):
            h = pk[(pk.Run == f"FEMA_{e}") & (pk.Element == r.Junction)]
            row[f"HMS_{e}"] = h.Qpeak_cfs.iloc[0] if not h.empty else np.nan
            row[f"FEMA_{e}"] = fr.loc[r.FEMA_RefLine, f"Q_{e}"]
            row[f"Ratio_{e}"] = row[f"HMS_{e}"] / row[f"FEMA_{e}"]
        frows.append(row)
    out = pk[pk.Element == "J-ECT030"].set_index("Run").Qpeak_cfs
    row = dict(Junction="J-ECT030 (outlet)", FEMA_RefLine="Trib12Ea_8.6sqmi (839 ft downstream)", DA_sqmi=8.276)
    for e in ("10yr", "25yr", "50yr", "100yr", "100yr_plus", "500yr"):
        row[f"HMS_{e}"] = out.get(f"FEMA_{e}", np.nan)
        row[f"FEMA_{e}"] = fr.loc["Trib12Ea_8.6sqmi", f"Q_{e}"]
        row[f"Ratio_{e}"] = row[f"HMS_{e}"] / row[f"FEMA_{e}"]
    frows.append(row)
    pd.DataFrame(frows).round(3).to_csv(OUT / "hms_vs_fema_reflines.csv", index=False)

    jn = c[c.Type == "Junction"]
    print(f"{pk.Run.nunique()} runs, {pk.Element.nunique()} elements")
    print("HMS / engine peak ratio at junctions: median %.3f, 5-95%% %.3f-%.3f, min %.3f max %.3f" % (
        jn.Ratio_HMS_Engine.median(), jn.Ratio_HMS_Engine.quantile(.05), jn.Ratio_HMS_Engine.quantile(.95),
        jn.Ratio_HMS_Engine.min(), jn.Ratio_HMS_Engine.max()))
    print("time-of-peak difference (HMS - engine) at junctions, min: median %.1f, 5-95%% %.1f to %.1f" % (
        jn.dT_min.median(), jn.dT_min.quantile(.05), jn.dT_min.quantile(.95)))
    print("Outlet J-ECT030:")
    print(c[c.Element == "J-ECT030"][["Run", "HMS_cfs", "Engine_cfs", "Ratio_HMS_Engine", "HMS_Tpk_hr", "dT_min"]]
          .round(3).to_string(index=False))


if __name__ == "__main__":
    main()
