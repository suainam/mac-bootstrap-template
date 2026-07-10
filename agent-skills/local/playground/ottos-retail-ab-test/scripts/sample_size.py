#!/usr/bin/env python3
"""线下零售 AB 实验样本量估算（门店级，两组等分）。

只需填业务参数，脚本算出所需门店数并判断够不够，无需理解统计公式。
仅用 Python 标准库，无需安装任何第三方包。

示例：
  # 已知门店间标准差 σ=18，要检测 +3 的提升，可用 200 家店
  python3 scripts/sample_size.py --sigma 18 --mde 3 --available 200

  # 不知道 σ，用基线值 × 变异系数估算（默认 cv=0.175）
  python3 scripts/sample_size.py --baseline 100 --mde 3 --available 200

  # 用相对提升表达 MDE（基线 100，预期提升 5%）
  python3 scripts/sample_size.py --baseline 100 --mde-rel 0.05 --available 400

  # 匹配对 / ANCOVA 降方差：填基线与实验期指标的相关系数 ρ
  python3 scripts/sample_size.py --sigma 18 --mde 3 --available 120 --rho 0.7
"""
import argparse
import math
from statistics import NormalDist


def main():
    ap = argparse.ArgumentParser(
        description="AB 实验样本量估算（两组等分，门店级）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--baseline", type=float, help="核心指标基线值（估 σ 或换算相对 MDE 时用）")
    ap.add_argument("--sigma", type=float, help="门店间标准差 σ；不填则用 baseline×cv 估算")
    ap.add_argument("--cv", type=float, default=0.175, help="变异系数，估 σ 用，默认 0.175（销售额绝对值类 15-20%% 中值；米效/坪效/动销率/转化率等比率型指标通常更低，填 0.08-0.12）")
    mde_grp = ap.add_mutually_exclusive_group(required=True)
    mde_grp.add_argument("--mde", type=float, help="最小可检测效应（绝对值，与基线同单位）")
    mde_grp.add_argument("--mde-rel", type=float, help="最小可检测效应（相对基线的比例，如 0.05=5%%）")
    ap.add_argument("--available", type=int, required=True, help="可用门店总数（两组合计）")
    ap.add_argument("--alpha", type=float, default=0.05, help="显著性水平，默认 0.05")
    ap.add_argument("--power", type=float, default=0.80, help="统计功效，默认 0.80")
    ap.add_argument("--sided", type=int, default=2, choices=[1, 2], help="单边/双边检验，默认 2（双边）")
    ap.add_argument("--rho", type=float, default=0.0,
                    help="基线与实验期指标的相关系数（匹配对/ANCOVA 降方差用，0-1，默认 0=不降方差）")
    args = ap.parse_args()

    # 确定门店间标准差 σ
    if args.sigma is not None:
        sigma = args.sigma
        sigma_src = f"用户直接提供 σ={sigma:g}"
    elif args.baseline is not None:
        sigma = args.baseline * args.cv
        sigma_src = f"由基线 {args.baseline:g} × cv {args.cv:g} 估得 σ={sigma:g}"
    else:
        ap.error("需提供 --sigma，或提供 --baseline 以按 cv 估算 σ")

    # 确定 MDE（统一换算成绝对值，与 σ 同单位）
    if args.mde is not None:
        mde = args.mde
        mde_src = f"绝对值 {mde:g}"
    else:
        if args.baseline is None:
            ap.error("--mde-rel 需同时提供 --baseline 以换算为绝对值")
        mde = args.baseline * args.mde_rel
        mde_src = f"基线 {args.baseline:g} × {args.mde_rel:g} = {mde:g}"

    if mde <= 0:
        ap.error("MDE 必须为正数")
    if not (0.0 <= args.rho < 1.0):
        ap.error("--rho 需在 [0, 1) 区间")

    z_alpha = NormalDist().inv_cdf(1 - args.alpha / args.sided)
    z_beta = NormalDist().inv_cdf(args.power)

    # 降方差因子（ANCOVA / 匹配对近似）：有效方差 = σ²(1-ρ²)
    sigma_eff = sigma * math.sqrt(1 - args.rho ** 2)

    n_per = (z_alpha + z_beta) ** 2 * 2 * sigma_eff ** 2 / mde ** 2
    n_per_ceil = math.ceil(n_per)
    n_total = n_per_ceil * 2
    avail_per = args.available // 2

    # 现有样本下能可靠检测到的最小提升幅度
    mde_detectable = (
        (z_alpha + z_beta) * math.sqrt(2 * sigma_eff ** 2 / avail_per)
        if avail_per > 0 else float("inf")
    )
    enough = avail_per >= n_per_ceil

    line = "=" * 50
    print(line)
    print("AB 实验样本量估算")
    print(line)
    print(f"σ（门店间标准差）：{sigma:g}   （{sigma_src}）")
    if args.rho > 0:
        print(f"降方差：ρ={args.rho:g} → 有效 σ={sigma_eff:g}（匹配对/ANCOVA）")
    print(f"MDE（最小可检测效应）：{mde:g}   （{mde_src}）")
    print(f"α={args.alpha:g}（{'双边' if args.sided == 2 else '单边'}）  功效={args.power:g}")
    print(f"  → Z={z_alpha:.3f}（α 项）  Z={z_beta:.3f}（功效项）")
    print("-" * 50)
    print(f"所需每组样本量：{n_per_ceil} 家门店   （精确 {n_per:.1f}）")
    print(f"所需总样本量：  {n_total} 家门店")
    print(f"可用每组样本量：{avail_per} 家门店   （可用总数 {args.available} ÷ 2）")
    print("-" * 50)
    if enough:
        print(f"[充足] 可用 {avail_per} ≥ 所需 {n_per_ceil}")
        print(f"       现有样本可可靠检测到 ≥ {mde_detectable:.3g} 的提升，优于目标 MDE {mde:g}")
    else:
        gap = n_per_ceil - avail_per
        print(f"[不足] 可用 {avail_per} < 所需 {n_per_ceil}，每组缺 {gap} 家")
        print(f"       现有 {avail_per} 家/组只能可靠检测到 ≥ {mde_detectable:.3g} 的提升")
        print("       常见应对（线下样本天然偏少，按业务情况选，不必都做）：")
        print("       ① 延长 AB 周期：多周平均降低波动，最省事")
        print("       ② 接受能测出的检测门槛：把门槛定在现有样本可靠检测的水平，与业务方说清")
        print("       ③ 扩大参与门店范围：让更多门店纳入实验 = 适度扩大试点/推广覆盖面")
        print("       ④ 匹配对/ANCOVA 降方差（--rho）：想更省样本时的进阶选项")
    print(line)


if __name__ == "__main__":
    main()
