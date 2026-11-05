# Detention phase

**Status:** 23 detention basins and ponds are in the HMS model as level-pool
elements `D-DET###`. Their storage comes from 1 m lidar. Their outlets are
**assumed** (KC APWA 5600 release rate) or terrain-controlled until as-built
outlet data is entered.

Scripts and data:

* `scripts/14_detention_inventory.py` (inventory, storage, ratings)
* `scripts/04` and `scripts/07` (model integration)
* `HMS/parameters/detention_basins.csv`
* `HMS/parameters/detention_ratings/DET###.csv`
* `HMS/parameters/detention_outlets_asbuilt.csv` (overrides)
* `GIS/Detention.gpkg`

## Most subdivisions here do not detain

The city storm GIS lists 131 detention, pond and retention polygons in the
watershed. They merge to **91 basins**, because the layer holds two vintages
of the same polygons. Only **23** store meaningful water.

| Not modelled because | Basins |
|---|---:|
| Less than 1 ft between the bottom (or pool) and the lowest point of the rim | 57 |
| Less than 0.1 ac-ft of storage below the rim | 40 |
| Drains less than 2 ac | 28 |
| Dry basin stores less than 0.05 in of runoff over its drainage area (a small polygon on a big creek) | 14 |
| On-stream lake already modelled (LK1 Silver Lake, LK2) | 2 |
| Wet soil / water-quality feature | 3 |

(A basin can fail more than one test.)

The 23 modelled basins hold **58.6 ac-ft** at their spill elevation and drain
688 ac of the 5,300-ac watershed. Most subdivision storm sewers discharge
straight to the creeks, as the city storm GIS shows (324 outfalls). That fits
the observation that many subdivisions did not detain, and it is why the
peaks below barely move at the outlet.

## Method (per basin)

* **Drainage area:** accumulation at the basin's outlet cell (inside its
  footprint) on the terrain + storm-sewer flow network. Basins in series
  (DET007 → DET027, DET032 → DET060) are routed in series.
* **Wet or dry:** a basin is wet when 25 % or more of its 1 m lidar cells lie
  within 0.1 ft of one elevation (hydro-flattened water). Storage is then
  counted above that pool only.
* **Spill:** the lowest ground on a ring 10 ft outside the basin.
* **Storage:** connected 1 m cells within 60 ft of the basin, from the bottom
  or pool to 3 ft above the spill.
* **Outflow**, depending on the basin:
  * **As-built**, if rows exist in `detention_outlets_asbuilt.csv`: orifices
    (diameter, invert), weirs (length, crest) and overflow weirs, plus rim
    overtopping.
  * **Assumed** (13 dry and 3 deeper wet basins): a principal outlet releasing
    **3.0 cfs per acre of drainage area at the spill elevation** (KC APWA 5600
    comprehensive-control 100-yr rate), orifice-shaped below it, plus rim
    overtopping as a broad-crested weir (C = 2.6) along the ring.
  * **Terrain** (7 shallow wet ponds): rim overtopping only; no structure is
    assumed.
* **In HMS:** subbasin → pool junction `J-DET###-Pool` → Modified Puls element
  `D-DET###` (storage–outflow table in the project DSS) → junction `J-DET###`
  → downstream reach.

## Results (HEC-HMS 4.14, all 12 runs, no errors)

* **At the basins:** the median 100-yr peak reduction is 34 %. Assumed-outlet
  basins cut 30–85 % (e.g. DET011 −70 %, DET006 Good Ranch −67 %, DET012
  −79 %). Shallow ponds cut 1–35 %.
* **At junctions** (FEMA 100-yr): up to −13 %, e.g. J-CNF27 −12.9 %,
  J-RL_TribTrib_0.3 −10.7 %, J-MEA030 −10.2 %, J-MEA020 −10.1 %, J-GRA010
  −9.9 %, J-CNF17 −9.1 %. The median junction is unchanged.
* **At the outlet:** −0.3 % to +0.8 % across storms. Delayed releases from
  basins can coincide slightly worse with the main-stem peak.
* **Rating check:** no basin exceeds 87 % of its rating table (the largest is
  DET007 in the Point 500-yr).
* Comparison files: `HMS/Results/hms_peaks_no_detention.csv` (before) and
  `HMS/Results/hms_peaks_all_elements.csv` (with detention).

## Entering as-built outlets (the next step)

1. Find the plan set: `HMS/parameters/detention_city_gis.csv` and the table
   below list the as-builts covering each basin (`docs/as-builts/raymore_asbuilt_index.csv`
   has the public Drive links).
2. Add one row per outlet element to `HMS/parameters/detention_outlets_asbuilt.csv`:

   ```
   Basin,Kind,Size_ft,Invert_ft,Source,Note
   DET006,orifice,1.0,1009.2,Good Ranch detention plans sheet X,12-in low-flow orifice
   DET006,weir,4.0,1011.0,Good Ranch detention plans sheet X,riser crest
   DET006,overflow,30.0,1012.5,Good Ranch detention plans sheet X,emergency spillway
   ```

   `Kind` is `orifice` (Size = diameter), `weir` (Size = crest length) or
   `overflow`. Elevations are in the plan datum; check them against the lidar
   (the 2002 Silver Lake survey ran about 0.5 ft below the lidar).
3. Re-run the scripts below, then compute HMS:

   ```bash
   python scripts/14_detention_inventory.py
   python scripts/07_build_hms_project.py
   ```

Plan sets covering the modelled basins (largest storage first):

| Basin | Storage at spill | Drainage area | As-built plan set |
|---|---:|---:|---|
| DET006 | 15.0 ac-ft | 27 ac | Good Ranch – Storm Water Detention Plans for S Dean Ave |
| DET011 | 9.3 | 33 | Raymore Galleria Phase 1 |
| DET032 | 7.0 | 2.5 | Foxwood Plaza at the Legends |
| DET021 | 5.9 | 46 | Lemor Estates Phase 1 |
| DET012 | 3.2 | 5 | Matlock Johnson (Walmart) |
| DET060 | 3.1 | 4 | Foxwood Plaza at the Legends |
| DET050 | 1.1 | 6 | Municipal Complex Phase 1 |
| DET044 | 0.8 | 14 | Centerview Phase II / Town Center Ph 1, 4 |
| DET030 | 0.6 | 54 | Shadowood Phase 1 |
| DET061 | 0.4 | 4 | Centerview Phase II / Municipal Complex Ph 1 |
| DET072 | 0.4 | 19 | The Prairie View of the Good Ranch |
| DET053 | 0.3 | 5 | Silver Lake (1986) |

The other 11 modelled basins (DET003, 007, 008, 016, 017, 023, 025, 027, 031,
033, 049) have no plan set in the library. Most are wet ponds.

## Known limitations

* The 68 unmodelled polygons hold 114 ac of footprint, mostly shallow. A few
  may have real storage the lidar misses (below a water surface, or a
  closed-pipe outlet with an underground vault).
* There is no tailwater: outlets discharge freely.
* Short reaches from a basin outlet to the next junction (e.g. R-DET021, 91 ft
  over the embankment) get odd trapezoid fits. They pass flow essentially
  unchanged.
* HMS warns that a few very small detention subbasins have a lag under
  0.29 × the 1-min step (SB-DET012, SB-DET032).
