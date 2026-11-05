# Detention phase

**Status:** 26 detention basins and ponds are in the HMS model as level-pool
elements `D-DET###`, with storage from 1 m lidar.

* **3 outlets are from as-builts:** DET006 Good Ranch, DET011 Raymore
  Galleria and DET021 Le'Mor Estates.
* **16 are assumed:** the KC APWA 5600 release rate.
* **7 are terrain-controlled:** shallow wet ponds.

Scripts and data:

* `scripts/14_detention_inventory.py` (inventory, storage, ratings, capture links)
* `scripts/04`, `05` and `07` (model integration)
* `HMS/parameters/detention_basins.csv`
* `HMS/parameters/detention_ratings/DET###.csv`
* `HMS/parameters/detention_outlets_asbuilt.csv` (as-built outlets)
* `HMS/parameters/detention_links.csv` (pond capture links)
* `GIS/Detention.gpkg`

## Most subdivisions here do not detain

The city storm GIS lists 131 detention, pond and retention polygons in the
watershed. They merge to **91 basins**, because the layer holds two vintages
of the same polygons. Only **26** store meaningful water.

| Not modelled because | Basins |
|---|---:|
| Less than 1 ft between the bottom (or pool) and the spill | 55 |
| Less than 0.1 ac-ft of storage below the spill | 37 |
| Drains less than 2 ac | 20 |
| Dry basin stores less than 0.05 in of runoff over its drainage area (a small polygon on a big creek) | 15 |
| On-stream lake already modelled (LK1 Silver Lake, LK2) | 2 |
| Wet soil / water-quality feature / lake type | 5 |

(A basin can fail more than one test.)

The 26 modelled basins hold **76.9 ac-ft** at their spill elevation. Their
local subbasins cover 694 ac of the 5,300-ac watershed. Most subdivision storm
sewers discharge straight to the creeks, as the city storm GIS shows (324
outfalls). That fits the observation that many subdivisions did not detain,
and it is why the outlet peak moves only a few percent.

## Method (per basin)

* **Drainage area:** everything whose flow enters the basin footprint, on the
  terrain + storm-sewer flow network. On a flat pool the 10 ft D8 grid can
  leave the footprint through a second cell. Before this was fixed, 17.6 of
  the 48 ac reaching DET006 bypassed its outlet. **Capture links** now send
  every footprint cell that leaves the footprint to the basin outlet (201
  links; used by delineation `04` and parameters `05`). Basins in series
  (DET007 → DET027, DET032 → DET060) are routed in series.
* **Pipes through and out of a basin:** a city pipe system can run through a
  pond. It reaches the pond, leaves by the outlet structure and continues
  downstream, all digitized as one network. Inlet capture (`02b`) sends every
  inlet to the system's final outfall, so inlets upstream of the pond would
  skip it. `14` finds these systems: a pipe node inside the basin, with the
  outfall beyond it.
  * Inlets whose pipe path passes the basin go to the basin outlet (25 links;
    the 20 Foxwood Plaza inlets above DET060 lift its drainage area from 4 to
    13 ac).
  * The basin outlet then follows the outlet pipe to its outfall (24 links).
    DET006's 48 in outlet runs SE under **Dean Ave**, so the pond now
    discharges east of Dean, joining the creek at J-CNF30 instead of crossing
    the road on the surface.
* **Wet or dry:** a basin is wet when 25 % or more of its 1 m lidar cells lie
  within 0.1 ft of one elevation (hydro-flattened water). Storage is then
  counted above that pool.
* **Spill:** overflow has to cross every ring 10, 20 and 30 ft outside the
  basin. The spill is therefore the highest of the rings' lowest points. A
  single 10 ft ring read an inflow swale as the spill: for DET006 it gave
  1012.1, where the terrain saddle is 1013.4 and the plan spillway 1013.0.
* **Storage:** connected 1 m cells within 60 ft of the basin, from the bottom
  or pool to 5 ft above the spill.
  * Where an as-built gives a lower design pool or outlet flowline
    (`pool` row), the storage is extended below the lidar surface with the
    area of the pool cells.
