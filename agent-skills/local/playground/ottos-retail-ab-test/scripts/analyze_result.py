#!/usr/bin/env python3
"""线下零售 AB 实验结果分析（门店级，实验结束后用）。

输入实验组、对照组两组门店的指标数据，脚本跑 t 检验算出 p 值和提升幅度，
再对照「显著性 + 是否达到预期提升幅度」给出结论。只用 Python 标准库，无需第三方包。

两组数据的给法（二选一）：
  · 文件：每行一个数值（表头/空行自动跳过）
  · 命令行：逗号分隔的一串数值

示例：
  # 文件输入，独立两组，判断是否达到 +3 的推广门槛
  python3 scripts/analyze_result.py --treatment t.csv --control c.csv --mde 3

  # 命令行直接给数值（适合匹配对等小样本）
  python3 scripts/analyze_result.py \
      --treatment-values 105,110,108,112,107 \
      --control-values   100,98,102,99,101 --mde 3

  # 匹配对设计：两组一一对应，用配对 t 检验
  python3 scripts/analyze_result.py --treatment t.csv --control c.csv --paired --mde 3

  # 用相对提升表达门槛（对照组均值为基线，预期 +5%）
  python3 scripts/analyze_result.py --treatment t.csv --control c.csv --mde-rel 0.05
"""
import argparse
import math
from statistics import mean, stdev


# ---------- t 分布 p 值：正则化不完全贝塔函数（零依赖，小样本也精确） ----------

