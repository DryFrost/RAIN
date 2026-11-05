# HEC-HMS model – methodology

Project: `HMS/Raymore_Trib12/Raymore_Trib12.hms` (HEC-HMS **4.14**, English units,
NAD83 Missouri State Plane West, US ft). Every number below is produced by
`scripts/01`–`07`; nothing was hand-entered.

## Model components

| Component | Name(s) | Notes |
|---|---|---|
| Basin model | `Existing FEMA-Consistent` | 87 subbasins, 82 Muskingum-Cunge reaches, 2 lakes + 26 detention basins (Modified Puls level pools), 115 junctions |
| Met models | `FEMA_<event>` (6) | FEMA RoG hyetographs, values unchanged, in `data/FEMA_Rainfall_ARF78.dss`. Re-written from `Resources/.../78% AR/Rainfall.dss` as PER-CUM, because FEMA's INST-VAL data type is rejected by HMS for precipitation gages |
| | `Point_<event>` (6) | same hyetographs × (Atlas 14 point depth / FEMA depth) = 1.2787, in `data/Atlas14_PointRainfall.dss` |
| Control | `48hr_1min` | 01 Jan 2030 00:00 – 03 Jan 2030 00:00, 1 min (same window as the FEMA plans) |
| Runs | 12 | one per met model, results to `results/<run>.dss` |
| Paired data | `LK1 Storage-Outflow`, `LK2 Storage-Outflow`, `DET### Storage-Outflow` (26) | in the project DSS `Raymore_Trib12.dss` |
| Maps | `maps/*.shp` | watershed, subbasins, streams, lakes |

Events: 10, 25, 50, 100, `100yr_plus` (Atlas 14 upper 90 % CI; FEMA's "101yr" plan p07) and 500-yr.
24-hr point depths (FEMA `Precip.gdb` / Atlas 14): 5.55, 6.83, 7.88, 8.97, 10.31, 11.75 in.
The FEMA temporal pattern is a nested, centre-peaked storm: about 92 % of the depth falls in 6 hr, with the peak at 12:06 on 1 Jan.

### Element naming

* `J-<id>`: junction at a subbasin outlet. The `<id>` is the FEMA structure
  ID without the `29037` county prefix (e.g. `J-ECT030` = bridge 29037ECT030),
  `RL_<FEMA reference line>`, `CNF##` (confluence), `SPL##` (main-stem break),
  `LK#` (lake outlet sill) or `LK#-IN#` (tributary entering a lake).
* `SB-<id>`: the subbasin draining to `J-<id>`. `R-<id>`: the reach leaving
  `J-<id>`. `L-LK#`: the lake (level pool). `J-LK#-Pool`: where tributaries
  and the lake subbasin enter the pool.
* Junction descriptions name the FEMA structure / reference line they match,
  so HMS results can be compared one-to-one with `FEMA_Results/*.csv`.

## Delineation (`02`, `04`)

1. FEMA terrain `FinalTerrain.hydroDEM.tif` (1 m). This is **not**
   hydro-enforced, so all 97 FEMA culvert barrels were burned along their
   centerlines from the surveyed upstream to downstream invert (3-cell-wide
   burn). Bridges are already open in the bare-earth terrain.
2. Aggregated 3×3 by **block minimum** to 9.84 ft cells (keeps burned
   channels connected). pysheds: fill pits → fill depressions → resolve flats
   → D8.
3. Check: 33 of 37 FEMA reference lines reproduce their named drainage areas
   within ±4 %. The other three (`Trib12Ea_0.7`, `Trib12Ea_1.6`,
   `TribNort_2.0`) involve the same ~0.75 sq mi diversion, which FEMA's own 2D
   results also show (see the root README).
4. Watershed divide check: the subject watershed follows the FEMA 2D
   perimeter for about 41,000 ft. At 93 % of transects across it the terrain
   falls away outside, and there is no artificial wall (median spike
   0.4 ft). The terrain extends about 2,700 ft beyond the perimeter, so the
   divide is terrain-defined, not truncated.
5. **Storm sewer** (`02b`, `scripts/sewer.py`): the city's 1,897 inlet-capture
   links send runoff reaching an inlet to its pipe outfall. 274 ac (5.2 %)
   moves between subbasins; see `docs/StormSewer_Delineation.md`.
6. Break points: all 27 FEMA crossings and 11 FEMA reference lines in the
   watershed (≥ 15 ac), confluences where both branches drain ≥ 60 ac, lake
   outlets, and tributaries ≥ 40 ac entering a lake. Points within 250 ft
   (flow distance) of a more important point are merged. Subbasins > 260 ac
   are split on the main stem where possible.

## Subbasin parameters (`05`)

**Loss: SCS Curve Number**, reproducing FEMA `Land Classification/Infiltration.hdf`.
That is FEMA's land-cover × soils CN table (lawn B/C/D = 69/79/84, prairie
61/74/80, trees 60/73/79, bare ground 85/89/91, crops 78/83/87; dual groups
use the D value; buildings, roads, water and channels = 98), evaluated on the
1 m land cover and the 10 ft SSURGO soils grid.

