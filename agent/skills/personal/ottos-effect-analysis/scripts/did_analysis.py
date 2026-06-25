#!/usr/bin/env python3
"""
DID（双重差分）净效果计算 —— 效果分析专用计算封装。

用途：匹配对照门店做事后归因时，把"试点门店前后变化 - 对照门店前后变化"算成净效果，
并给出显著性、置信区间、符号检验，以及 DID 成立的前提——平行趋势检验的结论。
使用者只需准备业务数据（每对门店的上线前/后均值），不需要懂统计细节。

输入：一个 JSON 文件，结构见 references/methods.md 或下方 EXAMPLE。
输出：人类可读摘要 + 结构化 JSON（--json 时仅输出 JSON，便于喂给报告脚本）。

用法：
    python3 did_analysis.py input.json
    python3 did_analysis.py input.json --json > did_result.json
"""
import sys
import json
import math
import statistics
import subprocess

EXAMPLE = {
    "metric": "米效",
    "unit": "元/米/天",
    "baseline_period": "上线前3个月",
    "metric_type": "amount",
    "alpha": 0.05,
    "pairs": [
        {"pair_id": 1, "t_pre": 85, "t_post": 92, "c_pre": 86, "c_post": 88},
        {"pair_id": 2, "t_pre": 88, "t_post": 95, "c_pre": 87, "c_post": 90},
    ],
    "parallel_trend": {
        "periods": ["M-6", "M-5", "M-4", "M-3", "M-2", "M-1"],
        "treatment_mean": [80, 81, 83, 84, 85, 85],
        "control_mean": [81, 82, 83, 85, 86, 86],
    },
}


def _ensure_scipy():
    """显著性检验依赖 scipy；不可用则自动安装。"""
    try:
        import scipy  # noqa: F401
        return True
    except ImportError:
        subprocess.run([sys.executable, "-m", "pip", "install", "scipy", "-q"], check=False)
        try:
            import scipy  # noqa: F401
            return True
        except ImportError:
            return False


def did_core(pairs, alpha=0.05, metric_type="amount"):
    """每对门店的 DiD = (t_post - t_pre) - (c_post - c_pre)，聚合后做配对检验。
    metric_type："amount"（金额/数量型，额外报相对基线的百分比）或
    "rate"（比率/百分点型，如动销率、毛利率——只报绝对百分点差，不算相对百分比，
    避免把 +3pp 误说成 +7%；此时数据按百分点数值填，如 42 而非 0.42）。"""
    dids = [(p["t_post"] - p["t_pre"]) - (p["c_post"] - p["c_pre"]) for p in pairs]
    n = len(dids)
    mean = statistics.mean(dids)
    baseline = statistics.mean([p["t_pre"] for p in pairs])  # 以试点上线前均值为基线
    pct = None if metric_type == "rate" else (mean / baseline if baseline else None)

    result = {
        "n_pairs": n,
        "metric_type": metric_type,
        "net_effect": round(mean, 4),
        "net_effect_pct": round(pct, 4) if pct is not None else None,
        "baseline_mean": round(baseline, 4),
        "per_pair_did": [round(d, 4) for d in dids],
        "positive_pairs": sum(1 for d in dids if d > 0),
    }

    if n < 2:
        result["note"] = "门店对数不足 2，无法做显著性检验，只看方向。"
        return result

    sd = statistics.stdev(dids)
    se = sd / math.sqrt(n)
    result["std"] = round(sd, 4)
    result["se"] = round(se, 4)

    if _ensure_scipy() and se > 0:
        from scipy import stats
        t_stat, p_val = stats.ttest_1samp(dids, 0.0)
        t_crit = stats.t.ppf(1 - alpha / 2, n - 1)
        ci_low, ci_high = mean - t_crit * se, mean + t_crit * se
        result.update({
            "t_stat": round(float(t_stat), 4),
            "p_value": round(float(p_val), 4),
            "significant": bool(p_val < alpha),
            "ci_95": [round(float(ci_low), 4), round(float(ci_high), 4)],
        })
        # 符号检验（单侧）：小样本时 t 检验难显著，看"同向比例"更稳健。
        # 取多数方向的门店数 k，算"在零假设 p=0.5 下出现 k 个及以上同向"的上尾概率。
        k = max(result["positive_pairs"], n - result["positive_pairs"])
        sign_p = sum(math.comb(n, i) for i in range(k, n + 1)) / (2 ** n)
        result["sign_test"] = {
            "same_direction": f"{result['positive_pairs']}/{n}",
            "p_value_one_sided": round(sign_p, 4),
        }
    else:
        result["note"] = "scipy 不可用或方差为 0，未做显著性检验。"
    return result


