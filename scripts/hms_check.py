"""Independent Python re-implementation of the HMS methods used in the
Raymore model, for QA/QC of the HEC-HMS project (and so results exist
before HMS is run).  It is NOT HEC-HMS: expect peaks within a few percent of
HMS, not identical values (HMS's automatic Muskingum-Cunge sub-stepping and
UH interpolation differ in detail).

Methods
  * SCS Curve Number loss, Ia = 0.2 S, impervious area -> 100 % runoff
  * SCS (NRCS) dimensionless unit hydrograph, PRF 484, Tp = dt/2 + lag
  * Muskingum-Cunge, trapezoid, constant parameters from the index flow,
    dx/dt per Ponce (automatic)
  * Modified Puls level-pool routing (storage-outflow table) for lakes
"""
import numpy as np

# NRCS NEH 630 ch.16 Table 16-1 dimensionless unit hydrograph (t/Tp, q/qp)
_UH_T = np.array([0.0, .1, .2, .3, .4, .5, .6, .7, .8, .9, 1.0, 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9,
                  2.0, 2.2, 2.4, 2.6, 2.8, 3.0, 3.2, 3.4, 3.6, 3.8, 4.0, 4.5, 5.0])
_UH_Q = np.array([0.0, .030, .100, .190, .310, .470, .660, .820, .930, .990, 1.000, .990, .930, .860, .780,
                  .680, .560, .460, .390, .330, .280, .207, .147, .107, .077, .055, .040, .029, .021, .015,
                  .011, .005, 0.0])


def scs_excess(p_inc, cn, imperv_pct, ia_ratio=0.2):
    """Incremental excess (in) from incremental precipitation (in)."""
    S = 1000.0 / cn - 10.0
    Ia = ia_ratio * S
    P = np.cumsum(p_inc)
    Pe = np.where(P > Ia, (P - Ia) ** 2 / (P - Ia + S), 0.0)
    pe_inc = np.diff(np.concatenate([[0.0], Pe]))
    f = imperv_pct / 100.0
    return (1.0 - f) * pe_inc + f * p_inc


def scs_uh(area_sqmi, lag_min, dt_min):
    """Unit hydrograph ordinates (cfs per inch of excess per dt)."""
    tp_hr = (dt_min / 2.0 + lag_min) / 60.0
    t_end = 5.0 * tp_hr
    # volume-consistent: difference the dimensionless mass curve at dt
    tt = np.linspace(0, 5.0, 2001)
    qq = np.interp(tt, _UH_T, _UH_Q)
    mass = np.concatenate([[0.0], np.cumsum((qq[1:] + qq[:-1]) / 2 * np.diff(tt))])
    mass /= mass[-1]
    n = int(np.ceil(t_end * 60.0 / dt_min)) + 1
    tk = np.arange(n + 1) * dt_min / 60.0 / tp_hr
    m = np.interp(tk, tt, mass, right=1.0)
    frac = np.diff(m)                       # fraction of unit volume in each dt
    vol_cf = area_sqmi * 27878400.0 / 12.0  # 1 inch over the area, ft^3
    return frac * vol_cf / (dt_min * 60.0)


def subbasin_hydrograph(p_inc, area_sqmi, cn, imperv, lag_min, dt_min):
    ex = scs_excess(p_inc, cn, imperv)
    uh = scs_uh(area_sqmi, lag_min, dt_min)
    return np.convolve(ex, uh)[: len(p_inc)]


def _trap(y, b, z):
    A = (b + z * y) * y
    P = b + 2 * y * np.sqrt(1 + z * z)
    T = b + 2 * z * y
    return A, P, T


def _manning_q(y, b, z, n, s):
    A, P, _ = _trap(y, b, z)
    return 1.486 / n * A * (A / P) ** (2.0 / 3.0) * np.sqrt(s)


def normal_depth(q, b, z, n, s):
    lo, hi = 1e-4, 100.0
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        if _manning_q(mid, b, z, n, s) < q:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def mc_parameters(L, s, n, b, z, q_index, dt_min):
    y = normal_depth(q_index, b, z, n, s)
    dy = max(1e-3, 0.01 * y)
    c = (_manning_q(y + dy, b, z, n, s) - _manning_q(y - dy, b, z, n, s)) / (
        _trap(y + dy, b, z)[0] - _trap(y - dy, b, z)[0])
    T = _trap(y, b, z)[2]
    dt = dt_min * 60.0
    dx_max = 0.5 * (c * dt + q_index / (T * s * c))
    nsub = max(1, int(np.ceil(L / dx_max)))
    dx = L / nsub
    K = dx / c
    X = float(np.clip(0.5 * (1.0 - q_index / (T * s * c * dx)), 0.0, 0.5))
    return dict(celerity=c, depth=y, top_width=T, nsub=nsub, dx=dx, K_s=K, X=X)


def muskingum_cunge(inflow, L, s, n, b, z, q_index, dt_min):
    p = mc_parameters(L, s, n, b, z, q_index, dt_min)
    dt = dt_min * 60.0
    K, X = p["K_s"], p["X"]
    D = K * (1 - X) + dt / 2
    c0 = (dt / 2 - K * X) / D
    c1 = (dt / 2 + K * X) / D
    c2 = (K * (1 - X) - dt / 2) / D
    q = np.asarray(inflow, float)
    for _ in range(p["nsub"]):
        out = np.empty_like(q)
        out[0] = q[0]
        for t in range(1, len(q)):
            out[t] = max(c0 * q[t] + c1 * q[t - 1] + c2 * out[t - 1], 0.0)
        q = out
    return q, p


def modified_puls(inflow, storage_acft, outflow_cfs, dt_min):
    S = np.asarray(storage_acft, float) * 43560.0
    O = np.asarray(outflow_cfs, float)
    dt = dt_min * 60.0
    ind = 2 * S / dt + O
    out = np.zeros(len(inflow))
    sto = np.zeros(len(inflow))
    o_prev, s_prev = 0.0, 0.0
    for t in range(1, len(inflow)):
        rhs = inflow[t - 1] + inflow[t] + (2 * s_prev / dt - o_prev)
        o = float(np.interp(rhs, ind, O))
        s_ = (rhs - o) * dt / 2
        out[t], sto[t] = o, s_
        o_prev, s_prev = o, s_
    return out, sto / 43560.0
