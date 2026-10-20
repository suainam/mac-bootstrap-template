# Tern 配置与快捷键

安装官方 Tern.app 到 `/Applications` 后，在父仓或模板仓运行 `make tern-sync`。首次启动前也可分发配置。完整 bootstrap 的 `install.sh` 已调用同一入口。Homebrew 的 `tern` 是其他工具，不要用它安装此终端。

```bash
make tern-sync          # 仓库配置分发到 Tern，建立 CLI 链接
make tern-status        # 检查配置；存在差异时返回非零
make tern-capture       # 将应用内修改保存到 private/terminals/tern/
make tern-sync FORCE=1  # 明确覆盖冲突，先创建带时间戳的备份
```

配置默认目录为 `~/Library/Application Support/Tern`，可通过 `TERN_CONFIG_DIR` 覆盖。私有源优先采用 `MAC_BOOTSTRAP_PRIVATE_DIR/terminals/tern`，否则使用父仓或模板内的 `private/terminals/tern`。私有文件整文件覆盖同名公共默认值，不做 JSON 合并。独立模板使用 capture 前设置 `MAC_BOOTSTRAP_PRIVATE_DIR`。

`managed.txt` 是唯一文件清单：settings（主题、字体、透明度、快捷键）、Carly SOUL、HEARTBEAT，以及可选私有 USER 和 tools.lua。capture 只采集这些文件。MEMORY、每日记忆、调度、账号、会话、插件和 omp 运行态不采集、不覆盖。机器路径与个人资料仅进入 private。

采用复制：Tern 原子重写配置会替换软链。首次遇到不同配置或发现应用内修改时，sync 拒绝覆盖并返回非零；先 capture 保留应用配置，或 FORCE=1 使用仓库配置。覆盖前备份到原路径的 `.bak.YYYYMMDD_HHMMSS`。分发时建议退出 Tern，完成后启动或重新加载设置。

快捷键先按 `Ctrl+A`，再按：

| 按键 | 动作 |
|---|---|
| `v` / `\` | 向右分屏 |
| `-` | 向下分屏 |
| `h/j/k/l` | 切换左/下/上/右 pane |
| `Shift+H/J/K/L` | 调整分屏尺寸 |
| `Shift+N/W/D` | 新建/重命名/关闭会话 |
| `Shift+T/X` | 重命名/关闭 tab |
| `b` / `w` / `g` | 侧栏 / Mission Control / 切换会话 |
| `s` / `?` / `r` | 设置 / 命令列表 / 重载配置 |
| `e` / `o` | scrollback / inbox |

冲突判断依赖 Tern 配置目录下的 `.mac-bootstrap.sha256`，记录上次分发内容的哈希。删除该文件等于放弃保护，下次 sync 遇到差异仍会先备份再覆盖。

2026-10-20：新增父子仓统一分发、配置采集和冲突保护。