def parallel_trend(pt, alpha=0.05):
    """平行趋势检验：上线前两组的差距 gap=试点-对照 对时间回归，斜率不显著=趋势平行。"""
    if not pt:
        return {"checked": False, "verdict": "未提供上线前历史数据，无法检验平行趋势——DID 结论可信度需下调。"}
    t = pt["treatment_mean"]
    c = pt["control_mean"]
    gap = [a - b for a, b in zip(t, c)]
    x = list(range(len(gap)))
    out = {"checked": True, "n_periods": len(gap), "gap_series": [round(g, 4) for g in gap]}
    if len(gap) < 3:
        out["verdict"] = "上线前历史点少于 3 个，平行趋势检验不可靠，建议至少 6 个月历史。"
        return out
    if _ensure_scipy():
        from scipy import stats
        reg = stats.linregress(x, gap)
        slope, pval = reg.slope, reg.pvalue
        # gap 几乎恒定时 linregress 的 p 值为 nan（残差≈0）——这恰是理想平行，不能误判成不平行
        if pval != pval:  # NaN
            out["gap_slope"] = round(slope, 4) if slope == slope else 0.0
            out["slope_p_value"] = None
            out["parallel_ok"] = True
            out["verdict"] = "上线前两组差距基本恒定（无趋势），平行趋势成立，可用 DID。"
        else:
            out["gap_slope"] = round(slope, 4)
            out["slope_p_value"] = round(pval, 4)
            out["parallel_ok"] = bool(pval >= alpha)
            if pval >= alpha:
                out["verdict"] = "上线前两组差距随时间无显著变化，平行趋势成立，可用 DID。"
            else:
                out["verdict"] = ("上线前两组差距随时间显著变化（斜率 p<%.2f），趋势不平行——"
                                  "这对匹配不可用，需重选对照门店；普遍不平行则改用同比+区域对比并下调可信度。" % alpha)
    else:
        out["verdict"] = "scipy 不可用，未做平行趋势回归。"
    return out


def render(data, res, pt_res):
    L = []
    L.append(f"# DID 净效果分析 —— {data.get('metric','指标')}（{data.get('unit','')}）")
    L.append("")
    L.append(f"匹配门店对数：{res['n_pairs']}")
    eff = res["net_effect"]
    pct = res.get("net_effect_pct")
    if res.get("metric_type") == "rate":
        L.append(f"净效果：{eff:+.2f} {data.get('unit','pp')}（比率型，按百分点；不另算相对百分比）")
    else:
        pct_s = f"（按基线约 {pct*100:+.1f}%）" if pct is not None else ""
        L.append(f"净效果：{eff:+.2f} {data.get('unit','')} {pct_s}")
    L.append(f"基线（试点上线前均值）：{res['baseline_mean']}")
    L.append(f"同向门店：{res['positive_pairs']}/{res['n_pairs']}")
    if "p_value" in res:
        sig = "显著" if res["significant"] else "不显著"
        L.append(f"配对 t 检验：t={res['t_stat']}，p={res['p_value']}（{sig}），95% 置信区间 {res['ci_95']}")
        st = res["sign_test"]
        L.append(f"符号检验（单侧，小样本更稳健）：同向 {st['same_direction']}，p={st['p_value_one_sided']}")
    if res.get("note"):
        L.append(f"提示：{res['note']}")
    L.append("")
    L.append("## 平行趋势检验（DID 成立前提）")
    L.append(pt_res["verdict"])
    if pt_res.get("gap_slope") is not None:
        p = pt_res.get("slope_p_value")
        ps = f"，p={p}" if p is not None else ""
        L.append(f"上线前差距斜率：{pt_res['gap_slope']}{ps}")
    return "\n".join(L)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    as_json = "--json" in sys.argv
    if not args:
        print("用法：python3 did_analysis.py input.json [--json]", file=sys.stderr)
        print("\n输入 JSON 示例：", file=sys.stderr)
        print(json.dumps(EXAMPLE, ensure_ascii=False, indent=2), file=sys.stderr)
        sys.exit(1)
    with open(args[0], encoding="utf-8") as f:
        data = json.load(f)
    alpha = data.get("alpha", 0.05)
    res = did_core(data["pairs"], alpha, data.get("metric_type", "amount"))
    pt_res = parallel_trend(data.get("parallel_trend"), alpha)
    out = {"input_meta": {k: data.get(k) for k in ("metric", "unit", "baseline_period")},
           "did": res, "parallel_trend": pt_res}
    if as_json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        print(render(data, res, pt_res))


if __name__ == "__main__":
    main()
