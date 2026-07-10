# Examples

## ADR — Architecture Decision

```bash
python scripts/record_knowledge.py \
  --type adr \
  --title "用 Rust 重写认证核心模块" \
  --content "## 决定
将 authentication 模块从 Python (FastAPI) 迁移到 Rust (Axum)。

## 理由
- 认证路径占整体 API 延迟的 40%，Python GC 引起的不稳定尾延迟
- Rust 的类型系统可以在编译期消除空指针和认证绕过漏洞

## 迁移策略
1. 新端点直接写 Rust，通过 sidecar 暴露 gRPC
2. 旧端点保持 Python，逐步迁移
3. 两套并行运行 2 周，验证无误后下线 Python 版本

## 评估
- 开发周期：2 周（含集成测试）
- 预期 P99 延迟：从 200ms 降至 30ms" \
  --background "用户问怎么提高认证系统性能，分析了 profiling 数据后发现 GC 是主瓶颈" \
  --tags "架构,Rust,性能优化,认证" \
  --impact high \
  --references "auth/main.py,auth/src/main.rs"
```

## Card — Knowledge Pattern

```bash
python scripts/record_knowledge.py \
  --type card \
  --title "macOS 上 Homebrew/Pyenv 共存时的 pip 问题" \
  --content "## 症状
`pip install` 后 `python -c \"import pkg\"` 报错 ModuleNotFoundError。

## 原因
Homebrew 的 Python 和 pyenv 的 Python 并存时，`pip install` 默认
安装到 Homebrew 的 site-packages，但 `python` 命令指向 pyenv。

## 解决
```
$ pyenv which pip     # 确认当前 pip 属于哪个 Python
$ pip install pkg     # 现在 install 到正确的 Python
```
或使用 `pip install --python /path/to/target/python`。",
  --background "用户说 'pip install 了 but 找不到模块'" \
  --tags "踩坑,Homebrew,Python,macOS" \
  --impact medium
```

## Daily — Notable Event

```bash
python scripts/record_knowledge.py \
  --type daily \
  --title "API 分页方案决策：由 offset/limit 改为 cursor-based" \
  --content "与后端团队确认：API 分页从 offset/limit 改为 cursor-based。
原因是在大量数据（100 万+ 行）下 offset 的性能退化严重。

新方案：cursor = base64({id, created_at})，客户端不感知编码细节。
后端团队将在下个 sprint 实施。前端需要配合修改分页组件。" \
  --background "今天讨论会上提出：用户请求第 1000 页时接口超时" \
  --tags "架构,API,性能" \
  --impact high \
  --references "docs/api-pagination.md"
```

## Script Path

The examples assume the working directory is the project root containing
`template/agent-skills/local/mac-bootstrap/knowledge-record/scripts/record-knowledge.py`.

From any agent directory (Codex, OpenCode, Claude):
```bash
python ~/work/config/mac-bootstrap/template/agent-skills/local/mac-bootstrap/knowledge-record/scripts/record_knowledge.py ...
```
