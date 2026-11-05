"""Storm-sewer inlet-capture links for the D8 flow graph (shared by 02b, 04, 05, 13).

Surface flow follows the terrain (D8 on the culvert-burned 10 ft DEM).  City
storm sewer (scripts/12, GIS/Raymore_StormGIS.gpkg) is added by inlet capture:
every inlet structure (curb inlet, field inlet, catch basin, gutter inlet, pipe
drain, and inflow end sections) is snapped to the gutter / flow line beside it
and its D8 link is redirected to the outfall of its pipe system, so runoff that
reaches an inlet leaves through the pipe outfall, even across a terrain divide.

Rules (each one fixed an artefact found during review, see docs/StormSewer_Delineation.md)
  * pipe systems: pipe endpoints snapped within 5 ft; the outfall of a system
    is its lowest leaf node (DEM within 15 ft), OUTFALL / end-section
    structures preferred by 3 ft.  Checked against city inverts: 39 of the 43
    systems that move >= 5 ac have inverts falling toward the chosen outfall.
  * an inlet is snapped to the highest-accumulation cell within 15 ft that
    drains <= 10 ac (street / field inlets) or <= 40 ac (inflow end sections),
    so an inlet beside a creek does not capture the creek.
  * links whose outfall already lies on the inlet's terrain flow path (road
    culverts, sewers that follow the natural drainage) are dropped: they move
    no area, and would otherwise make flow skip an HMS junction at a crossing.
  * links that would create a cycle are dropped.
This is "full capture" (the sewershed); flow above pipe capacity stays on the
surface in reality.
"""
from pathlib import Path
import sys
import numpy as np
import pandas as pd
import geopandas as gpd
import networkx as nx
from scipy.spatial import cKDTree
from shapely.geometry import Point
from shapely.strtree import STRtree

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hydro  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
STORM = ROOT / "GIS/Raymore_StormGIS.gpkg"
LINKS_CSV = ROOT / "HMS/parameters/sewer_links.csv"
SNAP_NODE_FT = 5.0
INLET_TO_SYSTEM_FT = 15.0
INLET_SNAP_FT = 15.0
OUTFALL_SNAP_FT = 25.0
CAPTURE_TYPES = {"CI", "FI", "CB", "GUTTER", "PD", "ES", "FES"}
MAX_CAPTURE_AC = {"CI": 10.0, "FI": 10.0, "CB": 10.0, "GUTTER": 10.0, "PD": 10.0, "ES": 40.0, "FES": 40.0}
OUTLET_TYPES = {"OUTFALL", "ES", "FES"}


def pipe_network():
    """City storm pipes as a graph: pipe endpoints snapped within SNAP_NODE_FT.
    Returns (P, G, xy): exploded pipes, MultiGraph (edge attr pipe, length) and
    node -> (x, y).  System k = k-th connected component of G (as in build_links)."""
    P = gpd.read_file(STORM, layer="pipes").explode(index_parts=False).reset_index(drop=True)
    n = len(P)
    ends = np.array([l.coords[0][:2] for l in P.geometry] + [l.coords[-1][:2] for l in P.geometry])
    G0 = nx.Graph()
    G0.add_nodes_from(range(2 * n))
    G0.add_edges_from(cKDTree(ends).query_pairs(SNAP_NODE_FT))
    node_of = {}
    for k, comp in enumerate(nx.connected_components(G0)):
        for i in comp:
            node_of[i] = k
    xy = {}
    for i, k in node_of.items():
        xy.setdefault(k, ends[i])
    G = nx.MultiGraph()
    for i in range(n):
        G.add_edge(node_of[i], node_of[i + n], pipe=i, length=P.geometry[i].length)
    return P, G, xy


