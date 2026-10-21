# 软件包管理指引

## 原则

**单一包管理器**：所有 CLI 工具、语言运行时与图形应用统一由 **Homebrew** 管理。

- **全局通用**：`template/Brewfile`（如 `git`、`ripgrep`、`docker`、`uv`、`gh`、`rtk`、`ghostty`）
- **work 机器专属**：`private/profiles/work/Brewfile`（如 `tea`、`lrzsz`、企业通讯工具）
- **home 机器专属**：`private/profiles/home/Brewfile`（如 `rclone`、`rustic`）
- **实验性**：`private/experimental/Brewfile`

机器在执行安装时通过 `scripts/resolve-profile.sh` 自动判定所属 profile，仅加载对应的 Brewfile 声明，不会发生跨机器污染。

---

## 添加与移除软件

### 添加软件

1. 在对应 profile 的 `Brewfile` 中添加 `brew` 或 `cask` 声明。
2. 运行同步：

```bash
make bootstrap              # 首次或整体配置
# 或
./scripts/brew-bundle.sh install   # 仅同步包
```

### 移除软件

1. 从对应的 `Brewfile` 中删除条目。
2. 执行卸载：

```bash
brew uninstall <formula>
# 或
brew uninstall --cask <cask>
```

---

## 回迁 Homebrew（Cutover Migration）

系统已从历史的 Zerobrew (zb) 隔离方案完整切回纯 Homebrew 架构。在旧机器或尚未完成回迁的环境中，使用统一幂等命令执行回迁：

```bash
make package-migrate
# 或
./scripts/brew-bundle.sh migrate
```

### 回迁执行保障

1. **动态候选探测**：根据机器当前实际安装的 Zerobrew 软件包与对应 profile 的 Brewfile 动态计算迁移集合，避免将 home 的专属工具（如 `rclone`、`rustic`）装到 work。
2. **绝对路径验证**：替代工具在 Homebrew 安装后，必须通过 `/opt/homebrew/bin/<tool>` 绝对路径严格验证版本或帮助输出。若任意工具验证未通过，绝不提前卸载旧副本。
3. **Docker CLI 插件重链**：仅当对应 Homebrew 插件通过验证后，才将 `~/.docker/cli-plugins/docker-compose` 与 `docker-buildx` 指向 Homebrew 路径；未验证时保留原链接。
4. **服务与环境变量平滑切换**：`rclone` / `rustic` 验证成功后，才将 `com.auroraops.rclone-webdav` 与 `rustic` 等后台服务的 ProgramArguments 及 PATH 切换至 `/opt/homebrew/bin` 并重新加载；shell dotfiles 移除 `/opt/zerobrew` 优先注入。
5. **可重入与安全移除**：仅在对应 Homebrew 工具验证成功后才从 Zerobrew 卸载对应条目；卸载失败或验证失败都会让迁移以非零退出码结束，不会打印成功结论。

---

## 检查清单

变更或迁移后运行：

- [ ] `make doctor` 通过
- [ ] 关键二进制可执行且指向 Homebrew：`command -v <tool> && which <tool>` 输出 `/opt/homebrew/bin/<tool>`
- [ ] Docker 插件正常：`docker compose version && docker buildx version`
- [ ] 后台服务正常：`launchctl list | grep -E 'rclone|rustic'`
- [ ] `test_declared_brew_formulas_are_installed` 检查通过

---

## 参考

- [private-overlay.md](./private-overlay.md)：私有覆盖层与机器 profile 说明
- [manual-apps.md](./manual-apps.md)：手动管理的图形应用列表
- `scripts/brew-bundle.sh`：包安装与迁移触发入口
- `scripts/migrate-to-homebrew.sh`：回迁具体执行实现
- `scripts/run-doctor-checks.py`：健康检查实现