* **Outflow**, depending on the basin:
  * **As-built** (rows in `detention_outlets_asbuilt.csv`):
    * orifices, V-notches, riser windows (C = 3.0) and overflow spillways
      (C = 2.6);
    * the barrel caps everything that discharges through it;
    * plus rim overtopping.
  * **Assumed** (13 dry and 3 deeper wet basins): a principal outlet releasing
    **3.0 cfs per acre of drainage area at the spill elevation** (KC APWA 5600
    comprehensive-control 100-yr rate), orifice-shaped below it, plus rim
    overtopping.
  * **Terrain** (7 shallow wet ponds): rim overtopping only; no structure is
    assumed.
  * Rim overtopping is a broad-crested weir (C = 2.6) along each ring; the
    ring that passes the least flow controls.
* **In HMS:** subbasin → pool junction `J-DET###-Pool` → Modified Puls element
  `D-DET###` (storage–outflow table in the project DSS) → junction `J-DET###`
  → downstream reach.

## As-built outlets entered

| Basin | Plan set (sheet) | Outlet | Check against the plans |
|---|---|---|---|
| DET006 | Good Ranch – Dean Ave and Regional Detention No. 1 (13) | Wet pool 1008.0. A 7 × 7 ft box with a 45° V-notch from 1008.0 to the grate at 1012.5, two 72 in windows at 1010.0, a 48 in barrel at invert 1002.23, and an emergency spillway at 1013.0. | Storage above the pool: 25.8 ac-ft at 1013.0 vs 1,111,469 cf (25.5 ac-ft) on the plans. Release: 20.5 / 88.9 / 177 cfs at the plan's 2 / 10 / 100-yr stages, vs 17.8 / 87.4 / 165.6 cfs designed. |
| DET011 | Raymore Galleria storm sewer as-built (5, 6) | A 30 in CMP (Line 3) with a flared end section; flowline 1035.38 in, 1033.85 out. Top of berm 1048.0; no riser. | Lidar spill 1047.9 vs berm 1048.0. HMS 100-yr water surface 1045.0 (FEMA rain) and 1046.6 (Atlas 14 point), vs 1046.87 on the plans. |
| DET021 | Le'Mor Estates supplemental plans as-built (10) | A 54 in RCP at the basin floor (FES 7-2, 993.82 → FES 7-1, 993.11) and a 24 in RCP at 1001.25. | The plans label it "D.E. for **proposed** detention basin". No control structure is shown, so it barely detains: −16 % in the 100-yr, where the assumed outlet gave −50 %. |

Not entered:

* **DET012** (Walmart): the plans show two cells joined by a 56 ft 12 in pipe,
  but not the north cell's outlet into the 48 in system. It stays on the
  assumed outlet.
