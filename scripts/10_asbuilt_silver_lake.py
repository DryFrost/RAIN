"""Silver Lake (model lake LK1) as-built check.

Source: Black & Veatch project 132691, "Silver Lake Drainage Basin
Improvements", 20 sheets, conformed to construction records 07/02/03
(Resources/AsBuilts/SilverLake_DrainageBasinImprovements_BV132691_2002.pdf,
from City of Raymore).  The values below are transcribed from that set; sheet
numbers are cited.  The spillway sheets 13-18 are stamped NOT USED: the
spillway rebuild was not constructed, so they document the EXISTING outlet.

Outputs: GIS/AsBuilts.gpkg (SilverLake_* layers)
         HMS/QAQC/silverlake_culvert_check.csv
         HMS/QAQC/silverlake_survey_vs_lidar.csv
"""
from pathlib import Path
import numpy as np
import pandas as pd
import geopandas as gpd
import rasterio
from shapely.geometry import Point, LineString

ROOT = Path(__file__).resolve().parents[1]
CRS = (ROOT / "Resources/2D_Raymore/Projection/Projection.prj").read_text()   # plans: MO State Plane West ft
DEM = ROOT / "Resources/2D_Raymore/Terrain/FinalTerrain.hydroDEM.tif"
OUT = ROOT / "GIS/AsBuilts.gpkg"
QA = ROOT / "HMS/QAQC"

# Sheet 13 note 2: existing cast-in-place box culvert under Silvertop Lane
CULVERT = dict(Name="Silvertop Ln culvert (existing)", Barrels=3, Span_ft=12.0, Rise_ft=4.3, Length_ft=40.0,
               Type="Cast-in-place concrete box, concrete wingwalls",
               Source="B&V 132691 sheet 13 note 2 (2002 existing condition)",
               x=2795522.0, y=959250.0, xy_note="Silvertop Ln centerline at spillway, +/-20 ft (sheet 13 plan)")
CULV_INVERT = 1024.9   # ft, between sheet 13 existing grade at STA 1+60 (1025.1) and 2+40 (1024.7)
ROAD_CREST = 1035.5    # ft, max terrain on the culvert line (sheet 13 plan contours 1033-1035)

# Sheet 13 profile: existing grade along the spillway channel (stationing increases downstream, west)
SPILLWAY_EX = {160: 1025.1, 240: 1024.7, 260: 1024.4, 280: 1024.4, 300: 1024.3, 320: 1024.1, 340: 1023.9,
               360: 1023.9, 380: 1023.9, 400: 1023.9, 420: 1023.8, 440: 1023.7, 460: 1023.5, 480: 1023.2,
               500: 1023.1, 520: 1022.8}
STA_ROAD = 200.0       # Silvertop Ln centerline station (sheet 13)

# Sheet 2: Sunset Channel (constructed) centerline, MO State Plane West ft
SUNSET_CL = [(607.94, 2798598.3578, 960923.9793), (620, 2798607.6002, 960931.7219), (640, 2798622.9314, 960944.5653),
             (660, 2798640.2254, 960954.3634), (680, 2798657.8630, 960963.7320), (700, 2798674.8189, 960974.3383),
             (720, 2798691.7749, 960984.9447), (1290.05, 2798751.6364, 961551.4050),
             (1300, 2798752.6276, 961571.3804), (1320, 2798753.6187, 961591.3558),
             (1340, 2798754.6099, 961611.3313), (1360, 2798755.1647, 961631.3176),
             (1368.04, 2798755.4307, 961651.3144)]
CONTROL_POINTS = [("C.P. #1", 2798241.29, 960503.78), ("C.P. #2", 2798511.90, 960890.53),
                  ("C.P. #4", 2798705.56, 961112.19)]

# Sheet 2 tables (design storm 100-yr, 24-hr 7.94 in; 10-yr 5.64 in; Type II)
SUNSET_HYDRO = pd.DataFrame([
    ("SS-1", 35.0, None, None, 63.0, 63.0, "Raymore City Hall; runoff limited by detention to 1.8 cfs/ac (100-yr)"),
    ("SS-2", 61.6, 25.2, 84.9, 213.3, 294.3, ""), ("SS-3", 3.3, 5.1, 85.2, 218.5, 302.5, "cumulative"),
    ("SS-4", 27.0, 24.0, 89.0, 291.5, 411.2, "cumulative, to RCB 517/517A")],
    columns=["Subarea", "Area_ac", "Lag_min", "CN", "Q10_cum_cfs", "Q100_cum_cfs", "Note"])
