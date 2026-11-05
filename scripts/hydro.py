"""Small numba D8 toolkit used by the delineation / parameter scripts.

Direction encoding (ESRI / pysheds): 1=E 2=SE 4=S 8=SW 16=W 32=NW 64=N 128=NE.
All arrays are 2D row-major; 'flat index' = r * ncols + c.
"""
import numpy as np
from numba import njit

CODES = np.array([1, 2, 4, 8, 16, 32, 64, 128], dtype=np.int64)
DR = np.array([0, 1, 1, 1, 0, -1, -1, -1], dtype=np.int64)
DC = np.array([1, 1, 0, -1, -1, -1, 0, 1], dtype=np.int64)
DIST = np.array([1, np.sqrt(2), 1, np.sqrt(2), 1, np.sqrt(2), 1, np.sqrt(2)])


@njit(cache=True)
def downstream_index(fdir):
    nr, nc = fdir.shape
    down = np.full(nr * nc, -1, dtype=np.int64)
    step = np.zeros(nr * nc, dtype=np.float64)
    for r in range(nr):
        for c in range(nc):
            d = fdir[r, c]
            for k in range(8):
                if d == CODES[k]:
                    rr, cc = r + DR[k], c + DC[k]
                    if 0 <= rr < nr and 0 <= cc < nc:
                        down[r * nc + c] = rr * nc + cc
                        step[r * nc + c] = DIST[k]
                    break
    return down, step


@njit(cache=True)
def topo_order(down):
    """Order cells so every cell comes before its downstream cell."""
    n = down.size
    indeg = np.zeros(n, dtype=np.int64)
    for i in range(n):
        if down[i] >= 0:
            indeg[down[i]] += 1
    order = np.empty(n, dtype=np.int64)
    stack = np.empty(n, dtype=np.int64)
    sp = 0
    for i in range(n):
        if indeg[i] == 0:
            stack[sp] = i
            sp += 1
    k = 0
    while sp > 0:
        sp -= 1
        i = stack[sp]
        order[k] = i
        k += 1
        d = down[i]
        if d >= 0:
            indeg[d] -= 1
            if indeg[d] == 0:
                stack[sp] = d
                sp += 1
    return order[:k]


@njit(cache=True)
def label_basins(down, order, outlet_label):
    """outlet_label: flat int array, >0 at outlet cells, 0 elsewhere.
    Returns flat label array; a cell inherits the label of the first outlet
    found walking downstream (its own if it is an outlet)."""
    n = down.size
    lab = np.zeros(n, dtype=np.int64)
    # walk from downstream to upstream: reverse topological order
    for k in range(order.size - 1, -1, -1):
        i = order[k]
        if outlet_label[i] > 0:
            lab[i] = outlet_label[i]
        elif down[i] >= 0:
            lab[i] = lab[down[i]]
    return lab


@njit(cache=True)
def upstream_length(down, step, order, cellsize, valid):
    """Longest flow distance from the divide to each cell (ft)."""
    n = down.size
    up = np.zeros(n)
    for k in range(order.size):
        i = order[k]
        if not valid[i]:
            continue
        d = down[i]
        if d >= 0 and valid[d]:
            L = up[i] + step[i] * cellsize
            if L > up[d]:
                up[d] = L
    return up


@njit(cache=True)
def longest_path_from(outlet, down, step, uplen, lab, nr, nc, cellsize, maxn):
    """Trace the longest flow path upstream from outlet within its label.
    Returns flat indices from the divide down to the outlet."""
    path = np.empty(maxn, dtype=np.int64)
    m = 0
    cur = outlet
    target = lab[outlet]
    while True:
        path[m] = cur
        m += 1
        if m >= maxn:
            break
        r, c = cur // nc, cur % nc
        best = -1
        bestv = -1.0
        for k in range(8):
            rr, cc = r - DR[k], c - DC[k]   # neighbor that would flow INTO cur
            if 0 <= rr < nr and 0 <= cc < nc:
                j = rr * nc + cc
                if down[j] == cur and lab[j] == target:
                    v = uplen[j] + step[j] * cellsize
                    if v > bestv:
                        bestv = v
                        best = j
        if best < 0:
            break
        cur = best
    return path[:m][::-1]


