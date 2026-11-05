# RAIN – East Creek Trib 12 watershed analysis (Raymore, Cass County, MO)

A detailed watershed analysis built from FEMA's preliminary Rain-on-Grid (RoG)
HEC-RAS model. **Phase 1 (this commit) builds a HEC-HMS 4.14 model** of the
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
   −0.4 to −0.8 ft (LK2) for all six storms.
5. The FEMA structure "Stage HW" output is not usable (values like 1 ft at a
   987 ft invert), so only structure flows were extracted.

## Results (Python QA engine; see "Status" below)

100-yr peaks at the FEMA reference lines, using the same FEMA rainfall and CN layer:

![HMS vs FEMA](docs/figures/hms_vs_fema_100yr.png)

| Event | FEMA RoG @ `Trib12Ea_8.6sqmi` (839 ft downstream) | HMS, FEMA rainfall @ outlet | HMS, Atlas 14 point rainfall @ outlet |
|---|---:|---:|---:|
| 10-yr | 2,899 | 4,733 | 6,605 |
| 25-yr | 4,383 | 6,279 | 8,638 |
| 50-yr | 5,837 | 7,574 | 10,331 |
| 100-yr | 7,310 | 8,935 | 12,110 |
| 100-yr+ | 8,970 | 10,629 | 14,326 |
| 500-yr | 11,023 | 12,471 | 16,742 |

Across the 11 reference lines inside the watershed, the median HMS/FEMA peak
ratio is 1.36 (10-yr), 1.11 (100-yr) and 0.98 (500-yr). HMS runs high in
frequent storms because the 2D model stores water in every lidar depression
and behind every road embankment. HMS has none of that yet, and that is
exactly the detail the next phases add (below). Full tables are in
`HMS/QAQC/`.

## Status: what has and hasn't been run

* The HMS 4.14 project files were written by `scripts/07_build_hms_project.py`
  using keywords taken from HEC's own HMS 4.14 sample projects and the HMS
  4.14 program.
* **HEC-HMS itself was not executed here.** The cloud session's safety policy
  blocked running the downloaded HMS program. All numbers above come from
  `scripts/hms_check.py`, an independent re-implementation of the same
  methods (SCS CN, SCS UH, Muskingum-Cunge, Modified Puls). HMS results should
  land within a few percent of it.
* **Next step for you:** open `HMS/Raymore_Trib12/Raymore_Trib12.hms` in
  HEC-HMS 4.14 (Windows), compute the 12 runs, and compare
  `J-ECT030` against the table above. If HMS flags any parameter on load, tell
  me the message and I'll fix the writer.

## Repository layout

```
Resources/2D_Raymore/     FEMA preliminary RoG HEC-RAS 6.3.1 model (unchanged)
FEMA_Results/             FEMA peaks extracted from the RAS plan HDFs (ref lines, structures, lake stages)
GIS/FEMA_RoG_geometry.gpkg  FEMA 2D perimeter, BC line, 37 reference lines, 72 structures, 97 culverts, breaklines
GIS/HMS_Raymore.gpkg      Watershed, Subbasins (with parameters), Junctions, Reaches, Streams, Lakes,
                          LongestFlowPaths, ReachXS (cross-section fits)
GIS/rasters/              10 ft burned DEM, D8 flow direction/accumulation, fill depth, subbasin grid (LFS)
HMS/Raymore_Trib12/       HEC-HMS 4.14 project (open Raymore_Trib12.hms)
HMS/parameters/           subbasin / reach / lake parameter tables
HMS/QAQC/                 QA-engine peaks, comparison with FEMA RoG, lake routing
docs/figures/             figures used here
scripts/                  everything above is reproducible from these (run in order 01→08)
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

`03` runs after `06` because its lake-stage table needs the lake polygons from `04`.

## Recommended next phases

1. **Run HMS 4.14** and reconcile with the QA engine.
2. **Road-crossing storage.** Turn the 27 FEMA culvert crossings into HMS
   reservoirs (Controlled Outflow + Culvert + overtopping weir). The culvert
   shape, size, inverts, length and entrance loss are all in
   `GIS/FEMA_RoG_geometry.gpkg`, and the upstream storage comes from the 1 m
   terrain. This is the main thing the 2D model has that HMS lacks.
3. **Subdivision detention.** Collect as-builts (City of Raymore / Cass County
   MS4 records) and screen with lidar (`GIS/rasters/fill_depth_10ft.tif`).
   Each basin becomes a reservoir with its real outlet (orifice, weir, riser).
   25 open-water bodies ≥ 0.25 ac lie inside the watershed; 23 of them
   (21 ac total) are inside subbasins and not yet modeled.
4. **Lake outlets.** Get dam and spillway as-builts for LK1 and LK2 and
   replace the terrain-only curves (neither has a principal-spillway pipe).
5. **The Trib 12 / TribNort diversion** (finding 3): check the storm sewer.
6. **Rainfall decision**: FEMA 0.782 ARF, Atlas 14 point, or an ARF sized to
   the 8.3 sq mi watershed.