SILVERLAKE_HYDRO = pd.DataFrame([   # spillway table, stamped NOT USED (design for the unbuilt spillway)
    ("SL-1", 15.89, 16.14, 78.00, 59.75), ("SL-3", 54.03, 18.24, 77.38, 200.95), ("SL-4", 36.38, 35.76, 78.00, 97.84),
    ("SL-5", 59.91, 35.10, 84.01, 181.86), ("SL-6", 68.78, 24.24, 79.52, 240.36), ("SL-7", 49.02, 29.94, 78.06, 140.71),
    ("SL-8", 5.91, 10.92, 78.00, 28.18), ("SL-9", 281.57, 11.64, 81.00, 1361.19), ("SL-10", 9.14, 3.54, 78.00, 52.75)],
    columns=["Subarea", "Area_ac", "Lag_min", "CN", "Q100_cfs"])
BV_LAKE_OUTFLOW_100YR = 131.09   # cfs, lake -> culvert (unbuilt lowered spillway design)


def culvert_inlet_control_hw(Q):
    """FHWA HDS-5 inlet control, box culvert with 30-75 deg wingwall flares
    (form 1: K = 0.026, M = 1.0; submerged c = 0.0347, Y = 0.81)."""
    nb, B, D = CULVERT["Barrels"], CULVERT["Span_ft"], CULVERT["Rise_ft"]
    q = Q / nb
    x = q / (B * D * D ** 0.5)
    yc = ((q / B) ** 2 / 32.2) ** (1 / 3)
    unsub = 1.5 * yc / D + 0.026 * x
    sub = 0.0347 * x ** 2 + 0.81
    hwd = unsub if x < 3.5 else (sub if x > 4.0 else unsub + (sub - unsub) * (x - 3.5) / 0.5)
    return CULV_INVERT + hwd * D


def main():
    OUT.unlink(missing_ok=True)
    gpd.GeoDataFrame([{k: v for k, v in CULVERT.items() if k not in ("x", "y")} |
                      dict(Invert_ft_est=CULV_INVERT, RoadCrest_ft=ROAD_CREST)],
                     geometry=[Point(CULVERT["x"], CULVERT["y"])], crs=CRS).to_file(OUT, layer="SilverLake_Culvert")
    gpd.GeoDataFrame(dict(Name=["Sunset Channel (constructed 2003)"], Sta_from=[SUNSET_CL[0][0]], Sta_to=[SUNSET_CL[-1][0]],
                          Section=["~30 ft bottom, 2.5H:1V side slopes (sheet 2 note 2)"],
                          Source=["B&V 132691 sheet 2 coordinate table (intermediate stations 7+40 to 12+80 not transcribed)"]),
                     geometry=[LineString([(x, y) for _, x, y in SUNSET_CL])], crs=CRS).to_file(OUT, layer="SilverLake_SunsetChannel")
    gpd.GeoDataFrame(dict(Name=[c[0] for c in CONTROL_POINTS]),
                     geometry=[Point(c[1], c[2]) for c in CONTROL_POINTS], crs=CRS).to_file(OUT, layer="SilverLake_ControlPoints")

    # culvert capacity vs the terrain-derived LK1 sill rating
    rt = pd.read_csv(ROOT / "HMS/parameters/lake_LK1_rating.csv")
    rows = []
    for Q in [50, 100, 150, 300, 648, 1000, 1400, 1500, 2000]:
        rows.append(dict(Q_cfs=Q, Culvert_HW_ft=culvert_inlet_control_hw(Q),
                         LakeStage_SillRating_ft=float(np.interp(Q, rt.Outflow_cfs, rt.Elev_ft))))
    cc = pd.DataFrame(rows)
    cc["Culvert_controls"] = cc.Culvert_HW_ft > cc.LakeStage_SillRating_ft
    QA.mkdir(parents=True, exist_ok=True)
    cc.round(2).to_csv(QA / "silverlake_culvert_check.csv", index=False)

    # 2002 survey (existing grade) vs lidar thalweg along the spillway (assumed due west of the road line)
    dem = rasterio.open(DEM)
    sv = []
    for sta, z in SPILLWAY_EX.items():
        x = CULVERT["x"] - (sta - STA_ROAD)
        zs = [v[0] for v in dem.sample([(x, CULVERT["y"] + dy) for dy in range(-45, 50, 5)])]
        sv.append(dict(Station=sta, Survey2002_EX_ft=z, Lidar_thalweg_ft=float(min(zs)), Lidar_minus_survey_ft=float(min(zs)) - z))
    sv = pd.DataFrame(sv)
    sv.round(2).to_csv(QA / "silverlake_survey_vs_lidar.csv", index=False)

    print(cc.round(2).to_string(index=False))
    print(sv.round(2).to_string(index=False))
    print("median lidar - survey: %.2f ft" % sv.Lidar_minus_survey_ft.median())
    print("B&V Sunset 100-yr at RCB 517: %.1f cfs from %.1f ac" % (SUNSET_HYDRO.Q100_cum_cfs.iloc[-1], SUNSET_HYDRO.Area_ac.sum()))
    print("B&V Silver Lake subareas listed: %.1f ac; design lake outflow %.1f cfs" % (SILVERLAKE_HYDRO.Area_ac.sum(), BV_LAKE_OUTFLOW_100YR))


if __name__ == "__main__":
    main()