@njit(cache=True)
def trace_down(start, down, stop_mask, maxn):
    path = np.empty(maxn, dtype=np.int64)
    m = 0
    cur = start
    while cur >= 0 and m < maxn:
        path[m] = cur
        m += 1
        if stop_mask[cur]:
            break
        cur = down[cur]
    return path[:m]


@njit(cache=True)
def upstream_length_lab(down, step, order, cellsize, lab):
    """Longest flow distance from the divide, restricted to cells of the same
    label (so each subbasin's longest flow path starts at its own divide)."""
    n = down.size
    up = np.zeros(n)
    for k in range(order.size):
        i = order[k]
        if lab[i] <= 0:
            continue
        d = down[i]
        if d >= 0 and lab[d] == lab[i]:
            L = up[i] + step[i] * cellsize
            if L > up[d]:
                up[d] = L
    return up


@njit(cache=True)
def on_downstream_path(start, target, down, maxn):
    """True if `target` lies on the D8 path downstream of `start`."""
    cur = start
    for _ in range(maxn):
        if cur == target:
            return True
        cur = down[cur]
        if cur < 0:
            return False
    return False


# ---------------------------------------------------------------------------
# Storm-sewer links: a link sends an inlet cell's flow to a (non-adjacent)
# outfall cell.  `down` stays a single-successor graph, so labelling and
# ordering work unchanged; only neighbour-based upstream searches need the
# CSR helpers below.
def apply_links(down, step, links_ic, links_oc, cellsize, nc):
    """Return (down2, step2) with inlet cells redirected to outfall cells.
    step2 of a link = straight-line inlet->outfall distance in cell units."""
    down2 = down.copy()
    step2 = step.copy()
    for ic, oc in zip(links_ic, links_oc):
        down2[ic] = oc
        r1, c1 = divmod(int(ic), nc)
        r2, c2 = divmod(int(oc), nc)
        step2[ic] = np.hypot(r1 - r2, c1 - c2)
    return down2, step2


@njit(cache=True)
def accumulate(down, order):
    """Number of cells draining through each cell (including itself)."""
    acc = np.ones(down.size)
    for k in range(order.size):
        i = order[k]
        d = down[i]
        if d >= 0:
            acc[d] += acc[i]
    return acc


@njit(cache=True)
def upstream_csr(down):
    n = down.size
    cnt = np.zeros(n + 1, dtype=np.int64)
    for i in range(n):
        if down[i] >= 0:
            cnt[down[i] + 1] += 1
    for i in range(n):
        cnt[i + 1] += cnt[i]
    idx = np.empty(cnt[n], dtype=np.int64)
    fill = cnt[:-1].copy()
    for i in range(n):
        d = down[i]
        if d >= 0:
            idx[fill[d]] = i
            fill[d] += 1
    return cnt, idx


@njit(cache=True)
def longest_path_csr(outlet, ptr, idx, step, uplen, lab, cellsize, maxn):
    """Longest flow path upstream from `outlet` within its label, following
    any upstream cell (including storm-sewer link inlets)."""
    path = np.empty(maxn, dtype=np.int64)
    m = 0
    cur = outlet
    target = lab[outlet]
    while m < maxn:
        path[m] = cur
        m += 1
        best = -1
        bestv = -1.0
        for k in range(ptr[cur], ptr[cur + 1]):
            j = idx[k]
            if lab[j] == target:
                v = uplen[j] + step[j] * cellsize
                if v > bestv:
                    bestv = v
                    best = j
        if best < 0:
            break
        cur = best
    return path[:m][::-1]
