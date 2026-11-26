---
name: dashenlin-ppt-polish
description: Use when editing or reviewing DaShenLin annual or quarterly review slides, or merging and exporting approved slide lanes in product_strategy.
---

# 大参林述职 PPT

按页校对、预览、确认。以当前磁盘稿为基线。项目工具位于 `topics/smart_assortment/04_outputs/ppt_master/templates/dashenlin/`，从仓库根目录运行命令。

1. **锁定基线。** 核对目标文件、版本、页码和合并负责人。用户刚保存过 PPTX 时，检查 `xxd -l 16 <file.pptx>`；遇到 `%TSD-Header-###%`，按 `decrypt-materialize` 的调用规则取得可读副本。用 `scripts/page_lane.py status <workspace> --slides <页码>` 检查已有 lane，复用当前 lane 或用 `extract <workspace> --slides <页码>` 抽页。完成条件：目标页和备注可读，lane 基线对应当前工作区，素材相对路径可解析。
2. **核数、定主张、改页面。** 数字变更先列跨页对照，核对指标、值、单位、范围、截至时间和来源；以当前生产运行态与用户最新口径为准，淘汰文档中过时的“未上线/未验收”旧边界。用 claim-first 把核心结论与量化值放进顶部横幅，用 SMART 检查范围、业务动作、结果和时间，用 humanizer-zh 改成评委能直接理解的业务语言（技术平台页同样去工程黑话）。把计算口径放在页脚或备注。区分已完成成果和计划，AI 提效写已证实的交付，有实测才写节省时间。按分工编辑 `slide.svg` 和 `note.md`。完成条件：每页一个主张，每个数字和时间可追溯，跨页相同口径一致。
3. **审核、渲染、预览。** 从仓库根目录运行技能目录下的 `scripts/preview-lane.sh <lane_dir>`。打开生成的 `preview.png`，核查图像加载、比例、遮挡、截断、留白和字号；正文至少 14px，每卡要点精炼（通常不超过 3 条），朱红每卡最多两处。先发 PNG，再发 SVG。完成条件：`audit-svg --check-copy` 为 0 违规，实看 PNG 无显示缺陷，用户收到两种预览。
4. **确认、交接、合并。** 用户确认后，交给约定的合并负责人，附页码、lane 路径、主要变更、已跑检查和待核对项。负责合并时先查 lane 状态；基线已变则先对齐修改，再用 `merge <workspace> --slides <页码>` 合入。完成条件：交接有发送证据；如果本轮负责交付，正式稿通过下述发布检查并记录版本。

## 按需读取

- **布局**：改横幅、卡片、图表和母版时，读项目工具目录的 `PLAYBOOK.md`「Visual Design & Layout Craft」和 `templates/` 中的品牌与版式规范。
- **黄金案例**：改策略归因、平台截图或有计划里程碑时，读 [案例索引](references/golden-cases.md)。案例用来借鉴页面结构，数字以本轮来源为准。
- **发布**：合并并导出整套 PPTX 时，按 `PLAYBOOK.md` 的整稿流程执行。刷新 authoring summary，完成 round-trip SVG 检查及导出（若插入新页，先重算 `rebuilt_slides` 再 `apply-pingfang`），跑 PPTX 交付检查与 `audit-pptx`，执行 `.venv/bin/pytest -v topics/smart_assortment/tests/test_ppt_master_dashenlin.py` 和 `make repo-check`，并复核导出后的关键页。
