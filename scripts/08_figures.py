"""Documentation figures: model map and HMS-check vs FEMA RoG comparison."""
from pathlib import Path
import numpy as np
import pandas as pd
import geopandas as gpd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

ROOT = Path(__file__).resolve().parents[1]
GP = ROOT / "GIS/HMS_Raymore.gpkg"
FIG = ROOT / "docs/figures"
SURF, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#d9d8d4"
S1, S2, S3, S4 = "#2a78d6", "#eb6834", "#1baf7a", "#6250d6"
plt.rcParams.update({"font.size": 10, "axes.edgecolor": GRID, "axes.labelcolor": INK2, "xtick.color": INK2,
                     "ytick.color": INK2, "figure.facecolor": SURF, "axes.facecolor": SURF})


def model_map():
    S = gpd.read_file(GP, layer="Subbasins")
    ST = gpd.read_file(GP, layer="Streams")
    J = gpd.read_file(GP, layer="Junctions")
    LK = gpd.read_file(GP, layer="Lakes")
    W = gpd.read_file(GP, layer="Watershed")
    fig, ax = plt.subplots(figsize=(11, 11))
    S.plot(ax=ax, facecolor="#f1f0ec", edgecolor="#a9a8a2", linewidth=0.6)
    W.boundary.plot(ax=ax, color=INK, linewidth=1.4)
    ST.plot(ax=ax, color=S1, linewidth=(ST.DA_sqmi.clip(0.04, 8.3) ** 0.45 * 1.6), alpha=0.85)
    LK.plot(ax=ax, facecolor="#bcd6f2", edgecolor=S1, linewidth=0.8)
    groups = [("Structure", ["Structure"], S1, "s", "FEMA road crossing (structure)"),
              ("RefLine", ["RefLine"], S2, "D", "FEMA reference line"),
              ("Node", ["Confluence", "Split"], S3, "o", "Confluence / main-stem break"),
              ("Lake", ["Lake", "LakeInflow"], S4, "^", "Lake outlet / lake inflow")]
    handles = []
    for _, kinds, col, mk, lab in groups:
        j = J[J.PointKind.isin(kinds)]
        ax.scatter(j.geometry.x, j.geometry.y, s=34, c=col, marker=mk, edgecolors=SURF, linewidths=1.2, zorder=5)
        handles.append(Line2D([], [], marker=mk, color=col, linestyle="", markersize=7, label=f"{lab} ({len(j)})"))
    o = J[J.PointKind == "Outlet"]
    ax.scatter(o.geometry.x, o.geometry.y, s=160, c=INK, marker="*", zorder=6)
    handles.append(Line2D([], [], marker="*", color=INK, linestyle="", markersize=11,
                          label="Outlet - bridge 29037ECT030 (8.28 sq mi)"))
    for _, r in S.iterrows():
        c = r.geometry.representative_point()
        ax.annotate(r.Subbasin.replace("SB-", ""), (c.x, c.y), fontsize=5.5, color=INK2, ha="center", va="center")
    for _, l in LK.iterrows():
        c = l.geometry.centroid
        ax.annotate(f"{l.Lake}\n{l.Area_ac:.0f} ac", (c.x, c.y), fontsize=8, color=INK, ha="center", weight="bold")
    ax.legend(handles=handles, loc="lower right", frameon=True, facecolor=SURF, edgecolor=GRID, fontsize=8.5)
    ax.set_title("HEC-HMS model - East Creek Trib 12 at FEMA bridge 29037ECT030\n"
                 f"{len(S)} subbasins, {len(LK)} lakes; NAD83 MO West (ft)", color=INK, loc="left", fontsize=11)
    ax.set_aspect("equal")
    ax.ticklabel_format(style="plain")
    ax.tick_params(labelsize=7)
    fig.savefig(FIG / "hms_model_map.png", dpi=150, bbox_inches="tight")


def comparison():
    c = pd.read_csv(ROOT / "HMS/QAQC/comparison_with_FEMA_RoG.csv")
    c = c[c.FEMA_RL_100yr.notna()].copy()
    # outlet vs the FEMA line 839 ft downstream
    fr = pd.read_csv(ROOT / "FEMA_Results/FEMA_RefLine_Peaks.csv", index_col=0)
    out = c.iloc[0:0]
    pk = pd.read_csv(ROOT / "HMS/QAQC/engine_peaks_all_elements.csv")
    q_out = float(pk.loc[pk.Element == "J-ECT030", "Q_FEMA_100yr"].iloc[0])
    pts = [(r.FEMA_RefLine.replace("sqmi", " sq mi"), r.FEMA_RL_100yr, r.HMSchk_100yr) for _, r in c.iterrows()]
    pts.append(("Outlet vs Trib12Ea_8.6 sq mi", fr.loc["Trib12Ea_8.6sqmi", "Q_100yr"], q_out))
    x = np.array([p[1] for p in pts])
    y = np.array([p[2] for p in pts])
    fig, ax = plt.subplots(figsize=(7.5, 7))
    lim = np.array([200, 12000])
    ax.fill_between(lim, lim * 0.75, lim * 1.25, color="#eeedea", zorder=0, label="±25%")
    ax.plot(lim, lim, color=INK2, linewidth=1.2, zorder=1)
    ax.scatter(x, y, s=60, c=S1, edgecolors=SURF, linewidths=2, zorder=3)
    for (lab, xi, yi) in pts:
        left = lab.startswith("TribNort_2.0")
        ax.annotate(lab, (xi, yi), xytext=(-6 if left else 6, -3), textcoords="offset points", fontsize=7.5,
                    color=INK, ha="right" if left else "left")
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlim(*lim)
    ax.set_ylim(*lim)
    ax.set_xlabel("FEMA preliminary RoG 100-yr peak (cfs)")
    ax.set_ylabel("HMS model, Python QA engine, 100-yr peak (cfs)")
    ax.set_title("100-yr peak flow at FEMA reference lines\nsame FEMA rainfall (78% ARF), same CN layer",
                 color=INK, loc="left", fontsize=11)
    ax.grid(True, which="major", color=GRID, linewidth=0.6)
    ax.text(250, 9000, "1:1 line; shaded band = ±25%", fontsize=8, color=INK2)
    for s in ax.spines.values():
        s.set_visible(False)
    fig.savefig(FIG / "hms_vs_fema_100yr.png", dpi=150, bbox_inches="tight")


if __name__ == "__main__":
    FIG.mkdir(parents=True, exist_ok=True)
    model_map()
    comparison()
    print("figures written")
