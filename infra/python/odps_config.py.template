"""
ODPS / MaxCompute 配置模板

使用方法：
  1. 推荐把真实文件放到 private/python/odps_config.py
  2. 运行 make render-configs 生成本地 python/odps_config.py
  3. 不要提交 python/odps_config.py 或任何真实 AK/SK

环境变量方式（推荐，避免密钥写文件）：
  export ODPS_ACCESS_ID=xxx
  export ODPS_ACCESS_KEY=xxx
  export ODPS_ENDPOINT=http://service.odps.aliyun.com/api
  export ODPS_PROJECT=my_project

跨平台路径：
  from pathlib import Path
  BASE = Path.home() / "work" / "data"
"""

from pathlib import Path

# ── 方式一：从环境变量读取（推荐） ──
import os

ACCESS_ID = os.environ.get("ODPS_ACCESS_ID")
ACCESS_KEY = os.environ.get("ODPS_ACCESS_KEY")
ENDPOINT = os.environ.get("ODPS_ENDPOINT", "http://service.odps.aliyun.com/api")
PROJECT = os.environ.get("ODPS_PROJECT")

# ── 方式二：直接填写（仅本地开发，不要提交 git） ──
# ACCESS_ID = "your_access_id"
# ACCESS_KEY = "your_access_key"
# ENDPOINT = "http://service.odps.aliyun.com/api"
# PROJECT = "your_project"

# ── SQL 模板目录 ──
SQL_TEMPLATES_DIR = Path(__file__).parent / "sql"

# ── 数据目录（跨平台） ──
DATA_DIR = Path.home() / "work" / "data"
TUNNEL_DIR = DATA_DIR / "odps_tunnel"
