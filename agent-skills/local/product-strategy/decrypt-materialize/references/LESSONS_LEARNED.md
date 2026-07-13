# Codex TSD 解密经验总结

## 问题发现

1. **症状误判**：最初以为是"加锁"，实际是 TSD 透明加密
2. **工具行为差异**：命令行 `sqlite3` 报错，但 Python sqlite3 能透明读取
3. **守护进程陷阱**：手动 kill 进程后自动重启，需要停止 launchd 服务

## 关键发现

### TSD 加密本质
- **磁盘格式**：加密二进制（`%TSD-Header-###%`）
- **应用层**：Python/应用通过 API 可透明读取
- **解密方法**：读取后写入新文件，自动变为标准格式
- **无需密钥**：透明加密，SQLite API 自动处理

### 工具兼容性
```
命令行 sqlite3  ✗  报错 "file is not a database (26)"
Python sqlite3  ✓  透明读取加密文件
openpyxl        ✗  不支持 .xls（只支持 .xlsx）
xlrd            ✓  支持旧 .xls 格式
```

### 进程管理
```
kill PID              → 进程重启（launchd 守护）
launchctl unload      → 停止守护进程
killall + unload      → 完全停止
```

## 技能改进点

### 1. 脚本 glob 模式失败
**问题**：`decrypt_codex.py` 的 `Path.glob()` 未找到文件
**原因**：可能是路径解析或模式匹配问题
**修复**：直接指定文件列表更可靠

### 2. 工作簿格式检测
**问题**：`.xls` 文件用 openpyxl 打开失败
**原因**：openpyxl 只支持 .xlsx，需要 xlrd 处理旧格式
**修复**：添加 `export_xls()` 函数，区分 `.xls` 和 `.xlsx`

### 3. 依赖管理
**问题**：全局 pip install 与项目环境不一致
**修复**：
- 添加 xlrd 到 `pyproject.toml`
- 使用 `uv run python` 确保环境一致

### 4. 进程检测不足
**问题**：只检测 `codex` 进程，漏掉 `codex-threadripper`
**修复**：`pgrep -i codex` 捕获所有相关进程

## 优化建议

### 脚本健壮性
```python
# 改进 1: 显式文件列表而非 glob
KNOWN_ENCRYPTED_FILES = [
    'goals_1.sqlite',
    'logs_2.sqlite',
    'memories_1.sqlite',
    'state_5.sqlite',
    'session_index.jsonl'
]

# 改进 2: 进程检测更全面
def check_codex_running():
    result = subprocess.run(
        ["pgrep", "-i", "codex"],  # -i 忽略大小写
        capture_output=True
    )
    # 不仅返回是否在运行，还返回进程名
```

### 文档结构优化
```
references/
├── CODEX_TSD.md          ✓ 新增，符合层级
├── WORKBOOK_PROCESS.md   ✓ 已有
├── SMUDGED_TEXT.md       ✓ 已有
└── TROUBLESHOOTING.md    △ 可新增：通用故障排查
```

### 完成标准可验证性
当前：
```
- [x] 命令行工具可访问解密文件
```

改进：
```
- [x] SQLite 文件头 = "SQLite format 3"（16 字节验证）
- [x] `sqlite3 <file> "SELECT 1"` 返回 0
- [x] JSONL 每行可 json.loads()
- [x] 备份文件存在且 > 0 字节
```

## 技能质量检查

### ✓ 做对的
1. **单一职责**：decrypt-materialize 聚焦"物化不透明文件"
2. **外部引用**：将详细流程放入 `references/CODEX_TSD.md`
3. **完成标准**：明确"加密文件被解密为标准格式，原文件已备份"
4. **示例驱动**：EXAMPLES.md 提供完整使用场景

### △ 可改进的
1. **duplication**："检查 Codex 进程"逻辑在文档和脚本中重复
   - 修复：脚本作为唯一真身，文档引用脚本行为
2. **no-op**："确保 Codex 已退出"在多处重复强调
   - 修复：合并为单一"前置条件"章节
3. **sprawl**：CODEX_TSD.md 160+ 行，可能过长
   - 考虑：是否需要拆分"故障排查"到独立文件

### ✗ 需修复的
1. **脚本 glob 失效**：已知问题，需改为显式列表
2. **缺少守护进程处理**：文档未提及 launchd unload
3. **验证不充分**：脚本返回成功但未验证文件头

## Leading Words 候选

- **透明加密** (transparent encryption)：TSD 的核心特征
- **物化** (materialize)：技能的核心动作（已用）
- **守护进程陷阱** (daemon trap)：进程管理的关键概念

## 下一步行动

1. **修复 decrypt_codex.py glob 问题**
2. **添加守护进程检测和停止逻辑**
3. **增强验证：检查文件头而非仅依赖 API 成功**
4. **压缩 CODEX_TSD.md**：移除重复，保留检查清单
5. **添加 TROUBLESHOOTING.md**：跨分支通用故障排查
