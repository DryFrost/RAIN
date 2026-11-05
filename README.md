# RAIN – East Creek Trib 12 watershed analysis (Raymore, Cass County, MO)

A detailed watershed analysis built from FEMA's preliminary Rain-on-Grid (RoG)
HEC-RAS model. **Phase 1 builds and runs a HEC-HMS 4.14 model** of the
watershed draining to the point the analysis is centered on:

| | |
|---|---|
| Outlet | 38.770832, −94.492901 → FEMA bridge **29037ECT030** on East Creek Trib 12 (Missouri State Plane West ft: 2,790,727 E, 948,173 N) |
| Drainage area | **8.28 sq mi** (5,296 ac), entirely inside the FEMA 2D area (45.4 sq mi) |
| HMS elements | 62 subbasins (3–270 ac, mean 85 ac), 55 Muskingum-Cunge reaches, 2 lakes (level-pool), 64 junctions |
| Land cover | 44 % lawn, 22 % trees, 13 % roads, 8 % crops, 5 % buildings, 5 % bare ground, 2 % water |
| Soils | 51 % C/D, 33 % C, 9 % D, 5 % B (SSURGO via FEMA `Soils.hdf`) |
| Loss | SCS CN from FEMA's own CN table: 20.5 % impervious, pervious CN 80.8 (composite 84.3) |
| Storms | 10, 25, 50, 100, 100+ (upper-CI) and 500-yr; FEMA hyetographs as-is **and** at Atlas 14 point depth |

![HMS model map](docs/figures/hms_model_map.png)

## Things found in the FEMA model that matter

1. **FEMA's rainfall is area-reduced by 0.782**, even though the RAS project
   description says "non-reduced". Every FEMA hyetograph in
   `Precip Data/78% AR/Rainfall.dss` totals exactly 0.782 × the Atlas 14 point
   depth in `Precip.gdb` (100-yr: 7.02 in vs 8.97 in). A 22 % reduction is a
   large-area factor. For an 8 sq mi watershed, and certainly for subdivision
   detention design, it under-states rainfall. The HMS project therefore
   carries both sets: `FEMA_*` (as-is) and `Point_*` (same pattern, Atlas 14
   point depth). Choosing which governs is an engineering decision for you.
2. **The FEMA terrain is not hydro-enforced.** `FinalTerrain.hydroDEM.tif`
   has road embankments 7–8 ft above the culvert inverts. For delineation I
   burned all 97 FEMA culvert barrels (surveyed inverts) into the 1 m terrain.
   With that, 33 of 37 FEMA reference lines reproduce their names' drainage
   areas within ±4 %.