* **DET050 / DET061** (Municipal Complex Phase 1, sheet 17 "Pond Plan &
  Details", 105-page set). The plans show two ponds:
  * **West pond (DET050):** an 18 in RCP principal spillway with a headwall at
    about 1067.0, and a SW emergency spillway 114.35 ft wide at **1078.5**.
  * **East pond (DET061):** a principal spillway pipe at about 1070.0, and a SE
    emergency spillway 48.92 ft wide at **1075.5**.

  The lidar disagrees with the plan spillways. DET050 spills at about 1074.0
  through a saddle at its east end, toward the low ground below DET061.
  DET061 spills at about 1073.6 over its SE side. These are 4.5 and 1.9 ft
  below the plan spillways, so the ponds as built (or as regraded since 2001)
  crest lower than drawn. The model keeps the lidar rims and the assumed
  outlets. Field-check the principal spillway pipes before entering them.
* **DET032 / DET060** (Foxwood Plaza at the Legends): the library file is the
  3-sheet *Legends at Raymore Public Water Main Improvements* plan, with no
  detention sheets.
* **DET006 drainage area:** the plans give **119.5 ac** (78.8 ac commercial +
  40.7 ac residential). Terrain + city sewer give **48 ac** today: the Dean
  Ave system from the north (city system 416) and the slope west of the pond.
  The unplatted land between the pond and the highway is still open ground in
  the lidar. If a commercial tract is built there, or elsewhere and piped to
  the pond (private pipes are not in the city layer), DET006 will receive
  about 2.5 times the modelled inflow. Check this on aerials or in the field.

## Results (HEC-HMS 4.14, all 12 runs, no errors)

The effect of detention is measured against the same model with the basins
passing flow straight through (storage × 0.001, `DET_STORAGE_FACTOR=0.001
python scripts/07_build_hms_project.py`). That way only the storage differs,
not the subbasins.

* **At the basins** (FEMA 100-yr): the median peak reduction is 41 %.
  * DET006 −83 % (260 → 44 cfs; water surface 1010.9);
  * DET011 −75 % (275 → 70 cfs);
  * DET012 −79 %, DET032 −79 %, DET060 −60 % (87 → 35 cfs), DET050 −49 %;
  * DET021 −16 % (54 in floor pipe);
  * shallow ponds −1 % to −51 %.
* **At junctions** (FEMA 100-yr):
  * median −1.9 %; 23 of 63 junctions drop 5 % or more;
  * J-CNF30 −31 %, J-GRA010 −30 %, J-LK1-IN2 −18 %, J-MCT010 −17 %, J-ECT070
    −13 %, J-RL_Trib12Ea_1.6 −13 %, J-MEA010 / MEA020 / CNF17 −11 %;
  * no junction rises more than 2 %.
* **At the outlet** J-ECT030:

  | Event | FEMA rain: pass-through → detention | Atlas 14 point rain |
  |---|---|---|
  | 10-yr | 3,692 → 3,522 cfs (−4.6 %) | 5,437 → 5,222 (−4.0 %) |
  | 100-yr | 7,700 → 7,456 (−3.2 %) | 10,896 → 10,588 (−2.8 %) |
  | 500-yr | 11,266 → 10,949 (−2.8 %) | 15,713 → 15,336 (−2.4 %) |

* **Rating check:** no basin exceeds 53 % of its rating table (the largest is
  DET007 in the Point 500-yr).
* Comparison files:
  * `HMS/Results/hms_peaks_detention_passthrough.csv` (same model, no storage);
  * `HMS/Results/hms_peaks_all_elements.csv` (with detention);
  * `HMS/Results/hms_peaks_no_detention.csv` (the earlier 61-subbasin model,
    before detention points split the subbasins).

## Entering more as-built outlets

1. Find the plan set: `HMS/parameters/detention_city_gis.csv` and the table
   below list the as-builts covering each basin (`docs/as-builts/raymore_asbuilt_index.csv`
   has the public Drive links).
2. Add one row per outlet element to `HMS/parameters/detention_outlets_asbuilt.csv`:

   ```
   Basin,Kind,Size_ft,Invert_ft,Top_ft,Source,Note
   DET012,pool,,1066.0,,Matlock Johnson (Walmart) sheet 1,outlet flowline
   DET012,orifice,1.0,1066.0,,Matlock Johnson (Walmart) sheet 1,12-in low-flow pipe
   DET012,weir,4.0,1069.0,,...,riser window
   DET012,vnotch,45,1067.0,1070.0,...,V-notch (Size = angle, Top_ft = top of notch)
   DET012,barrel,2.0,1064.5,,...,outlet pipe; caps the riser's inflow
   DET012,overflow,30.0,1072.0,,...,emergency spillway
   ```

   `Kind` is one of:
   * `orifice` (Size = diameter);
   * `weir` (Size = crest length);
   * `vnotch` (Size = angle in degrees, Top_ft = top of the notch);
   * `overflow` (spillway crest length);
   * `barrel` (diameter, invert);
   * `pool` (design normal pool, or the outlet flowline of a dry basin whose
     lidar bottom is higher).

   Elevations are in the plan datum; check them against the lidar. Good Ranch
   matched within about 0.4 ft; the 2002 Silver Lake survey ran about 0.5 ft
   below the lidar.
3. Re-run the scripts below, then compute HMS:

   ```bash
   python scripts/14_detention_inventory.py
   python scripts/07_build_hms_project.py
   ```

   If a basin's modelled / not-modelled status changes, also run `04` and `05`
   between `14` and `07`, then `14` again to refresh the subbasin tags.

Plan sets covering the modelled basins (largest storage first):

| Basin | Storage at spill | Drainage area | As-built plan set | Outlet |
|---|---:|---:|---|---|
| DET006 | 27.9 ac-ft | 48 ac | Good Ranch – Storm Water Detention Plans for S Dean Ave | **entered** |
| DET011 | 9.5 | 38 | Raymore Galleria Phase 1 | **entered** |
| DET032 | 7.4 | 5.6 | Foxwood Plaza at the Legends | assumed (file is a water-main plan) |
| DET021 | 6.0 | 46 | Lemor Estates Phase 1 | **entered** |
| DET012 | 3.2 | 5 | Matlock Johnson (Walmart) | assumed (outlet not detailed) |
| DET060 | 3.1 | 13 | Foxwood Plaza at the Legends | assumed (file is a water-main plan) |
| DET050 | 1.5 | 10 | Municipal Complex Phase 1 | read; lidar rim below plan spillway (above) |
| DET044 | 1.2 | 14 | Centerview Phase II / Town Center Ph 1, 4 | assumed |
| DET030 | 0.6 | 54 | Shadowood Phase 1 | assumed |
| DET061 | 0.6 | 4 | Centerview Phase II / Municipal Complex Ph 1 | read; lidar rim below plan spillway (above) |
| DET072 | 0.4 | 19 | The Prairie View of the Good Ranch | assumed |
| DET053 | 0.3 | 5 | Silver Lake (1986) | assumed |

The other 14 modelled basins have no plan set in the library. Most are wet
ponds: DET003, 007, 008, 016, 017, 023, 025, 027, 031, 033, 049, 051, 068
and 078.

## Known limitations

* The 65 unmodelled polygons are mostly shallow. A few may have real storage
  that the lidar misses (below a water surface, or a closed-pipe outlet with
  an underground vault).
* Spills come from the lidar (rings out to 30 ft, storage within 60 ft). Where
  a pond was regraded after its plans (e.g. DET050, DET061), the lidar rim is
  used, not the plan spillway.
* **Pipe branches that end in a pond.** A branch whose last pipe ends inside
  a basin may discharge into it, or may be the pond's outlet pipe. The city
  layer cannot tell which: digitizing direction is only 69 % reliable, and
  end sections sit at both kinds of pipe end. These branches keep their
  inlet-capture outfall. Check these on the plans or in the field:

  | Basin | City system | Inlets | Outfall distance |
  |---|---:|---:|---:|
  | DET012 | 79 | 33 | 425 ft |
  | DET030 | 68 | 8 | 680 ft |
  | DET031 / DET032 | 46 | 35 | 1.9 / 1.1 k ft |
  | DET049 | 320 | 21 | 697 ft |
  | DET050 | 43 | 15 | 1,130 ft |

  If a branch does discharge into the pond, its inlets bypass the pond in the
  model, so the pond's drainage area (and its attenuation) is understated.
* There is no tailwater: outlets discharge freely. The barrel is an orifice,
  with no friction or outlet control; at DET006 that puts the 100-yr release
  7 % above the design value.
* DET006's drainage area may be low (see above).
* Short reaches from a basin outlet to the next junction (e.g. R-DET021, 91 ft
  over the embankment) get odd trapezoid fits. They pass flow essentially
  unchanged.
* HMS warns that the smallest detention subbasin has a lag under
  0.29 × the 1-min step (SB-DET012).