* FEMA's CN-98 classes (buildings, roads, open water, channels, no-data) are
  entered as **Percent Impervious** (100 % runoff in HMS).
* **Curve Number** = area-weighted CN of the remaining (pervious) cells.
* Ia = 0.2 S (HMS default when Initial Abstraction is blank, and FEMA's
  abstraction ratio). Composite CN is in the subbasin description and
  `parameters/subbasin_parameters.csv`.

**Transform: SCS UH (standard, PRF 484)**, lag = 0.6 Tc. Tc is TR-55,
segmented along each subbasin's longest D8 flow path:

| Segment | Rule |
|---|---|
| Sheet | first 100 ft. n by land cover (TR-55 Table 3-1: impervious 0.011, lawn/prairie 0.24, bare 0.05, crops 0.17, trees 0.40). P₂ = 3.66 in (Atlas 14 2-yr 24-hr). s ≥ 0.005 |
| Shallow concentrated | to channel start. Paved V = 20.33 √s on roads and buildings, unpaved V = 16.13 √s elsewhere. s over ±50 ft, ≥ 0.005 |
| Channel | from DA ≥ 30 ac, or sustained FEMA "channel" land cover. Manning n = 0.045, R = DA(sq mi)^0.3 ft (0.4–4 ft), s over ±100 ft ≥ 0.001, V ≤ 12 ft/s |

Minimum Tc is 5 min. Lake subbasins measure Tc only to the water's edge,
because the pool is routed separately. Storm-sewer steps of the flow path
(inlet → outfall) travel at 5 ft/s; 18 subbasins have one. Results: lag
3.9–73 min (median 21.0).
The NRCS lag equation (reported as `Lag_NRCSeq_min`) gives about 40 % shorter
lags. TR-55 was kept as the primary method because it is the segmented method
local criteria most often reference; switch to the lag equation if your
governing criteria call for it.

No baseflow and no canopy or surface storage, consistent with FEMA's RoG.

## Reach parameters (`05`)

**Muskingum-Cunge, trapezoid, automatic Δx/Δt, index flow**

* Length = D8 path between junctions. Slope = regression of the burned-DEM
  profile (minimum 0.0005).
* Trapezoid: least-squares fit of A(h) = b·h + z·h² to the flow area from
  three 1 m terrain cross sections per reach (25/50/75 %), for depths up to
  h_ref = 2.5 + 2·DA^0.35 ft (3–10 ft, roughly the 100-yr depth). Bottom
  width and side slope are the medians of the three fits.
* Manning n: the conveyance-weighted value of FEMA's Manning's n raster across
  the wetted section at h_ref, n_eff = Σd^{5/3} / Σ(d^{5/3}/n_i), limited to
  0.03–0.12. Median 0.064.
* Index flow = 0.5 × the QA engine's 100-yr (FEMA rainfall) peak inflow to
  the reach, following the HMS Technical Reference. HMS uses it only to set
  Δx and Δt. HMS's Muskingum-Cunge is variable-parameter: celerity and X are
  recomputed every step from the current flow.
* Reaches that would cross a lake are replaced by a direct junction link into
  that lake's pool.

`R-CNF07` is a real 4,200 ft wooded floodplain with about 2 ft of fall: the
slope of 0.0005 is confirmed by the 1 m thalweg, and the fitted valley is
570–850 ft wide. Its single trapezoid (121 ft bottom, 60:1 sides) gives very
high Muskingum-Cunge diffusion, and HMS attenuates the 100-yr peak from 4,563
to 2,584 cfs there (inflow 4,574 cfs). That puts `TribUppe_3.4` 27–34 % below FEMA's 2D model at
the 100- and 500-yr, while every other reference line is at or above FEMA. It
needs an 8-point (channel + overbank) section.

## Lakes (`06`)