def _betacf(a, b, x):
    MAXIT, EPS, FPMIN = 300, 3e-16, 1e-300
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < FPMIN:
        d = FPMIN
    d = 1.0 / d
    h = d
    for m in range(1, MAXIT + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < FPMIN:
            d = FPMIN
        c = 1.0 + aa / c
        if abs(c) < FPMIN:
            c = FPMIN
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < FPMIN:
            d = FPMIN
        c = 1.0 + aa / c
        if abs(c) < FPMIN:
            c = FPMIN
        d = 1.0 / d
        de = d * c
        h *= de
        if abs(de - 1.0) < EPS:
            break
    return h


def _betai(a, b, x):
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    lbeta = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
    bt = math.exp(lbeta + a * math.log(x) + b * math.log(1.0 - x))
    if x < (a + 1.0) / (a + b + 2.0):
        return bt * _betacf(a, b, x) / a
    return 1.0 - bt * _betacf(b, a, 1.0 - x) / b


def t_two_sided_p(t, df):
    """双边 p 值 = P(|T| > |t|)。"""
    if df <= 0:
        return float("nan")
    x = df / (df + t * t)
    return _betai(df / 2.0, 0.5, x)


# ---------- 数据读取 ----------

def parse_values(file_path, inline):
    if inline is not None:
        return [float(v) for v in inline.split(",") if v.strip() != ""]
    vals = []
    with open(file_path, encoding="utf-8-sig") as f:
        for row in f:
            cell = row.strip().split(",")[0].strip()
            if cell == "":
                continue
            try:
                vals.append(float(cell))
            except ValueError:
                continue  # 跳过表头等非数值行
    return vals


# ---------- 检验 ----------

def welch_ttest(t_vals, c_vals):
    n1, n2 = len(t_vals), len(c_vals)
    m1, m2 = mean(t_vals), mean(c_vals)
    v1, v2 = stdev(t_vals) ** 2, stdev(c_vals) ** 2
    se = math.sqrt(v1 / n1 + v2 / n2)
    t = (m1 - m2) / se
    df = (v1 / n1 + v2 / n2) ** 2 / (
        (v1 / n1) ** 2 / (n1 - 1) + (v2 / n2) ** 2 / (n2 - 1)
    )
    return t, df, m1, m2


def paired_ttest(t_vals, c_vals):
    n = len(t_vals)
    diffs = [a - b for a, b in zip(t_vals, c_vals)]
    md = mean(diffs)
    sd = stdev(diffs)
    t = md / (sd / math.sqrt(n))
    return t, n - 1, mean(t_vals), mean(c_vals)


def main():
    ap = argparse.ArgumentParser(
        description="AB 实验结果分析（t 检验 + 结论判断，门店级）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--treatment", help="实验组数据文件（每行一个数值）")
    ap.add_argument("--treatment-values", help="实验组数值，逗号分隔")
    ap.add_argument("--control", help="对照组数据文件（每行一个数值）")
    ap.add_argument("--control-values", help="对照组数值，逗号分隔")
    ap.add_argument("--paired", action="store_true", help="匹配对设计，用配对 t 检验（两组需一一对应、等长）")
    mde_grp = ap.add_mutually_exclusive_group()
    mde_grp.add_argument("--mde", type=float, help="预期提升幅度门槛（绝对值，与指标同单位）")
    mde_grp.add_argument("--mde-rel", type=float, help="预期提升幅度门槛（相对对照组均值的比例，如 0.05=5%%）")
    ap.add_argument("--alpha", type=float, default=0.05, help="显著性水平，默认 0.05")
    ap.add_argument("--sided", type=int, default=2, choices=[1, 2], help="单边/双边，默认 2（双边）")
    ap.add_argument("--required-per-group", type=int,
                    help="每组所需样本量（来自 sample_size.py），用于判断'证据不足'是否因样本不够")
    args = ap.parse_args()

    t_vals = parse_values(args.treatment, args.treatment_values)
    c_vals = parse_values(args.control, args.control_values)
    if len(t_vals) < 2 or len(c_vals) < 2:
        ap.error("每组至少需要 2 个数值")
    if args.paired and len(t_vals) != len(c_vals):
        ap.error(f"配对检验要求两组等长：实验组 {len(t_vals)} ≠ 对照组 {len(c_vals)}")

    if args.paired:
        t, df, m1, m2 = paired_ttest(t_vals, c_vals)
        method = "配对 t 检验（匹配对设计）"
    else:
        t, df, m1, m2 = welch_ttest(t_vals, c_vals)
        method = "Welch t 检验（独立两组，不要求等方差）"

    effect = m1 - m2  # 实验组 - 对照组，绝对提升
    rel = effect / m2 if m2 != 0 else float("nan")

    p_two = t_two_sided_p(t, df)
    if args.sided == 2:
        p = p_two
    else:  # 单边 H1：实验组 > 对照组
        p = p_two / 2 if t > 0 else 1 - p_two / 2

    # 门槛 MDE（绝对值）
    mde = None
    if args.mde is not None:
        mde = args.mde
    elif args.mde_rel is not None:
        mde = m2 * args.mde_rel

    line = "=" * 50
    print(line)
    print("AB 实验结果分析")
    print(line)
    print(f"检验方法：{method}")
    print(f"实验组：n={len(t_vals)}  均值={m1:.4g}  标准差={stdev(t_vals):.4g}")
    print(f"对照组：n={len(c_vals)}  均值={m2:.4g}  标准差={stdev(c_vals):.4g}")
    print("-" * 50)
    print(f"提升幅度：{effect:+.4g}（绝对）  {rel:+.2%}（相对对照组）")
    print(f"t={t:.3f}  df={df:.1f}  p={p:.4g}（{'双边' if args.sided == 2 else '单边'}）")
    if mde is not None:
        print(f"推广门槛 MDE：{mde:.4g}")
    print("-" * 50)

    sig = p < args.alpha
    n_min = min(len(t_vals), len(c_vals))
    underpowered = args.required_per_group is not None and n_min < args.required_per_group
    if not sig:
        if underpowered:
            verdict = (
                f"[证据不足·样本不够] p ≥ α，但每组仅 {n_min} 家 < 所需 {args.required_per_group} 家，"
                "很可能是样本不足没测出来、而非方案无效\n"
                "       → 延长周期或扩大参与门店范围补足样本后复测，先不要判定方案无效"
            )
        else:
            verdict = "[证据不足] p ≥ α，不能确认新方案有效 → 不推广，维持原方案"
    elif effect < 0:
        verdict = "[负向] 显著但方向为负，新方案更差 → 放弃该方案"
    elif mde is None:
        verdict = f"[显著正向] 提升 {effect:+.4g} 且统计显著；是否达推广门槛需对照 MDE（本次未提供 --mde）"
    elif effect >= mde:
        verdict = f"[有效] 显著且提升 {effect:.4g} ≥ 门槛 {mde:.4g} → 达到推广门槛，可推广"
    else:
        verdict = f"[幅度不足] 提升真实（显著）但 {effect:.4g} < 门槛 {mde:.4g} → 按 2.8 评估是否值得推"
    print(verdict)
    print(line)


if __name__ == "__main__":
    main()
