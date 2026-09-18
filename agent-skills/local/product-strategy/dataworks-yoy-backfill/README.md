# DataWorks Workflow Snapshot & Batch Backfill Skill

独立可分享的 DataWorks 工作流拓扑拉取与批量回刷工具。

---

## 🚀 快速开始

### 1. 安装依赖

```bash
# 方式 A：使用 pip（独立环境）
cd ~/.omp/agent/skills/dataworks-yoy-backfill
pip3 install -r requirements.txt

# 方式 B：使用 uv（推荐，在专题仓库中）
cd ~/work/projects/product_strategy
uv sync --extra lineage
```

### 2. 配置凭据

创建 `.env` 文件或设置环境变量：

```bash
export ODPS_ACCESS_ID=your_access_key_id
export ODPS_SECRET_KEY=your_secret_key
export DATAWORKS_ENDPOINT=dataworks.cn-shenzhen.aliyuncs.com
export ODPS_ENDPOINT=https://service.cn-shenzhen.maxcompute.aliyun.com/api
```

或在以下任一位置放置 `.env` 文件（脚本按优先级自动加载）：
- `~/work/projects/www/marimo/merchandise/.env`
- `~/work/config/shared/.env`
- `~/work/projects/product_strategy/.env`

### 3. 拉取工作流快照

```bash
cd ~/.omp/agent/skills/dataworks-yoy-backfill/scripts

python3 dataworks_snapshot.py \
  --project-id 175690 \
  --env PROD \
  --workflow-id 10002308897 \
  --node-ids 10002308898,10002308899 \
  --cache /tmp/wf_cache.json \
  --schemas-cache /tmp/wf_schemas.json \
  --out ~/Downloads/workflow_snapshot_$(date +%Y%m%d).md
```

### 4. 查询表血缘

```bash
python3 dataworks_lineage.py \
  --table dsl_ads.ads_item_content_store_all_stat \
  --direction up \
  --depth 3
```

---

## 📦 目录结构

```
dataworks-yoy-backfill/
├── README.md                     # 本文档（快速上手）
├── SKILL.md                      # 完整技能文档（能力说明、范式、反模式）
├── requirements.txt              # Python 依赖清单
├── scripts/
│   ├── dataworks_snapshot.py     # 工作流快照拉取（增量/断点续传）
│   ├── dataworks_lineage.py      # 表级血缘追踪
│   ├── dataworks_batch_backfill.py  # 批量分区回刷编排
│   └── workflow_snapshot_core.py    # 纯函数核心库
├── templates/
│   └── backfill_config.yaml      # 配置模板
└── examples/
    ├── smart_assortment_case.md  # 智能组货实战案例
    └── WORKFLOW_SNAPSHOT_GUIDE.md # 详细指引
```

---

## 🎯 核心能力

### ① 工作流快照
- **增量比对**：云端 `ModifyTime` 未变跳过耗时的 `GetNodeCode`
- **断点续传**：每节点拉完立即写缓存，网络中断重跑自动续传
- **真实 DDL**：从 MaxCompute 元数据拼装标准 `CREATE TABLE` DDL
- **拓扑图**：自动生成 Mermaid 工作流架构图

### ② 表级血缘
- 递归查询 MaxCompute / DataWorks 表的上下游依赖
- 生成 Markdown 依赖列表与 Mermaid 流程图

### ③ 批量回刷
- **不使用 DataWorks DAG**（3min/天）→ MaxCompute SDK 直接提交（~6s/天）
- **分区存在性预检**：已存在分区自动跳过（断点续传）
- **倒序执行**：按季度切片，新→旧，优先验证新分区
- **16 并发**：628 天全量回刷约 25-30 分钟

---

## 📋 典型流程

1. **拉取工作流快照** → 确认节点 SQL、调度参数、产出表 DDL、血缘拓扑
2. **识别漂移问题** → 对比 YoY 可比口径，发现门店池不一致
3. **修复 SQL 逻辑** → 在预聚合层固定同店基准（昨日快照）
4. **批量回刷历史分区** → 并发回刷（16 并发，按季度切片，断点续传）
5. **验证结果** → ODPS 实查门店配对率 99.96%+

---

## 🔧 专题集成示例

在专题仓库脚本中引用：

```python
from pathlib import Path
import sys

# 引入 skill 脚本路径
skill_path = Path.home() / ".omp/agent/skills/dataworks-yoy-backfill/scripts"
sys.path.insert(0, str(skill_path))

from dataworks_batch_backfill import run_batch
from dataworks_snapshot import make_odps, make_dw_client

# 定义季度窗口
QUARTERS = [
    ("2026 Q3", "20260701", "20260809"),
    ("2026 Q2", "20260401", "20260630"),
]

# 定义单日 SQL 构建函数
def build_sql(stat_date: int) -> str:
    return f"""
WITH base AS (SELECT * FROM source WHERE stat_date = {stat_date})
INSERT OVERWRITE TABLE target PARTITION (stat_date = {stat_date})
SELECT * FROM base;
"""

# 执行批量回刷
for q_name, start, end in QUARTERS:
    result = run_batch(
        quarter_name=q_name,
        start_date=start,
        end_date=end,
        sql_builder=build_sql,
        partition_tables=["target"],
        odps_project="dsl_analysis",
        workers=16,
    )
    print(f"✓ {q_name}: {result}")
```

---

## 📚 详细文档

- **完整技能文档**：`SKILL.md`（能力说明、YoY 修复范式、反模式、完成标准）
- **工作流快照指引**：`examples/WORKFLOW_SNAPSHOT_GUIDE.md`
- **实战案例**：`examples/smart_assortment_case.md`（智能组货 628 天回刷）

---

## 🎁 分享此 Skill

```bash
# 打包
cd ~/.omp/agent/skills/
tar -czf ~/Downloads/dataworks-yoy-backfill-skill.tar.gz dataworks-yoy-backfill/

# 接收方解压
tar -xzf dataworks-yoy-backfill-skill.tar.gz -C ~/.omp/agent/skills/

# 安装依赖
cd ~/.omp/agent/skills/dataworks-yoy-backfill
pip3 install -r requirements.txt

# 配置凭据后即可使用
export ODPS_ACCESS_ID=xxx
export ODPS_SECRET_KEY=yyy
python3 scripts/dataworks_snapshot.py --help
```

---

## ⚠️ 依赖说明

- Python 3.9+
- `alibabacloud-dataworks-public20200518` ≥10.1.0
- `alibabacloud-tea-openapi` ≥0.4.6
- `pyodps` ≥0.11.0

---

## 📞 反馈

遇到问题或有改进建议，欢迎通过以下方式反馈：
- 在 OMP/Codex 对话中提及此 skill
- 更新 `SKILL.md` 后重新分享