LK1 (52.5 ac, normal pool 1025.47 ft, 0.68 sq mi) and LK2 (8.3 ac, 1032.78 ft,
0.22 sq mi) are hydro-flattened in the lidar and have no outlet structures in
the FEMA model. Each is a **Modified Puls reach with a storage–outflow table**,
which is mathematically a level-pool reservoir:

* **Storage:** volume above normal pool in the 1 m terrain cells connected to
  the lake, within its contributing subbasins.
* **Outflow:** a broad-crested weir (C = 2.6, FEMA's coefficient),
  strip-integrated across a 1 m transect at the **sill**. The sill is the
  location on the outflow path whose cross-section low point is highest.
* **Start:** the lake begins at normal pool, as in FEMA's model.

Check against FEMA 2D maximum lake stage, all six events
(`QAQC/engine_lake_routing.csv`):

* LK1: +0.26 to +0.37 ft
* LK2: −0.41 to −0.76 ft

**LK1 is Silver Lake.** The Black & Veatch 2002 as-builts (conformed 2003;
review in `docs/as-builts/Silver_Lake_BV132691.md`) confirm the existing outlet
is an open channel through a triple 12 × 4.3 ft cast-in-place box under
Silvertop Ln. The planned spillway rebuild was not constructed.

* The culvert doesn't control below about 1,400 cfs; LK1's maximum modeled
  outflow is 620 cfs.
* The 2002 survey puts the sill about 0.5 ft below the lidar.
* Lowering the rating 0.5 ft raises LK1's 100-yr outflow by 35–45 % and the
  outlet peak by under 1 %.

The LK1 curve is therefore kept as is. LK2's curve is still terrain-only.

## QA/QC engine (`scripts/hms_check.py`)

The engine re-implements the methods above independently:

* SCS CN (incremental)
* NRCS dimensionless UH with Tp = Δt/2 + lag
* variable-parameter Muskingum-Cunge, with HMS's automatic scheme inferred
  from its log notes 41089/41102 (n = ceil(L / c·Δt), Δx = L/n, X not clipped
  at zero)
* storage-indication Modified Puls

Outputs are in `QAQC/`:

* `engine_peaks_all_elements.csv`: peak and time-to-peak for every junction
  and subbasin, all 12 runs
* `comparison_with_FEMA_RoG.csv`: against FEMA reference lines (total flow)
  and structures (through-structure flow only; road overtopping excluded, so
  these are not directly comparable)
* `engine_muskingum_cunge.csv`: celerity, normal depth, subreaches, K, X per reach
* `engine_lake_routing.csv`: lake inflow and outflow, storage, stage, FEMA stage

**Check against HEC-HMS 4.14** (all 12 runs, `Results/hms_vs_engine.csv`):

* junction peaks: HMS/engine 1.000–1.012 (median 1.002)
* subbasin peaks: 1.001–1.008
* time of peak: within about 1 min

The engine is therefore a valid check on the HMS model. Re-run it after any
parameter change before trusting a new HMS result.

`Results/` (from `scripts/09_hms_results.py`) holds:

* `hms_peaks_all_elements.csv`: HMS peak, time of peak and volume for every element and run
* `hms_vs_fema_reflines.csv`: HMS vs FEMA RoG at the 11 reference lines and the outlet
* `hms_vs_engine.csv`: HMS vs the QA engine
* `hms_peaks_detention_passthrough.csv`: the same model with detention storage × 0.001 (basins pass flow through); the baseline for the detention effect

HMS log: no errors. Warnings: 41074 ("very short reach … may cause
numeric instabilities") for 20 short reaches, whose hydrographs are smooth;
41084 for `R-DET051` at high index flows (diffusivity would ask for one more
subreach); and 41784 for `SB-DET012` (lag under 0.29 × the 1-min
step).

## Known limitations of this phase

* No storage at road crossings (27 culverts), so HMS is high in frequent
  storms relative to FEMA's 2D model (HMS/FEMA median ratio at reference
  lines: 1.16 at 10-yr, 1.08 at 100-yr, 1.01 at 500-yr). Subdivision
  detention is routed for the 26 basins that store meaningful water. Three
  outlets come from as-builts; the rest are assumed (`docs/Detention.md`).
* Single-trapezoid reaches over-attenuate on wide flat floodplains
  (`R-CNF07`, see above).
* Ponds inside subbasins are routed only where the city detention layer has them and they store meaningful water (`docs/Detention.md`).
* Storm sewer is "full capture": inlet catchments go to the pipe outfall in every storm (no capacity limit yet).
* Channel R for Tc is a regional power law, not surveyed.
* The lake curves are terrain-only, with no principal spillways.
