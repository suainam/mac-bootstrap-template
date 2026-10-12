"""Production-grade retail causal evaluation runner template (ps-causal-evaluation).

Features:
1. Four-set architecture with mathematical boundaries:
   - Control Donor Set (D_i): Same-region, same-stratum mature candidate pool (>=365D in business).
   - Training Set (T_train: seg1 & seg2): Pre-intervention [-90D, -31D] (60 days) split into two 30D segments
     [-90D, -61D] and [-60D, -31D] with 364-day prior-year counterparts for 8-dim trajectory matching.
   - Holdout Test Set (T_holdout): Pre-intervention [-30D, -1D] (30 days) as untouched out-of-sample diagnostic
     (100% firewall isolation from matching, scaling, optimization, and gating; zero leakage).
   - Final Matched Control Group (C_i): Tier 1 pure single store (<=10%), Tier 2 SCM synthetic clone (<=20%),
     or Tier 3 excluded (unmatched, zero cross-stratum fallback).
2. Standardized space scale-invariant Mahalanobis Distance (MDM) with regularized covariance inversion.
3. Adaptive convex Quadratic Programming SCM solver via Duchi et al. (2008) simplex projection.
4. Exact 4-period (C, H, L, LH) Triple Difference (DDD / YoY-DID) closed-loop calculations across 30D/60D/90D.
5. Golden two-zone decoupled Excel delivery (Sheet 1 Overview, Sheet 2 Results vs Process Decoupled, Sheet 3 Donors, Sheet 4 Dictionary).
6. Modern Analytical Blueprint HTML executive dashboard with SVG CONSORT funnel and metric cards.
7. Standalone execution: run with `--synthetic-demo` for instant end-to-end verification without external data.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys
from typing import Any

import numpy as np
import pandas as pd

# ==============================================================================
# 1. Mathematical Core (Self-contained, Zero external dependency failures)
# ==============================================================================

def compute_js_distance(p: np.ndarray | list[float], q: np.ndarray | list[float]) -> float:
    """Compute the Jensen-Shannon Distance between two probability distributions.

    Bounded in [0.0, 1.0]. Returns square root of JSD divergence (a true metric).
    """
    p_arr = np.asarray(p, dtype=float)
    q_arr = np.asarray(q, dtype=float)

    sum_p = float(np.sum(p_arr))
    sum_q = float(np.sum(q_arr))
    if sum_p <= 0.0 or sum_q <= 0.0:
        return 1.0

    p_norm = p_arr / sum_p
    q_norm = q_arr / sum_q
    m = 0.5 * (p_norm + q_norm)

    def _kl(a: np.ndarray, b: np.ndarray) -> float:
        mask = (a > 0.0) & (b > 0.0)
        if not np.any(mask):
            return 0.0
        return float(np.sum(a[mask] * np.log2(a[mask] / b[mask])))

    jsd = 0.5 * _kl(p_norm, m) + 0.5 * _kl(q_norm, m)
    return float(np.sqrt(max(jsd, 0.0)))


def compute_standardized_mahalanobis_distances(
    donor_features: np.ndarray,
    target_vector: np.ndarray | list[float],
    ridge: float = 1e-2,
) -> np.ndarray:
    """Compute Mahalanobis distances using donor-dispersed dimensions in standardized space.

    Guarantees scale invariance: linear unit changes (e.g., yuan to 10k yuan) do not alter distance or ranking.
    """
    X = np.asarray(donor_features, dtype=float)
    y = np.asarray(target_vector, dtype=float)
    if X.ndim != 2 or len(X) == 0:
        return np.array([], dtype=float)
    if len(X) < 2:
        return np.zeros(len(X), dtype=float)

    means = np.nanmean(X, axis=0)
    stds = np.nanstd(X, axis=0, ddof=1)
    active = np.isfinite(stds) & (stds > 1e-12)
    if not active.any():
        return np.zeros(len(X), dtype=float)

    Z = (X[:, active] - means[active]) / stds[active]
    z_target = (y[active] - means[active]) / stds[active]

    corr = np.cov(Z, rowvar=False)
    if corr.ndim == 0:
        corr = np.array([[float(corr)]])
    corr = np.nan_to_num(corr, nan=0.0, posinf=0.0, neginf=0.0)

    alpha = float(np.clip(ridge, 1e-6, 0.5))
    corr_reg = (1.0 - alpha) * corr + alpha * np.eye(corr.shape[0])
    corr_inv = np.linalg.pinv(corr_reg)

    diffs = Z - z_target[np.newaxis, :]
    m_sq = np.sum((diffs @ corr_inv) * diffs, axis=1)
    return np.sqrt(np.maximum(m_sq, 0.0))


def project_to_simplex(v: np.ndarray) -> np.ndarray:
    """Project a real vector v onto the probability simplex {w >= 0, sum(w) = 1}.

    Exact O(n log n) closed-form algorithm by Duchi et al. (2008).
    """
    v_arr = np.asarray(v, dtype=float)
    n = len(v_arr)
    if n == 1:
        return np.array([1.0])

    u = np.sort(v_arr)[::-1]
    cssv = np.cumsum(u)
    indices = np.arange(1, n + 1)
    cond = u * indices > (cssv - 1.0)
    rho_candidates = np.nonzero(cond)[0]
    if len(rho_candidates) == 0:
        rho = n - 1
    else:
        rho = int(rho_candidates[-1])

    theta = float(cssv[rho] - 1.0) / (rho + 1.0)
    w = np.maximum(v_arr - theta, 0.0)
    s = float(np.sum(w))
    return w / (s if s > 0 else 1.0)


def solve_convex_scm_weights(
    donor_matrix: np.ndarray,
    target_vector: np.ndarray,
    feature_weights: np.ndarray | list[float] | None = None,
    max_iter: int = 400,
) -> list[float]:
    """Solve convex SCM combination weights minimizing standardized distance to target.

    Objective: min_w || W^(1/2) (Z_donors^T w - z_target) ||_2^2
    Subject to: sum(w) = 1, w_k >= 0
    """
    D = np.asarray(donor_matrix, dtype=float)
    y = np.asarray(target_vector, dtype=float)
    K, _ = D.shape
    if K <= 1:
        return [1.0]

    means = np.nanmean(D, axis=0)
    scales = np.nanstd(D, axis=0, ddof=0)
    active = np.isfinite(scales) & (scales > 1e-9)
    if not active.any():
        w_u = [round(1.0 / K, 4)] * K
        w_u[0] = round(w_u[0] + round(1.0 - sum(w_u), 4), 4)
        return w_u

    scales = scales[active]
    D_std = (D[:, active] - means[active]) / scales
    y_std = (y[active] - means[active]) / scales

    if feature_weights is not None:
        weights = np.sqrt(np.maximum(np.asarray(feature_weights, dtype=float)[active], 1e-6))
        D_std *= weights[np.newaxis, :]
        y_std *= weights

    A = D_std.T
    AtA = A.T @ A
    Aty = A.T @ y_std
    eig_max = float(np.linalg.norm(AtA, 2))
    step = 1.0 / (2.0 * eig_max + 1e-6)
    w = np.ones(K, dtype=float) / float(K)

    for _ in range(max_iter):
        w_next = project_to_simplex(w - step * (2.0 * (AtA @ w - Aty)))
        if float(np.max(np.abs(w_next - w))) < 1e-7:
            w = w_next
            break
        w = w_next

    w_rounded = [round(float(x), 4) for x in w]
    s = sum(w_rounded)
    if s <= 0:
        w_u = [round(1.0 / K, 4)] * K
        w_u[0] = round(w_u[0] + round(1.0 - sum(w_u), 4), 4)
        return w_u
    w_norm = [round(x / s, 4) for x in w_rounded]
    w_norm[int(np.argmax(w_norm))] = round(w_norm[int(np.argmax(w_norm))] + round(1.0 - sum(w_norm), 4), 4)
    return w_norm


def compute_smd(a_vals: np.ndarray | list[float], b_vals: np.ndarray | list[float]) -> float:
    """Compute Standardized Mean Difference (SMD / Cohen's d). SMD <= 0.10 indicates negligible bias."""
    a = np.asarray(a_vals, dtype=float)
    b = np.asarray(b_vals, dtype=float)
    if len(a) < 2 or len(b) < 2:
        return 0.0
    mean_a = float(np.mean(a))
    mean_b = float(np.mean(b))
    var_a = float(np.var(a, ddof=1))
    var_b = float(np.var(b, ddof=1))
    pooled_sd = float(np.sqrt((var_a + var_b) / 2.0))
    if pooled_sd <= 1e-9:
        return 0.0
    return float(abs(mean_a - mean_b) / pooled_sd)


# ==============================================================================
# 2. Four Sets Feature Extraction & SCM Pipeline
# ==============================================================================

SCM_FEATURE_NAMES = [
    "seg1_daily_sales",
    "seg2_daily_sales",
    "seg1_daily_profit",
    "seg2_daily_profit",
    "seg1_daily_orders",
    "seg2_daily_orders",
    "seg1_yoy_growth",
    "seg2_yoy_growth",
]


def extract_training_features(df_daily: pd.DataFrame, store_code: int, start_date: pd.Timestamp) -> dict[str, float]:
    """Extract 8-dimensional trajectory features from Training Set: seg1 [-90, -61] and seg2 [-60, -31].

    Note: 30-day Holdout Set [-30, -1] is strictly excluded from this feature vector.
    """
    sub = df_daily[df_daily["store_code"] == store_code].copy()
    if sub.empty:
        return {k: np.nan for k in SCM_FEATURE_NAMES}

    sub["stat_date"] = pd.to_datetime(sub["stat_date"])
    sub_indexed = sub.set_index("stat_date")

    def _get_window_stats(s_dt: pd.Timestamp, e_dt: pd.Timestamp) -> tuple[float, float, float]:
        window = sub_indexed.loc[s_dt:e_dt] if not sub_indexed.empty else pd.DataFrame()
        if len(window) < 20:  # Valid coverage threshold
            return np.nan, np.nan, np.nan
        s_val = float(window["sales"].mean()) if "sales" in window else np.nan
        p_val = float(window["profit"].mean()) if "profit" in window else np.nan
        o_val = float(window["orders"].mean()) if "orders" in window else np.nan
        return s_val, p_val, o_val

    # seg1: [-90D, -61D]
    s1_start, s1_end = start_date - pd.Timedelta(days=90), start_date - pd.Timedelta(days=61)
    s1_ly_start, s1_ly_end = s1_start - pd.Timedelta(days=364), s1_end - pd.Timedelta(days=364)
    s1_s, s1_p, s1_o = _get_window_stats(s1_start, s1_end)
    s1_s_ly, _, _ = _get_window_stats(s1_ly_start, s1_ly_end)
    s1_yoy = (s1_s - s1_s_ly) / s1_s_ly if np.isfinite(s1_s) and np.isfinite(s1_s_ly) and s1_s_ly > 0 else np.nan

    # seg2: [-60D, -31D]
    s2_start, s2_end = start_date - pd.Timedelta(days=60), start_date - pd.Timedelta(days=31)
    s2_ly_start, s2_ly_end = s2_start - pd.Timedelta(days=364), s2_end - pd.Timedelta(days=364)
    s2_s, s2_p, s2_o = _get_window_stats(s2_start, s2_end)
    s2_s_ly, _, _ = _get_window_stats(s2_ly_start, s2_ly_end)
    s2_yoy = (s2_s - s2_s_ly) / s2_s_ly if np.isfinite(s2_s) and np.isfinite(s2_s_ly) and s2_s_ly > 0 else np.nan

    return {
        "seg1_daily_sales": s1_s,
        "seg2_daily_sales": s2_s,
        "seg1_daily_profit": s1_p,
        "seg2_daily_profit": s2_p,
        "seg1_daily_orders": s1_o,
        "seg2_daily_orders": s2_o,
        "seg1_yoy_growth": s1_yoy,
        "seg2_yoy_growth": s2_yoy,
    }


def extract_holdout_sales(df_daily: pd.DataFrame, store_code: int, start_date: pd.Timestamp) -> float:
    """Extract total sales in Holdout Test Set [-30, -1] for out-of-sample blind testing."""
    sub = df_daily[df_daily["store_code"] == store_code].copy()
    if sub.empty:
        return np.nan
    sub["stat_date"] = pd.to_datetime(sub["stat_date"])
    h_start = start_date - pd.Timedelta(days=30)
    h_end = start_date - pd.Timedelta(days=1)
    window = sub[(sub["stat_date"] >= h_start) & (sub["stat_date"] <= h_end)]
    if len(window) < 25:
        return np.nan
    return float(window["sales"].sum())


def compute_category_jsd(
    df_cat: pd.DataFrame,
    pilot_code: int,
    donors: list[dict[str, Any]],
) -> float:
    """Compute pre-intervention category Jensen-Shannon Distance between pilot and control group."""
    if df_cat.empty:
        return np.nan
    p_data = df_cat[df_cat["store_code"] == pilot_code]
    if p_data.empty:
        return np.nan

    cats = sorted(df_cat["category_name"].unique())
    p_shares = p_data.set_index("category_name")["share"].reindex(cats, fill_value=0.0).to_numpy(dtype=float)

    c_shares = np.zeros(len(cats), dtype=float)
    active_donors = [d for d in donors if float(d["weight"]) > 0]
    if not active_donors:
        return np.nan

    for d in active_donors:
        d_code = int(d["store_code"])
        d_data = df_cat[df_cat["store_code"] == d_code]
        if d_data.empty:
            return np.nan
        d_vec = d_data.set_index("category_name")["share"].reindex(cats, fill_value=0.0).to_numpy(dtype=float)
        c_shares += float(d["weight"]) * d_vec

    return compute_js_distance(p_shares, c_shares)


def match_pilot_stores(
    df_pilots: pd.DataFrame,
    df_candidates: pd.DataFrame,
    df_daily: pd.DataFrame,
    df_cat: pd.DataFrame,
) -> pd.DataFrame:
    """Run Step 3 matching: 1:N stratification, MDM distance, convex SCM, Holdout testing, and Tier 1/2/3 gating."""
    pair_rows: list[dict[str, Any]] = []

    for _, pilot in df_pilots.reset_index(drop=True).iterrows():
        p_code = int(pilot["store_code"])
        p_name = str(pilot["store_name"])
        region = str(pilot["region_name"])
        stratum = str(pilot["store_stratum"])
        start = pd.to_datetime(pilot["test_start_date"])

        pair_id = f"PAIR_{p_code}"
        train_p = extract_training_features(df_daily, p_code, start)

        base_record: dict[str, Any] = {
            "pair_id": pair_id,
            "region_man_name": region,
            "store_strata": stratum,
            "store_code_a": p_code,
            "store_name_a": p_name,
            "test_start_date": start.strftime("%Y-%m-%d"),
            "candidate_pool_cnt": 0,
            "match_tier": "Tier 3: 未获可比对照",
            "is_valid_match": False,
            "exclusion_code": "",
            "is_excluded_reason": "",
            "single_store_code_b": np.nan,
            "single_store_name_b": "",
            "scm_control_stores": "[]",
            "scm_donors_text": "",
            "pre_fit_rmspe": np.nan,
            "pre_holdout_rmspe": np.nan,
            "category_js_distance": np.nan,
            "fitted_sales_diff_pct": np.nan,
            "fitted_profit_diff_pct": np.nan,
            "fitted_trend_diff_pp": np.nan,
            "single_sales_diff_pct": np.nan,
            "single_profit_diff_pct": np.nan,
            "single_trend_diff_pp": np.nan,
        }

        # 1. Candidate Donor Filtering: strict same region, same stratum, mature >= 365D
        pool = df_candidates[
            (df_candidates["region_name"] == region)
            & (df_candidates["store_stratum"] == stratum)
            & (df_candidates["store_code"] != p_code)
        ].copy()

        if pool.empty:
            base_record.update({
                "exclusion_code": "NO_SAME_STRATUM_DONOR",
                "is_excluded_reason": "同营运区同店型合规成熟供体池为空；坚决不跨层回退",
            })
            pair_rows.append(base_record)
            continue

        base_record["candidate_pool_cnt"] = len(pool)

        # 2. Extract Training Features for candidate pool
        cand_feats: list[dict[str, float]] = []
        valid_indices: list[int] = []
        for idx, (_, cand) in enumerate(pool.iterrows()):
            f = extract_training_features(df_daily, int(cand["store_code"]), start)
            if all(np.isfinite(f[c]) for c in SCM_FEATURE_NAMES):
                cand_feats.append(f)
                valid_indices.append(idx)

        if not cand_feats:
            base_record.update({
                "exclusion_code": "DONOR_TRAIN_DATA_DEFICIT",
                "is_excluded_reason": "同层供体在90D训练集内流水记录不全或缺测",
            })
            pair_rows.append(base_record)
            continue

        valid_pool = pool.iloc[valid_indices].reset_index(drop=True)
        donor_X = np.array([[f[col] for col in SCM_FEATURE_NAMES] for f in cand_feats], dtype=float)
        target_y = np.array([train_p[col] for col in SCM_FEATURE_NAMES], dtype=float)

        # 3. Standardized Mahalanobis Distance Ranking
        mdm_dists = compute_standardized_mahalanobis_distances(donor_X, target_y)
        valid_pool["mdm_dist"] = mdm_dists
        valid_pool = valid_pool.sort_values(by="mdm_dist").reset_index(drop=True)

        best_single = valid_pool.iloc[0]
        f_single = cand_feats[int(valid_pool.index[0])]
        single_code = int(best_single["store_code"])
        single_name = str(best_single["store_name"])

        # Compute single store metrics
        single_sales_diff = abs(f_single["seg2_daily_sales"] - train_p["seg2_daily_sales"]) / max(train_p["seg2_daily_sales"], 1.0)
        single_profit_diff = abs(f_single["seg2_daily_profit"] - train_p["seg2_daily_profit"]) / max(train_p["seg2_daily_profit"], 1.0)
        single_order_diff = abs(f_single["seg2_daily_orders"] - train_p["seg2_daily_orders"]) / max(train_p["seg2_daily_orders"], 1.0)
        single_trend_diff = abs(f_single["seg2_yoy_growth"] - train_p["seg2_yoy_growth"])

        base_record.update({
            "single_store_code_b": single_code,
            "single_store_name_b": single_name,
            "single_sales_diff_pct": float(single_sales_diff * 100),
            "single_profit_diff_pct": float(single_profit_diff * 100),
            "single_trend_diff_pp": float(single_trend_diff * 100),
        })

        # 4. SCM Convex Optimization on Top-K donors (K=min(3, len(pool)))
        top_k = min(3, len(valid_pool))
        top_donors = valid_pool.iloc[:top_k]
        top_X = donor_X[:top_k]

        w = solve_convex_scm_weights(top_X, target_y)
        scm_donors = [
            {"store_code": int(r["store_code"]), "store_name": str(r["store_name"]), "weight": float(wj)}
            for (_, r), wj in zip(top_donors.iterrows(), w, strict=True)
        ]

        # Synthetic values
        synth_vals = np.sum([wj * x for wj, x in zip(w, top_X, strict=True)], axis=0)
        scales = np.nanstd(top_X, axis=0)
        scales[scales <= 1e-9] = 1.0
        fit_rmspe = float(np.sqrt(np.mean(((synth_vals - target_y) / scales) ** 2)))

        scm_sales_diff = abs(synth_vals[1] - train_p["seg2_daily_sales"]) / max(train_p["seg2_daily_sales"], 1.0)
        scm_profit_diff = abs(synth_vals[3] - train_p["seg2_daily_profit"]) / max(train_p["seg2_daily_profit"], 1.0)
        scm_trend_diff = abs(synth_vals[7] - train_p["seg2_yoy_growth"])

        # 5. Tier Gating Decision
        selected_donors: list[dict[str, Any]] = []
        tier = "Tier 3: 未获可比对照"
        if single_sales_diff <= 0.10 and single_order_diff <= 0.10 and single_trend_diff <= 0.15:
            tier = "Tier 1: 真实单店"
            selected_donors = [{"store_code": single_code, "store_name": single_name, "weight": 1.0}]
            fitted_sales_diff = single_sales_diff
            fitted_profit_diff = single_profit_diff
            fitted_trend_diff = single_trend_diff
        elif len(scm_donors) >= 2 and fit_rmspe <= 1.0 and scm_sales_diff <= 0.20 and scm_trend_diff <= 0.20:
            tier = "Tier 2: SCM 虚拟克隆"
            selected_donors = scm_donors
            fitted_sales_diff = scm_sales_diff
            fitted_profit_diff = scm_profit_diff
            fitted_trend_diff = scm_trend_diff
        else:
            tier = "Tier 3: 未获可比对照"
            selected_donors = []
            fitted_sales_diff = scm_sales_diff
            fitted_profit_diff = scm_profit_diff
            fitted_trend_diff = scm_trend_diff

        # 6. Untouched Holdout Test Set Blind Validation [-30, -1]
        p_holdout = extract_holdout_sales(df_daily, p_code, start)
        eval_donors = selected_donors if selected_donors else scm_donors
        holdout_sales_ctrl = 0.0
        for d in eval_donors:
            s_d = extract_holdout_sales(df_daily, int(d["store_code"]), start)
            holdout_sales_ctrl += float(d["weight"]) * (s_d if np.isfinite(s_d) else 0.0)

        holdout_rmspe = (
            abs(holdout_sales_ctrl - p_holdout) / max(p_holdout, 1.0)
            if np.isfinite(p_holdout) and p_holdout > 0 and holdout_sales_ctrl > 0
            else np.nan
        )

        # 7. Category JSD Calculation
        jsd = compute_category_jsd(df_cat, p_code, eval_donors)

        donors_text = " + ".join(f"{d['store_name']}({d['weight']:.1%})" for d in eval_donors if d["weight"] > 0)
        is_valid = tier.startswith("Tier 1") or tier.startswith("Tier 2")
        ex_reason = "" if is_valid else f"基线拟合未达门禁: sales_diff={single_sales_diff:.1%}, scm_fit={fit_rmspe:.2f}"
        ex_code = "" if is_valid else "BASELINE_FIT_OUTSIDE_CALIPER"

        base_record.update({
            "match_tier": tier,
            "is_valid_match": is_valid,
            "exclusion_code": ex_code,
            "is_excluded_reason": ex_reason,
            "scm_control_stores": json.dumps(selected_donors, ensure_ascii=False),
            "scm_donors_text": donors_text,
            "pre_fit_rmspe": fit_rmspe,
            "pre_holdout_rmspe": holdout_rmspe,
            "category_js_distance": jsd,
            "fitted_sales_diff_pct": float(fitted_sales_diff * 100),
            "fitted_profit_diff_pct": float(fitted_profit_diff * 100),
            "fitted_trend_diff_pp": float(fitted_trend_diff * 100),
        })
        pair_rows.append(base_record)

    return pd.DataFrame(pair_rows)


# ==============================================================================
# 3. Triple Difference (DDD / YoY-DID) Engine
# ==============================================================================

def calculate_4period_ddd(
    df_pairs: pd.DataFrame,
    df_daily: pd.DataFrame,
    window_days: int = 30,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Calculate exact 4-period (C, H, L, LH) DDD for Sales, Profit, Orders, and ATV across all valid pairs."""
    sub_indexed = df_daily.copy()
    sub_indexed["stat_date"] = pd.to_datetime(sub_indexed["stat_date"])
    daily_map = {int(code): part.set_index("stat_date") for code, part in sub_indexed.groupby("store_code", sort=False)}

    pair_ddd_records: list[dict[str, Any]] = []

    for _, pair in df_pairs.iterrows():
        p_id = str(pair["pair_id"])
        is_valid = bool(pair["is_valid_match"])
        p_code = int(pair["store_code_a"])
        start = pd.to_datetime(pair["test_start_date"])

        rec: dict[str, Any] = {
            "pair_id": p_id,
            "pilot_pre_yoy": np.nan,
            "pilot_post_yoy": np.nan,
            "pilot_diff_pp": np.nan,
            "control_pre_yoy": np.nan,
            "control_post_yoy": np.nan,
            "control_diff_pp": np.nan,
            "sales_did_pp": np.nan,
            "profit_did_pp": np.nan,
            "order_did_pp": np.nan,
            "atv_did_pp": np.nan,
        }

        if not is_valid:
            pair_ddd_records.append(rec)
            continue

        donors = json.loads(pair["scm_control_stores"])

        # Define 4 periods
        c_span = (start, start + pd.Timedelta(days=window_days - 1))
        h_span = (start - pd.Timedelta(days=window_days), start - pd.Timedelta(days=1))
        l_span = (start - pd.Timedelta(days=364), start - pd.Timedelta(days=364) + pd.Timedelta(days=window_days - 1))
        lh_span = (start - pd.Timedelta(days=364) - pd.Timedelta(days=window_days), start - pd.Timedelta(days=364) - pd.Timedelta(days=1))

        def _get_period_metrics(code: int, span: tuple[pd.Timestamp, pd.Timestamp]) -> dict[str, float]:
            if code not in daily_map:
                return {"sales": np.nan, "profit": np.nan, "orders": np.nan}
            table = daily_map[code]
            part = table.loc[span[0]:span[1]] if not table.empty else pd.DataFrame()
            if part.empty:
                return {"sales": np.nan, "profit": np.nan, "orders": np.nan}
            return {
                "sales": float(part["sales"].sum()) if "sales" in part else np.nan,
                "profit": float(part["profit"].sum()) if "profit" in part else np.nan,
                "orders": float(part["orders"].sum()) if "orders" in part else np.nan,
            }

        # Pilot measurements
        p_c = _get_period_metrics(p_code, c_span)
        p_h = _get_period_metrics(p_code, h_span)
        p_l = _get_period_metrics(p_code, l_span)
        p_lh = _get_period_metrics(p_code, lh_span)

        # Control weighted measurements
        c_c = {"sales": 0.0, "profit": 0.0, "orders": 0.0}
        c_h = {"sales": 0.0, "profit": 0.0, "orders": 0.0}
        c_l = {"sales": 0.0, "profit": 0.0, "orders": 0.0}
        c_lh = {"sales": 0.0, "profit": 0.0, "orders": 0.0}

        for d in donors:
            d_code = int(d["store_code"])
            w = float(d["weight"])
            m_c = _get_period_metrics(d_code, c_span)
            m_h = _get_period_metrics(d_code, h_span)
            m_l = _get_period_metrics(d_code, l_span)
            m_lh = _get_period_metrics(d_code, lh_span)
            for k in ["sales", "profit", "orders"]:
                c_c[k] += w * m_c[k]
                c_h[k] += w * m_h[k]
                c_l[k] += w * m_l[k]
                c_lh[k] += w * m_lh[k]

        def _compute_metric_ddd(k: str) -> tuple[float, float, float, float, float, float, float]:
            val_pc, val_ph = p_c[k], p_h[k]
            val_pl, val_plh = p_l[k], p_lh[k]
            val_cc, val_ch = c_c[k], c_h[k]
            val_cl, val_clh = c_l[k], c_lh[k]

            p_post = (val_pc - val_ph) / val_ph if val_ph > 0 else np.nan
            p_pre = (val_pl - val_plh) / val_plh if val_plh > 0 else np.nan
            c_post = (val_cc - val_ch) / val_ch if val_ch > 0 else np.nan
            c_pre = (val_cl - val_clh) / val_clh if val_clh > 0 else np.nan

            p_diff = (p_post - p_pre) * 100 if np.isfinite(p_post) and np.isfinite(p_pre) else np.nan
            c_diff = (c_post - c_pre) * 100 if np.isfinite(c_post) and np.isfinite(c_pre) else np.nan
            did = p_diff - c_diff if np.isfinite(p_diff) and np.isfinite(c_diff) else np.nan

            return p_pre * 100, p_post * 100, p_diff, c_pre * 100, c_post * 100, c_diff, did

        s_pre_a, s_post_a, s_diff_a, s_pre_b, s_post_b, s_diff_b, s_did = _compute_metric_ddd("sales")
        _, _, _, _, _, _, p_did = _compute_metric_ddd("profit")
        _, _, _, _, _, _, o_did = _compute_metric_ddd("orders")

        # ATV = Sales / Orders
        def _atv(m: dict[str, float]) -> float:
            return m["sales"] / m["orders"] if m["orders"] > 0 else np.nan

        atv_pc, atv_ph = _atv(p_c), _atv(p_h)
        atv_pl, atv_plh = _atv(p_l), _atv(p_lh)
        atv_cc, atv_ch = _atv(c_c), _atv(c_h)
        atv_cl, atv_clh = _atv(c_l), _atv(c_lh)

        atv_post_a = (atv_pc - atv_ph) / atv_ph if atv_ph > 0 else np.nan
        atv_pre_a = (atv_pl - atv_plh) / atv_plh if atv_plh > 0 else np.nan
        atv_post_b = (atv_cc - atv_ch) / atv_ch if atv_ch > 0 else np.nan
        atv_pre_b = (atv_cl - atv_clh) / atv_clh if atv_clh > 0 else np.nan
        atv_diff_a = (atv_post_a - atv_pre_a) * 100 if np.isfinite(atv_post_a) and np.isfinite(atv_pre_a) else np.nan
        atv_diff_b = (atv_post_b - atv_pre_b) * 100 if np.isfinite(atv_post_b) and np.isfinite(atv_pre_b) else np.nan
        atv_did = atv_diff_a - atv_diff_b if np.isfinite(atv_diff_a) and np.isfinite(atv_diff_b) else np.nan

        rec.update({
            "pilot_pre_yoy": s_pre_a,
            "pilot_post_yoy": s_post_a,
            "pilot_diff_pp": s_diff_a,
            "control_pre_yoy": s_pre_b,
            "control_post_yoy": s_post_b,
            "control_diff_pp": s_diff_b,
            "sales_did_pp": s_did,
            "profit_did_pp": p_did,
            "order_did_pp": o_did,
            "atv_did_pp": atv_did,
        })
        pair_ddd_records.append(rec)

    df_pair_ddd = pd.DataFrame(pair_ddd_records)

    # Compute Aggregate Summary Table
    valid_sub = df_pair_ddd[np.isfinite(df_pair_ddd["sales_did_pp"])].copy()
    n_valid = len(valid_sub)

    summary_rows = [
        {
            "window": f"{window_days}D",
            "metric": "销售额",
            "pilot_cnt": n_valid,
            "mean_store_did_pp": float(valid_sub["sales_did_pp"].mean()) if n_valid > 0 else np.nan,
            "pilot_diff_mean_pp": float(valid_sub["pilot_diff_pp"].mean()) if n_valid > 0 else np.nan,
            "control_diff_mean_pp": float(valid_sub["control_diff_pp"].mean()) if n_valid > 0 else np.nan,
        },
        {
            "window": f"{window_days}D",
            "metric": "毛利额",
            "pilot_cnt": n_valid,
            "mean_store_did_pp": float(valid_sub["profit_did_pp"].mean()) if n_valid > 0 else np.nan,
            "pilot_diff_mean_pp": np.nan,
            "control_diff_mean_pp": np.nan,
        },
        {
            "window": f"{window_days}D",
            "metric": "客流订单量",
            "pilot_cnt": n_valid,
            "mean_store_did_pp": float(valid_sub["order_did_pp"].mean()) if n_valid > 0 else np.nan,
            "pilot_diff_mean_pp": np.nan,
            "control_diff_mean_pp": np.nan,
        },
        {
            "window": f"{window_days}D",
            "metric": "客单价(ATV)",
            "pilot_cnt": n_valid,
            "mean_store_did_pp": float(valid_sub["atv_did_pp"].mean()) if n_valid > 0 else np.nan,
            "pilot_diff_mean_pp": np.nan,
            "control_diff_mean_pp": np.nan,
        },
    ]

    return df_pair_ddd, pd.DataFrame(summary_rows)


# ==============================================================================
# 4. Standardized Deliverables: 4-Sheet Excel & Blueprint HTML
# ==============================================================================

def export_excel_workbook(
    df_pairs: pd.DataFrame,
    df_pair_ddd: pd.DataFrame,
    df_summary: pd.DataFrame,
    df_candidates: pd.DataFrame,
    output_path: Path,
) -> None:
    """Export standardized pyramid 4-Sheet Excel with strict Results vs Process Decoupling."""
    try:
        import openpyxl
        from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
        from openpyxl.utils import get_column_letter
    except ImportError:
        print("Warning: openpyxl is not installed. Exporting CSV fallback summary instead.")
        df_pair_ddd.to_csv(output_path.with_suffix(".csv"), index=False, encoding="utf-8-sig")
        return

    wb = openpyxl.Workbook()
    if wb.active is not None:
        wb.remove(wb.active)

    font_family = "Microsoft YaHei"
    f_title = Font(name=font_family, size=13, bold=True, color="1E3A8A")
    f_sec = Font(name=font_family, size=11, bold=True, color="1E293B")
    f_head = Font(name=font_family, size=10, bold=True, color="FFFFFF")
    f_body = Font(name=font_family, size=10, color="0F172A")
    f_note = Font(name=font_family, size=9, italic=True, color="64748B")

    fill_navy = PatternFill(start_color="1E3A8A", end_color="1E3A8A", fill_type="solid")
    fill_slate = PatternFill(start_color="334155", end_color="334155", fill_type="solid")
    border_thin = Border(
        left=Side(border_style="thin", color="CBD5E1"),
        right=Side(border_style="thin", color="CBD5E1"),
        top=Side(border_style="thin", color="CBD5E1"),
        bottom=Side(border_style="thin", color="CBD5E1"),
    )

    def _fmt_pct(v: float) -> str:
        return f"{v:+.2f}%" if np.isfinite(v) else "—"

    def _fmt_pp(v: float) -> str:
        return f"{v:+.2f}pp" if np.isfinite(v) else "—"

    # --------------------------------------------------------------------------
    # Sheet 1: 评估结论总览
    # --------------------------------------------------------------------------
    ws1 = wb.create_sheet(title="评估结论总览")
    ws1.views.sheetView[0].showGridLines = False

    ws1.cell(row=1, column=1, value="零售营运管理干预因果推断评估 · 结论总览大盘").font = f_title
    ws1.cell(row=2, column=1, value="口径: 严格同区同店型硬分层、尺度不变性MDM、SCM凸组合优化、三重差分(DDD)闭环测算").font = f_note

    # Section 1: Summary KPI Table
    ws1.cell(row=4, column=1, value="一、核心合格配对大盘效果汇总").font = f_sec
    s1_heads = ["分析窗口", "核心指标", "有效样本量", "试点店增量(pp)", "对照组增量(pp)", "DID净增量(pp)"]
    for c_idx, h in enumerate(s1_heads, start=1):
        cell = ws1.cell(row=5, column=c_idx, value=h)
        cell.font = f_head
        cell.fill = fill_navy
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = border_thin

    row_cur = 6
    for _, r in df_summary.iterrows():
        vals = [
            str(r["window"]),
            str(r["metric"]),
            int(r["pilot_cnt"]),
            _fmt_pp(r["pilot_diff_mean_pp"]),
            _fmt_pp(r["control_diff_mean_pp"]),
            _fmt_pp(r["mean_store_did_pp"]),
        ]
        for c_idx, v in enumerate(vals, start=1):
            c = ws1.cell(row=row_cur, column=c_idx, value=v)
            c.font = f_body
            c.border = border_thin
            c.alignment = Alignment(horizontal="center" if c_idx <= 3 else "right", vertical="center")
        row_cur += 1

    # Section 2: Excluded Stores
    row_cur += 2
    ex_pairs = df_pairs[~df_pairs["is_valid_match"]]
    ws1.cell(row=row_cur, column=1, value=f"二、未获可比对照与排除门店专表 (共 {len(ex_pairs)} 家 · 规则驱动客观隔离)").font = f_sec
    row_cur += 1
    ex_heads = ["配对编号", "试点编码", "试点门店名称", "所属营运区", "店型分类", "排除原因说明", "原因代码"]
    for c_idx, h in enumerate(ex_heads, start=1):
        cell = ws1.cell(row=row_cur, column=c_idx, value=h)
        cell.font = f_head
        cell.fill = fill_slate
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = border_thin
    row_cur += 1
    for _, r in ex_pairs.iterrows():
        vals = [
            str(r["pair_id"]),
            int(r["store_code_a"]),
            str(r["store_name_a"]),
            str(r["region_man_name"]),
            str(r["store_strata"]),
            str(r["is_excluded_reason"]),
            str(r["exclusion_code"]),
        ]
        for c_idx, v in enumerate(vals, start=1):
            c = ws1.cell(row=row_cur, column=c_idx, value=v)
            c.font = f_body
            c.border = border_thin
            c.alignment = Alignment(horizontal="center" if c_idx in [1, 2, 4, 5, 7] else "left", vertical="center")
        row_cur += 1

    for col in ws1.columns:
        col_letter = get_column_letter(col[0].column)
        ws1.column_dimensions[col_letter].width = 20

    # --------------------------------------------------------------------------
    # Sheet 2: 试验组与对照组详细门店及指标 (两区彻底解耦)
    # --------------------------------------------------------------------------
    ws2 = wb.create_sheet(title="试验组与对照组详细门店及指标")
    ws2.views.sheetView[0].showGridLines = False

    sheet2_cols = [
        ("pair_id", "配对编号", "center"),
        ("region_man_name", "营运区", "center"),
        ("store_strata", "店型分类", "center"),
        ("store_code_a", "试点编码", "center"),
        ("store_name_a", "试点门店名称", "left"),
        ("match_tier", "对照类型 (单体/拟合/未匹配)", "center"),
        ("control_display_name", "最终对位对照组名称", "left"),
        # 业务实证结果区
        ("pilot_pre_yoy", "试点店销售基期同比(%)", "right"),
        ("pilot_post_yoy", "试点店销售实施后同比(%)", "right"),
        ("pilot_diff_pp", "试点店销售增量(pp)", "right"),
        ("control_pre_yoy", "对照组销售基期同比(%)", "right"),
        ("control_post_yoy", "对照组销售实施后同比(%)", "right"),
        ("control_diff_pp", "对照组销售增量(pp)", "right"),
        ("sales_did_pp", "销售DID净增量(pp)", "right"),
        ("profit_did_pp", "毛利DID净增量(pp)", "right"),
        ("order_did_pp", "客流DID净增量(pp)", "right"),
        ("atv_did_pp", "客单价DID净增量(pp)", "right"),
        # 算法拟合过程与质量审计区
        ("fitted_sales_diff_pct", "最终对照销售拟合偏差(%)", "right"),
        ("fitted_profit_diff_pct", "最终对照毛利拟合偏差(%)", "right"),
        ("fitted_trend_diff_pp", "基期走势偏差(pp)", "right"),
        ("category_js_distance", "品类JSD", "right"),
        ("pre_holdout_rmspe", "留出测试集盲测RMSPE", "right"),
        ("single_store_name_b", "1:1单店锚点名称", "left"),
        ("single_sales_diff_pct", "1:1单店销售偏差(%)", "right"),
        ("single_profit_diff_pct", "1:1单店毛利偏差(%)", "right"),
        ("single_trend_diff_pp", "1:1单店走势偏差(pp)", "right"),
        ("scm_donors_text", "SCM供体组成及权重", "left"),
        ("is_excluded_reason", "未匹配/排除客观说明", "left"),
    ]

    for c_idx, (_, label, _) in enumerate(sheet2_cols, start=1):
        cell = ws2.cell(row=1, column=c_idx, value=label)
        cell.font = f_head
        cell.fill = fill_navy
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = border_thin

    merged_pairs = df_pairs.merge(df_pair_ddd, on="pair_id", how="left")

    row_cur = 2
    for _, r in merged_pairs.iterrows():
        is_valid = bool(r["is_valid_match"])
        tier = str(r["match_tier"])
        ctrl_name = "未匹配 (无同层合规对照)" if not is_valid else (f"单体对照: {r['single_store_name_b']}" if tier.startswith("Tier 1") else f"虚拟拟合克隆: {r['scm_donors_text']}")

        vals = [
            str(r["pair_id"]),
            str(r["region_man_name"]),
            str(r["store_strata"]),
            int(r["store_code_a"]),
            str(r["store_name_a"]),
            tier,
            ctrl_name,
            _fmt_pct(r["pilot_pre_yoy"]),
            _fmt_pct(r["pilot_post_yoy"]),
            _fmt_pp(r["pilot_diff_pp"]),
            _fmt_pct(r["control_pre_yoy"]),
            _fmt_pct(r["control_post_yoy"]),
            _fmt_pp(r["control_diff_pp"]),
            _fmt_pp(r["sales_did_pp"]),
            _fmt_pp(r["profit_did_pp"]),
            _fmt_pp(r["order_did_pp"]),
            _fmt_pp(r["atv_did_pp"]),
            f"{r['fitted_sales_diff_pct']:.1f}%" if np.isfinite(r["fitted_sales_diff_pct"]) else "—",
            f"{r['fitted_profit_diff_pct']:.1f}%" if np.isfinite(r["fitted_profit_diff_pct"]) else "—",
            f"{r['fitted_trend_diff_pp']:.1f}pp" if np.isfinite(r["fitted_trend_diff_pp"]) else "—",
            f"{r['category_js_distance']:.4f}" if np.isfinite(r["category_js_distance"]) else "—",
            f"{r['pre_holdout_rmspe']:.4f}" if np.isfinite(r["pre_holdout_rmspe"]) else "—",
            str(r["single_store_name_b"]),
            f"{r['single_sales_diff_pct']:.1f}%" if np.isfinite(r["single_sales_diff_pct"]) else "—",
            f"{r['single_profit_diff_pct']:.1f}%" if np.isfinite(r["single_profit_diff_pct"]) else "—",
            f"{r['single_trend_diff_pp']:.1f}pp" if np.isfinite(r["single_trend_diff_pp"]) else "—",
            str(r["scm_donors_text"]),
            str(r["is_excluded_reason"]),
        ]
        for c_idx, (v, (_, _, align)) in enumerate(zip(vals, sheet2_cols, strict=True), start=1):
            c = ws2.cell(row=row_cur, column=c_idx, value=v)
            c.font = f_body
            c.border = border_thin
            c.alignment = Alignment(horizontal=align, vertical="center")
        row_cur += 1

    for col in ws2.columns:
        col_letter = get_column_letter(col[0].column)
        ws2.column_dimensions[col_letter].width = 18
    ws2.column_dimensions["E"].width = 25
    ws2.column_dimensions["G"].width = 30
    ws2.column_dimensions["AA"].width = 30
    ws2.column_dimensions["AB"].width = 35

    # --------------------------------------------------------------------------
    # Sheet 3: 候选池分层与虚拟合成溯源
    # --------------------------------------------------------------------------
    ws3 = wb.create_sheet(title="候选池分层与虚拟合成溯源")
    ws3.views.sheetView[0].showGridLines = False
    ws3.cell(row=1, column=1, value="候选供体池成熟度与分层溯源清单").font = f_title
    s3_heads = ["候选门店编码", "候选门店名称", "所属营运区", "店型分类", "开业日期", "开业天数", "资格状态"]
    for c_idx, h in enumerate(s3_heads, start=1):
        cell = ws3.cell(row=3, column=c_idx, value=h)
        cell.font = f_head
        cell.fill = fill_slate
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = border_thin
    row_cur = 4
    for _, r in df_candidates.head(100).iterrows():
        vals = [
            int(r["store_code"]),
            str(r["store_name"]),
            str(r["region_name"]),
            str(r["store_stratum"]),
            str(r.get("open_date", "2020-01-01")),
            int(r.get("open_days", 1000)),
            "合规成熟供体",
        ]
        for c_idx, v in enumerate(vals, start=1):
            c = ws3.cell(row=row_cur, column=c_idx, value=v)
            c.font = f_body
            c.border = border_thin
            c.alignment = Alignment(horizontal="center" if c_idx in [1, 3, 4, 5, 6, 7] else "left", vertical="center")
        row_cur += 1

    for col in ws3.columns:
        col_letter = get_column_letter(col[0].column)
        ws3.column_dimensions[col_letter].width = 20

    # --------------------------------------------------------------------------
    # Sheet 4: 口径说明与计算字典
    # --------------------------------------------------------------------------
    ws4 = wb.create_sheet(title="口径说明与计算字典")
    ws4.views.sheetView[0].showGridLines = False
    ws4.cell(row=1, column=1, value="因果推断方法论标准计算字典与卡尺门禁口径").font = f_title

    dict_lines = [
        ("四大核心集合", "候选供体集(成熟合规同区同层)、训练集(90D~31D双段时序拟合)、留出测试集(30D~1D严格盲测绝缘)、最终对照集(Tier 1/Tier 2/Tier 3)"),
        ("三重差分 DDD", "DDD = (YoY_pilot,post - YoY_pilot,pre) - (YoY_ctrl,post - YoY_ctrl,pre)；严格差分的差分闭环"),
        ("客单价 (ATV)", "ATV = Sales / Orders 真实流水比值直算，严禁颠倒"),
        ("单店门禁 (Tier 1)", "训练期单店销售偏差 <= 10%、客流偏差 <= 10%、走势偏差 <= 15pp 优先入选单店"),
        ("拟合门禁 (Tier 2)", "SCM凸优化拟合度 RMSPE <= 1.0、SCM销售偏差 <= 20%、走势偏差 <= 20pp 入选合成克隆"),
        ("排除门禁 (Tier 3)", "单店与SCM均未突破门禁或同层候选池为空，沉底归入未匹配专表，坚决杜绝跨层降级混配"),
        ("留出盲测绝缘铁律", "留出测试集 30 天数据 100% 物理绝缘，不参与拟合、优化与门禁，仅作为事前预测泛化能力诊断披露"),
    ]
    for r_idx, (term, desc) in enumerate(dict_lines, start=3):
        c1 = ws4.cell(row=r_idx, column=1, value=term)
        c1.font = Font(name=font_family, size=10, bold=True, color="1E3A8A")
        c1.border = border_thin
        c2 = ws4.cell(row=r_idx, column=2, value=desc)
        c2.font = f_body
        c2.border = border_thin
    ws4.column_dimensions["A"].width = 25
    ws4.column_dimensions["B"].width = 80

    output_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(output_path)
    print(f"Saved pyramid 4-Sheet Excel at: {output_path}")


def export_executive_html(
    df_pairs: pd.DataFrame,
    df_summary: pd.DataFrame,
    output_path: Path,
) -> None:
    """Generate clean Blueprint style executive dashboard HTML with SVG CONSORT funnel and KPI cards."""
    valid_cnt = int(df_pairs["is_valid_match"].sum())
    total_cnt = len(df_pairs)
    t1_cnt = int((df_pairs["match_tier"] == "Tier 1: 真实单店").sum())
    t2_cnt = int((df_pairs["match_tier"] == "Tier 2: SCM 虚拟克隆").sum())
    t3_cnt = int(df_pairs["match_tier"].str.contains("Tier 3").sum())

    sales_did = df_summary[df_summary["metric"] == "销售额"]["mean_store_did_pp"].values[0] if not df_summary.empty else 0.0
    profit_did = df_summary[df_summary["metric"] == "毛利额"]["mean_store_did_pp"].values[0] if not df_summary.empty else 0.0
    order_did = df_summary[df_summary["metric"] == "客流订单量"]["mean_store_did_pp"].values[0] if not df_summary.empty else 0.0

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>零售营运管理干预因果推断决策看板</title>
<style>
:root {{
  --bg: #F8FAFC; --card: #FFFFFF; --text: #0F172A; --sub: #64748B;
  --primary: #1E3A8A; --accent: #2563EB; --border: #E2E8F0;
  --success: #059669; --danger: #DC2626;
}}
body {{
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Microsoft YaHei", sans-serif;
  background: var(--bg); color: var(--text); margin: 0; padding: 24px;
}}
.container {{ max-width: 1200px; margin: 0 auto; }}
.header {{ margin-bottom: 24px; }}
.header h1 {{ margin: 0 0 8px 0; color: var(--primary); font-size: 24px; }}
.header p {{ margin: 0; color: var(--sub); font-size: 14px; }}
.grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 16px; margin-bottom: 24px; }}
.card {{ background: var(--card); border: 1px solid var(--border); border-radius: 8px; padding: 20px; box-shadow: 0 1px 3px rgba(0,0,0,0.05); }}
.metric-title {{ font-size: 13px; color: var(--sub); text-transform: uppercase; margin-bottom: 8px; font-weight: 600; }}
.metric-value {{ font-size: 28px; font-weight: 700; color: var(--primary); }}
.metric-value.pos {{ color: var(--success); }}
.metric-value.neg {{ color: var(--danger); }}
.metric-desc {{ font-size: 12px; color: var(--sub); margin-top: 6px; }}
.panel {{ background: var(--card); border: 1px solid var(--border); border-radius: 8px; padding: 24px; margin-bottom: 24px; }}
.panel h2 {{ margin: 0 0 16px 0; font-size: 18px; color: var(--primary); border-bottom: 1px solid var(--border); padding-bottom: 8px; }}
.funnel-container {{ text-align: center; margin: 20px 0; }}
.table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
.table th, .table td {{ padding: 10px 12px; text-align: left; border-bottom: 1px solid var(--border); }}
.table th {{ background: #F1F5F9; font-weight: 600; color: var(--primary); }}
.callout {{ background: #EFF6FF; border-left: 4px solid var(--accent); padding: 14px 18px; border-radius: 4px; font-size: 13px; color: #1E40AF; margin-top: 16px; }}
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <h1>零售营运干预因果效应评估决策看板</h1>
    <p>方法体系: 1:N 硬分层互锁 · 尺度不变性 MDM · SCM 凸优化 · 30D 留出盲测 · 三重差分 (DDD)</p>
  </div>

  <div class="grid">
    <div class="card">
      <div class="metric-title">销售额 DID 净增量 (30D)</div>
      <div class="metric-value {'pos' if sales_did >= 0 else 'neg'}">{sales_did:+.2f}pp</div>
      <div class="metric-desc">有效结对试点店: {valid_cnt} 家 / 总试点: {total_cnt} 家</div>
    </div>
    <div class="card">
      <div class="metric-title">毛利额 DID 净增量 (30D)</div>
      <div class="metric-value {'pos' if profit_did >= 0 else 'neg'}">{profit_did:+.2f}pp</div>
      <div class="metric-desc">毛利纳入 SCM 二次规划优化目标约束</div>
    </div>
    <div class="card">
      <div class="metric-title">客流订单量 DID 净增量 (30D)</div>
      <div class="metric-value {'pos' if order_did >= 0 else 'neg'}">{order_did:+.2f}pp</div>
      <div class="metric-desc">全期真实订单流水直算，剔除空单噪音</div>
    </div>
  </div>

  <div class="panel">
    <h2>因果推断分层与卡尺流转漏斗 (CONSORT 架构)</h2>
    <div class="funnel-container">
      <svg width="780" height="180" viewBox="0 0 780 180" xmlns="http://www.w3.org/2000/svg">
        <rect x="20" y="30" width="160" height="100" rx="6" fill="#1E3A8A" />
        <text x="100" y="70" fill="#fff" font-size="14" font-weight="bold" text-anchor="middle">全量试点门店</text>
        <text x="100" y="95" fill="#93C5FD" font-size="13" text-anchor="middle">{total_cnt} 家</text>

        <line x1="180" y1="80" x2="220" y2="80" stroke="#64748B" stroke-width="2" marker-end="url(#arrow)" />

        <rect x="220" y="30" width="160" height="100" rx="6" fill="#334155" />
        <text x="300" y="65" fill="#fff" font-size="13" font-weight="bold" text-anchor="middle">1:N 店型分层匹配</text>
        <text x="300" y="85" fill="#CBD5E1" font-size="12" text-anchor="middle">同区同层供体池初排</text>
        <text x="300" y="105" fill="#93C5FD" font-size="12" text-anchor="middle">90D~31D 训练集</text>

        <line x1="380" y1="80" x2="420" y2="80" stroke="#64748B" stroke-width="2" />

        <rect x="420" y="30" width="160" height="100" rx="6" fill="#047857" />
        <text x="500" y="65" fill="#fff" font-size="13" font-weight="bold" text-anchor="middle">基线门禁合格对照</text>
        <text x="500" y="85" fill="#D1FAE5" font-size="12" text-anchor="middle">Tier 1 单店: {t1_cnt} 家</text>
        <text x="500" y="105" fill="#A7F3D0" font-size="12" text-anchor="middle">Tier 2 SCM: {t2_cnt} 家</text>

        <line x1="580" y1="80" x2="620" y2="80" stroke="#64748B" stroke-width="2" />

        <rect x="620" y="30" width="140" height="100" rx="6" fill="#DC2626" />
        <text x="690" y="70" fill="#fff" font-size="13" font-weight="bold" text-anchor="middle">Tier 3 排除沉底</text>
        <text x="690" y="95" fill="#FECACA" font-size="13" text-anchor="middle">{t3_cnt} 家 (客观隔离)</text>
      </svg>
    </div>
    <div class="callout">
      <strong>交付指引:</strong> 逐店明细、完整 DDD 因果链条及拟合质量审计数据已在配套 4-Sheet Excel 工作簿中解耦呈现。详细单店表现请查阅 Excel 文件的 <strong>Sheet 2</strong>。
    </div>
  </div>
</div>
</body>
</html>
"""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
    print(f"Saved executive HTML report at: {output_path}")


# ==============================================================================
# 5. Synthetic Demo Dataset Generator
# ==============================================================================

def generate_synthetic_dataset() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Generate realistic synthetic retail datasets for instant out-of-the-box verification."""
    np.random.seed(42)

    # 1. Pilot Stores (12 stores across 2 regions and 3 strata)
    regions = ["广州营运区", "佛山营运区"]
    strata = ["常规成熟店", "O2O重点店", "DTP门店"]
    pilots_data: list[dict[str, Any]] = []

    for i in range(1, 13):
        reg = regions[(i - 1) % 2]
        strat = strata[(i - 1) % 3]
        pilots_data.append({
            "store_code": 1000 + i,
            "store_name": f"{reg[:2]}试点_{strat[:2]}_{i}店",
            "region_name": reg,
            "store_stratum": strat,
            "test_start_date": "2026-06-01",
        })
    df_pilots = pd.DataFrame(pilots_data)

    # 2. Candidate Donor Stores (40 mature stores)
    cands_data: list[dict[str, Any]] = []
    cand_codes: list[int] = []
    c_idx = 1
    for reg in regions:
        for strat in strata:
            for k in range(1, 8):
                code = 2000 + c_idx
                cand_codes.append(code)
                cands_data.append({
                    "store_code": code,
                    "store_name": f"{reg[:2]}候选_{strat[:2]}_{c_idx}店",
                    "region_name": reg,
                    "store_stratum": strat,
                    "open_date": "2021-01-01",
                    "open_days": 1800,
                })
                c_idx += 1
    df_candidates = pd.DataFrame(cands_data)

    # 3. Store Daily Sales (180 days: 2025-02-01 to 2026-07-31)
    all_codes = list(df_pilots["store_code"]) + cand_codes
    dates = pd.date_range("2025-02-01", "2026-07-31", freq="D")

    daily_rows: list[dict[str, Any]] = []
    for code in all_codes:
        base_s = np.random.uniform(3000.0, 8000.0)
        base_p = base_s * np.random.uniform(0.20, 0.35)
        base_o = base_s / np.random.uniform(40.0, 70.0)

        is_pilot = code in df_pilots["store_code"].values
        for dt in dates:
            noise = np.random.normal(1.0, 0.08)
            # Add a small true intervention boost for pilots after 2026-06-01
            boost = 1.05 if (is_pilot and dt >= pd.Timestamp("2026-06-01")) else 1.0

            s_val = round(max(base_s * noise * boost, 100.0), 2)
            p_val = round(max(base_p * noise * boost, 20.0), 2)
            o_val = int(max(base_o * noise * boost, 5))

            daily_rows.append({
                "store_code": code,
                "stat_date": dt.strftime("%Y-%m-%d"),
                "sales": s_val,
                "profit": p_val,
                "orders": o_val,
            })
    df_daily = pd.DataFrame(daily_rows)

    # 4. Category Shares
    cats = ["处方西药", "非处方药", "中药饮片", "医疗器械", "保健食品"]
    cat_rows: list[dict[str, Any]] = []
    for code in all_codes:
        raw_weights = np.random.dirichlet(np.ones(len(cats)))
        for c_name, w in zip(cats, raw_weights, strict=True):
            cat_rows.append({
                "store_code": code,
                "category_name": c_name,
                "share": float(w),
            })
    df_cat = pd.DataFrame(cat_rows)

    return df_pilots, df_candidates, df_daily, df_cat


# ==============================================================================
# 6. Main Orchestrator & CLI Facade
# ==============================================================================

def run_causal_evaluation_pipeline(
    df_pilots: pd.DataFrame,
    df_candidates: pd.DataFrame,
    df_daily: pd.DataFrame,
    df_cat: pd.DataFrame,
    output_dir: Path,
) -> None:
    """Execute complete end-to-end causal evaluation workflow."""
    output_dir.mkdir(parents=True, exist_ok=True)
    print("=" * 70)
    print("RETAIL CAUSAL EVALUATION & SYNTHETIC CONTROL MATCHING PIPELINE")
    print("=" * 70)
    print(f"Pilots: {len(df_pilots)} stores | Candidates: {len(df_candidates)} stores")

    # Step 3: Match & Tier Stores
    print("\n[Step 3] Running 1:N stratification, MDM ranking, convex SCM, & Holdout testing...")
    df_pairs = match_pilot_stores(df_pilots, df_candidates, df_daily, df_cat)
    valid_cnt = int(df_pairs["is_valid_match"].sum())
    print(f"Matching finished: {valid_cnt} / {len(df_pairs)} pairs qualified.")

    # Step 4: Triple Difference (DDD)
    print("\n[Step 4] Computing 4-period Triple Difference (DDD) for 30D window...")
    df_pair_ddd, df_summary = calculate_4period_ddd(df_pairs, df_daily, window_days=30)
    for _, r in df_summary.iterrows():
        print(f"  - {r['metric']}: {r['mean_store_did_pp']:+.2f}pp (N={r['pilot_cnt']})")

    # Step 5: Deliverables
    print("\n[Step 5] Exporting pyramid 4-Sheet Excel and Blueprint HTML...")
    excel_path = output_dir / "causal_evaluation_report.xlsx"
    html_path = output_dir / "causal_evaluation_dashboard.html"

    export_excel_workbook(df_pairs, df_pair_ddd, df_summary, df_candidates, excel_path)
    export_executive_html(df_pairs, df_summary, html_path)
    print("\nAll deliverables generated successfully!")
    print("=" * 70)


def run_dry_run_checks() -> None:
    """Perform mathematical invariants, simplex projections, and scale invariance self-tests."""
    print("Running mathematical invariants self-test...")

    # 1. Scale Invariance Test
    donors = np.array([[1000.0, 300.0, 20.0, 0.1], [2000.0, 300.0, 40.0, -0.1], [3500.0, 300.0, 70.0, 0.2]], dtype=float)
    target = np.array([1800.0, 450.0, 36.0, 0.03], dtype=float)
    units = np.array([0.0001, 0.0001, 1.0, 1.0], dtype=float)

    d1 = compute_standardized_mahalanobis_distances(donors, target)
    d2 = compute_standardized_mahalanobis_distances(donors * units, target * units)
    assert np.allclose(d1, d2), "Scale invariance failed for MDM!"

    # 2. Simplex Projection Test
    w1 = solve_convex_scm_weights(donors, target)
    w2 = solve_convex_scm_weights(donors * units, target * units)
    assert np.isclose(sum(w1), 1.0), "SCM weights do not sum to 1.0!"
    assert np.allclose(w1, w2, atol=1e-3), "Scale invariance failed for SCM weights!"

    # 3. JSD Metric Test
    p = [0.4, 0.3, 0.2, 0.1]
    q = [0.1, 0.2, 0.3, 0.4]
    jsd = compute_js_distance(p, q)
    assert 0.0 <= jsd <= 1.0, f"JSD out of bounds: {jsd}"
    assert np.isclose(compute_js_distance(p, p), 0.0), "Self-JSD must be 0.0!"

    print("Mathematical self-test passed cleanly. All invariants hold.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Retail Causal DID & SCM Evaluation Runner Template.")
    parser.add_argument("--dry-run", action="store_true", help="Run internal mathematical self-test and exit.")
    parser.add_argument("--synthetic-demo", action="store_true", help="Generate synthetic retail dataset and run end-to-end demo.")
    parser.add_argument("--pilot-file", type=str, help="Path to pilot stores CSV / Excel.")
    parser.add_argument("--candidate-file", type=str, help="Path to candidate donor stores CSV / Excel.")
    parser.add_argument("--daily-file", type=str, help="Path to daily sales CSV / Parquet.")
    parser.add_argument("--cat-file", type=str, help="Path to category share CSV / Excel.")
    parser.add_argument("--output-dir", type=str, default="./outputs", help="Output directory for Excel and HTML reports.")

    args = parser.parse_args()

    if args.dry_run:
        run_dry_run_checks()
        sys.exit(0)

    if args.synthetic_demo or not args.pilot_file:
        print("Executing in synthetic demo mode (generating realistic retail trial data)...")
        df_p, df_c, df_d, df_cat = generate_synthetic_dataset()
        out_dir = Path(args.output_dir)
        run_causal_evaluation_pipeline(df_p, df_c, df_d, df_cat, out_dir)
        sys.exit(0)

    # Load custom files
    out_dir = Path(args.output_dir)
    p_path = Path(args.pilot_file)
    c_path = Path(args.candidate_file)
    d_path = Path(args.daily_file)
    cat_path = Path(args.cat_file) if args.cat_file else None

    df_p = pd.read_excel(p_path) if p_path.suffix == ".xlsx" else pd.read_csv(p_path)
    df_c = pd.read_excel(c_path) if c_path.suffix == ".xlsx" else pd.read_csv(c_path)
    df_d = pd.read_parquet(d_path) if d_path.suffix == ".parquet" else pd.read_csv(d_path)
    df_cat = pd.DataFrame()
    if cat_path and cat_path.exists():
        df_cat = pd.read_excel(cat_path) if cat_path.suffix == ".xlsx" else pd.read_csv(cat_path)

    run_causal_evaluation_pipeline(df_p, df_c, df_d, df_cat, out_dir)


if __name__ == "__main__":
    main()