3. **About 0.75 sq mi of upper Trib 12 drains north to "TribNort" in both the
   terrain and the FEMA 2D results.** FEMA's reference-line names say
   otherwise: `Trib12Ea_0.7sqmi` carries only 22 cfs in the FEMA 100-yr, and
   `TribNort_2.0sqmi` really drains 2.74 sq mi. A storm sewer or culvert not
   in the FEMA model probably sends this area south. The HMS model follows the
   terrain (same as FEMA's 2D model). **Field-verify.**
4. **Two on-stream lakes** (LK1 52.5 ac, normal pool 1025.47 ft; LK2 8.3 ac,
   1032.78 ft) have no outlet structures in the FEMA model, so they spill over
   the terrain. HMS routes them as level pools whose terrain-derived curves
   reproduce FEMA's 2D peak lake stages within +0.3 to +0.4 ft (LK1) and
   −0.4 to −0.8 ft (LK2) for all six storms. **LK1 is Silver Lake.** Its
   as-builts (Black & Veatch 132691, conformed 2003) confirm the lake spills
   through the existing open channel and triple 12 × 4.3 ft box under
   Silvertop Ln. The culvert doesn't control below about 1,400 cfs, and the
   2002 survey puts the sill about 0.5 ft below the lidar. See
   [`docs/as-builts/Silver_Lake_BV132691.md`](docs/as-builts/Silver_Lake_BV132691.md).
5. FEMA's `Rainfall.dss` stores incremental precipitation with data type
   **INST-VAL**. HEC-RAS accepts that, but HEC-HMS rejects it for a
   precipitation gage. The HMS project uses a re-written copy with identical
   values stored as PER-CUM.
6. The FEMA structure "Stage HW" output is not usable (values like 1 ft at a
   987 ft invert), so only structure flows were extracted.

## Results (HEC-HMS 4.14)

All 12 runs were computed with HEC-HMS 4.14 (Linux, headless) and finished
with no errors. The only warning is that 14 short reaches "may cause numeric
instabilities"; the hydrographs show none. An independent Python
re-implementation of the same methods (`scripts/hms_check.py`) reproduces the
HMS peaks at every junction within 0–1.2 % and the time of peak within about
1 min, which confirms HMS is computing what was intended.

100-yr peaks at the FEMA reference lines, using the same FEMA rainfall and CN layer:

![HMS vs FEMA](docs/figures/hms_vs_fema_100yr.png)

Peak flow at the outlet (cfs):

| Event | FEMA RoG @ `Trib12Ea_8.6sqmi` (839 ft downstream) | HMS, FEMA rainfall | HMS, Atlas 14 point rainfall |
|---|---:|---:|---:|
| 10-yr | 2,899 | 3,769 | 5,536 |
| 25-yr | 4,383 | 5,223 | 7,526 |
| 50-yr | 5,837 | 6,476 | 9,224 |
| 100-yr | 7,310 | 7,822 | 11,045 |
| 100-yr+ | 8,970 | 9,526 | 13,350 |
| 500-yr | 11,023 | 11,418 | 15,899 |

Across the 11 reference lines inside the watershed, the median HMS/FEMA peak
ratio is 1.31 (10-yr), 1.10 (100-yr) and 1.00 (500-yr). HMS runs high in
frequent storms because the 2D model stores water in every lidar depression
and behind every road embankment. HMS has none of that yet, and that is
exactly the detail the next phases add (below).

One location runs the other way: at `TribUppe_3.4` HMS is 27 % (100-yr) to
34 % (500-yr) **below** FEMA. Reach `R-CNF07` upstream of it is a 4,200 ft
wooded floodplain with about 2 ft of fall, and its single fitted trapezoid
(121 ft bottom, 60:1 sides) over-attenuates in Muskingum-Cunge. An 8-point
(channel + overbank) section would fix this; it's on the list below.

Full tables are in `HMS/Results/`; QA-engine detail is in `HMS/QAQC/`.

## Running HEC-HMS

* **On your PC:** open `HMS/Raymore_Trib12/Raymore_Trib12.hms` in HEC-HMS
  4.14 and compute any run.
* **In a Claude Code cloud session:** `.claude/settings.json` allows one
  command, a headless HMS run from `/root/hec-hms`. HMS isn't kept between
  sessions, so it is downloaded first, then all 12 runs are computed and
  summarized:

```bash
mkdir -p /root/hec-hms && curl -sSL https://www.hec.usace.army.mil/software/hec-hms/downloads/HEC-HMS-4.14-linux64.tar.gz | tar xz -C /root/hec-hms
```

```bash
xvfb-run -a bash /root/hec-hms/HEC-HMS-4.14/hec-hms.sh -s /home/user/RAIN/scripts/hms_compute_all.py
```

```bash
python scripts/09_hms_results.py
```

`hms_compute_all.py` computes `HMS/Raymore_Trib12` in place. To run a
scratch copy instead, write the copy's `.hms` path into
`scripts/HMS_PROJECT` (that file is git-ignored). HMS re-saves project files
in its own format when it closes, so a scratch copy keeps the generated files
clean.

## Repository layout

```
Resources/2D_Raymore/     FEMA preliminary RoG HEC-RAS 6.3.1 model (unchanged)
FEMA_Results/             FEMA peaks extracted from the RAS plan HDFs (ref lines, structures, lake stages)
GIS/FEMA_RoG_geometry.gpkg  FEMA 2D perimeter, BC line, 37 reference lines, 72 structures, 97 culverts, breaklines
GIS/HMS_Raymore.gpkg      Watershed, Subbasins (with parameters), Junctions, Reaches, Streams, Lakes,
                          LongestFlowPaths, ReachXS (cross-section fits)
GIS/rasters/              10 ft burned DEM, D8 flow direction/accumulation, fill depth, subbasin grid (LFS)
HMS/Raymore_Trib12/       HEC-HMS 4.14 project (open Raymore_Trib12.hms)
HMS/Results/              HEC-HMS peaks for every element and run, HMS vs FEMA, HMS vs QA engine
HMS/parameters/           subbasin / reach / lake parameter tables
HMS/QAQC/                 QA-engine peaks, lake routing, Muskingum-Cunge parameters
docs/figures/             figures used here
docs/as-builts/           as-built reviews (Silver Lake)
Resources/AsBuilts/       as-built plan sets (LFS)
GIS/AsBuilts.gpkg         features transcribed from as-builts (Silver Lake culvert, Sunset Channel, control)
scripts/                  everything above is reproducible from these
.claude/settings.json     lets Claude Code run HEC-HMS headless in cloud sessions
```

Methodology, assumptions and parameter sources: **[`HMS/README.md`](HMS/README.md)**.

## Reproducing

```bash
git lfs pull
```

```bash
pip install -r requirements.txt
```

```bash
for s in 01_extract_fema_geometry 02_condition_dem 04_delineate_subbasins 05_hydrologic_parameters 06_lake_storage_outflow 03_extract_fema_results 07_build_hms_project 08_figures; do python scripts/$s.py; done
```

`03` runs after `06` because its lake-stage table needs the lake polygons from
`04`. Then run HMS and `09` as shown above, and re-run `08` so the figure uses
the HMS results.

## Recommended next phases

1. **Road-crossing storage.** Turn the 27 FEMA culvert crossings into HMS
   reservoirs (Controlled Outflow + Culvert + overtopping weir). The culvert
   shape, size, inverts, length and entrance loss are all in
   `GIS/FEMA_RoG_geometry.gpkg`, and the upstream storage comes from the 1 m
   terrain. This is the main thing the 2D model has that HMS lacks.
2. **Subdivision detention.** Collect as-builts (City of Raymore / Cass County
   MS4 records) and screen with lidar (`GIS/rasters/fill_depth_10ft.tif`).
   The inventory starts in `HMS/parameters/detention_inventory.csv`; the first
   entry is Raymore City Hall, held to 1.8 cfs/ac in the 100-yr, from the
   Silver Lake plans.
   Each basin becomes a reservoir with its real outlet (orifice, weir, riser).
   25 open-water bodies ≥ 0.25 ac lie inside the watershed; 23 of them
   (21 ac total) are inside subbasins and not yet modeled.
3. **8-point cross sections** for wide floodplain reaches, starting with
   `R-CNF07`.
4. **Lake outlets.** LK1 (Silver Lake) as-builts are reviewed. Remaining for
   LK1: survey the sill (±0.5 ft changes its 100-yr outflow by about 40 %), and
   confirm whether the area west of the lake (`SB-EAG030`) reaches it by storm
   sewer. LK2 still needs as-builts.
5. **The Trib 12 / TribNort diversion** (finding 3): check the storm sewer.
6. **Rainfall decision**: FEMA 0.782 ARF, Atlas 14 point, or an ARF sized to
   the 8.3 sq mi watershed.