def build_links(F, A, Z, tr, crs):
    """F: D8 codes (2D), A: terrain accumulation (flat), Z: 10 ft DEM (2D).
    Returns (systems GeoDataFrame, links DataFrame[ic, oc, System, InletType, x, y])."""
    nr, nc = F.shape
    cs = tr.a
    ac = cs * cs / 43560.0
    down, _ = hydro.downstream_index(F)

    def max_acc_cell(x, y, rad, cap_ac=None):
        c0, r0 = ~tr * (x, y)
        n = int(np.ceil(rad / cs))
        best, bv = -1, -1.0
        cap = np.inf if cap_ac is None else cap_ac / ac
        for r in range(int(r0) - n, int(r0) + n + 1):
            for c in range(int(c0) - n, int(c0) + n + 1):
                if 0 <= r < nr and 0 <= c < nc and ((c + 0.5 - c0) ** 2 + (r + 0.5 - r0) ** 2) * cs * cs <= rad * rad:
                    i = r * nc + c
                    if bv < A[i] <= cap:
                        best, bv = i, A[i]
        return best

    def zmin_near(x, y, rad=15.0):
        c0, r0 = ~tr * (x, y)
        n = int(np.ceil(rad / cs))
        w = Z[max(0, int(r0) - n):int(r0) + n + 1, max(0, int(c0) - n):int(c0) + n + 1]
        w = w[w > -9000]
        return float(w.min()) if w.size else np.inf

    P, G, xy = pipe_network()
    I = gpd.read_file(STORM, layer="inlets").reset_index(drop=True)
    st_out = STRtree(list(I[I.TYPE.isin(OUTLET_TYPES)].geometry))

    sys_rows, comp_of_pipe, outlet_of_comp = [], {}, {}
    for k, comp in enumerate(nx.connected_components(G)):
        sub = G.subgraph(comp)
        leaves = [nd for nd in comp if G.degree(nd) == 1] or list(comp)
        score = {nd: zmin_near(*xy[nd]) - (3.0 if len(st_out.query(Point(xy[nd]).buffer(15))) else 0.0)
                 for nd in leaves}
        o = min(score, key=score.get)
        outlet_of_comp[k] = o
        for _, _, d in sub.edges(data=True):
            comp_of_pipe[d["pipe"]] = k
        sys_rows.append(dict(System=k, Pipes=sub.number_of_edges(),
                             Length_ft=sum(d["length"] for *_, d in sub.edges(data=True)),
                             Outfall_x=xy[o][0], Outfall_y=xy[o][1], geometry=Point(xy[o])))
    systems = gpd.GeoDataFrame(sys_rows, crs=crs)
    out_cell = {k: max_acc_cell(*xy[o], OUTFALL_SNAP_FT) for k, o in outlet_of_comp.items()}

    st_pipe = STRtree(list(P.geometry))
    cand_links, n_inline = [], 0
    for _, r in I[I.TYPE.isin(CAPTURE_TYPES)].iterrows():
        pt = r.geometry
        cand = st_pipe.query(pt.buffer(INLET_TO_SYSTEM_FT))
        if len(cand) == 0:
            continue
        k = comp_of_pipe[min(cand, key=lambda j: P.geometry[j].distance(pt))]
        o = outlet_of_comp[k]
        if Point(xy[o]).distance(pt) < 40:          # this structure is the outfall
            continue
        ic = max_acc_cell(pt.x, pt.y, INLET_SNAP_FT, MAX_CAPTURE_AC[r.TYPE])
        oc = out_cell[k]
        if ic < 0 or oc < 0 or ic == oc:
            continue
        if hydro.on_downstream_path(ic, oc, down, 200000):
            n_inline += 1
            continue
        cand_links.append((ic, oc, k, r.TYPE, pt.x, pt.y))

    # one link per inlet cell (first wins), then drop links that close a cycle
    seen, kept = set(), []
    for L in cand_links:
        if L[0] not in seen:
            seen.add(L[0])
            kept.append(L)
    down2 = down.copy()
    for ic, oc, *_ in kept:
        down2[ic] = oc
    for _ in range(20):
        order = hydro.topo_order(down2)
        if order.size == down2.size:
            break
        inorder = np.zeros(down2.size, bool)
        inorder[order] = True
        bad = {L[0] for L in kept if not inorder[L[0]]}
        for ic in bad:
            down2[ic] = down[ic]
        kept = [L for L in kept if L[0] not in bad]
    links = pd.DataFrame(kept, columns=["ic", "oc", "System", "InletType", "x", "y"])
    links.attrs["n_inline"] = n_inline
    links.attrs["n_candidates"] = len(cand_links)
    return systems, links


def load_links():
    """(ic, oc) arrays from HMS/parameters/sewer_links.csv, or empty arrays."""
    if not LINKS_CSV.exists():
        return np.zeros(0, np.int64), np.zeros(0, np.int64)
    d = pd.read_csv(LINKS_CSV)
    return d.ic.to_numpy(np.int64), d.oc.to_numpy(np.int64)


DET_LINKS_CSV = ROOT / "HMS/parameters/detention_links.csv"


def load_detention_links():
    """(ic, oc) arrays from HMS/parameters/detention_links.csv (scripts/14):
    cells of a modelled detention basin whose D8 flow leaves the footprint
    are sent to the basin outlet, so everything entering a pond passes its outlet."""
    if not DET_LINKS_CSV.exists():
        return np.zeros(0, np.int64), np.zeros(0, np.int64)
    d = pd.read_csv(DET_LINKS_CSV)
    return d.ic.to_numpy(np.int64), d.oc.to_numpy(np.int64)


def flow_graph(F, cellsize, use_sewer=True, use_detention=False):
    """down, step (cell units), order and accumulation for the terrain graph
    with (optionally) the storm-sewer links and detention-capture links applied."""
    nr, nc = F.shape
    down, step = hydro.downstream_index(F)
    if use_sewer:
        ic, oc = load_links()
        if ic.size:
            down, step = hydro.apply_links(down, step, ic, oc, cellsize, nc)
    if use_detention:
        ic, oc = load_detention_links()
        if ic.size:
            down, step = hydro.apply_links(down, step, ic, oc, cellsize, nc)
    order = hydro.topo_order(down)
    assert order.size == down.size, "flow graph has a cycle"
    acc = hydro.accumulate(down, order)
    return down, step, order, acc
