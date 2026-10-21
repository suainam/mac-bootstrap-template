# 软件包管理指引

## 原则

**单一归属**：每个 formula 仅由一个包管理器安装，避免重复管理。

- **Homebrew (brew)**：默认归属，适用于大部分工具、图形应用和依赖库
- **Zerobrew (zb)**：可选的版本隔离前缀，适用于需要冻结版本或避免 Homebrew 升级影响的工具（如 `docker`、`gh`、`rtk`）

归属声明位于 [`scripts/package-ownership.json`](../scripts/package-ownership.json) 的 `zerobrew_formulas` 列表；未声明的 formula 默认归 Homebrew。

**不要根据当前机器的安装状态修改归属清单**，它是跨机器的策略配置，不是安装记录。

---

## 添加新软件

### 1. 确定归属

多数情况选择 **Homebrew**。仅在以下场景使用 Zerobrew：

- 需要冻结版本（如 Docker CLI 固定在某个与 Colima 兼容的版本）
- 工具有频繁的不兼容升级（如某些 CLI 破坏脚本）
- 需要在同一系统维护不同版本隔离实例

### 2. 声明安装

编辑对应 profile 的 `Brewfile`：

- **全局**：`template/Brewfile`
- **work 机器**：`private/profiles/work/Brewfile`
- **home 机器**：`private/profiles/home/Brewfile`
- **实验性**：`private/experimental/Brewfile`

```ruby
# Homebrew formula
brew "ripgrep"

# Zerobrew formula (还需更新 package-ownership.json)
brew "docker"

# Homebrew cask
cask "visual-studio-code"
```

### 3. 更新归属清单（仅 Zerobrew）

如果选择 Zerobrew，同时编辑 `template/scripts/package-ownership.json`：

```json
{
  "zerobrew_formulas": [
    "docker",
    "gh",
    "your-new-tool"
  ]
}
```

### 4. 安装

```bash
make bootstrap              # 首次机器配置
# 或
./scripts/brew-bundle.sh install   # 仅同步包
```

---

## 移除软件

### 1. 移除声明

从对应 profile 的 `Brewfile` 删除条目。

### 2. 更新归属清单（如适用）

如果是 Zerobrew formula，同时从 `package-ownership.json` 移除。

### 3. 卸载

```bash
brew uninstall <formula>
# 或
zb uninstall <formula>
```

---

## 变更归属（Homebrew ↔ Zerobrew）

**场景**：已安装的 formula 需要从一个管理器迁移到另一个。

### 自动迁移（推荐）

1. 更新 `package-ownership.json`（添加或移除目标 formula）
2. 运行迁移命令：

```bash
make package-migrate
# 或
./scripts/brew-bundle.sh migrate
```

迁移逻辑：

- 检查依赖关系（`brew uses --installed`），有其他包依赖则中止
- 在目标管理器安装并验证二进制
- 从源管理器卸载
- Docker 插件会自动重新链接到新路径

### 手动迁移（恢复场景）

适用于自动迁移失败或需要回退的情况：

```bash
# 1. 在目标管理器安装
brew install docker   # 或 zb install docker

# 2. 验证可用性
command -v docker
docker --version

# 3. 处理特殊依赖（如 Docker 插件）
# 确保 $DOCKER_CONFIG/cli-plugins 中的符号链接指向正确路径
ls -la ~/.docker/cli-plugins/

# 4. 从源管理器卸载
zb uninstall docker   # 或 brew uninstall docker

# 5. 运行检查
make doctor
```

---

## 日常维护

### 升级所有包

```bash
make system-upgrade            # 完整系统升级（包 + 技能 + 配置）
make system-upgrade UPGRADE_ONLY=packages  # 仅升级包
```

`system-upgrade` 自动处理：

- Homebrew 包：`brew update && brew upgrade`
- Zerobrew 包：`zb upgrade`
- 手动安装的图形应用跳过（如 `microsoft-edge`、`zed`、`grok-bot`）

### 检查状态

```bash
make doctor                    # 完整健康检查
brew list --formula            # Homebrew 已安装 formula
zb list                        # Zerobrew 已安装 formula
brew list --cask               # Homebrew 已安装 cask
```

### 清理无用依赖

```bash
brew autoremove                # Homebrew 孤立依赖
brew cleanup                   # Homebrew 旧版本缓存
zb gc                          # Zerobrew 未引用条目
```

---

## 特殊场景

### 图形应用已手动安装，Homebrew cask 冲突

如果应用（如 `Grok Bot.app`）在 `brew bundle` 前已手动放入 `/Applications`：

**选项 1**：让 Homebrew 接管（推荐）

```bash
brew install --cask --adopt grok-bot
```

`--adopt` 会将现有应用纳入 Homebrew 管理，后续可通过 `brew upgrade` 更新。

**选项 2**：保持手动管理

在 `scripts/brew-bundle.sh` 的跳过列表（当前第 148 行）中追加
`<token>:<App Name>.app` 一项：

```bash
for entry in 'microsoft-edge:Microsoft Edge.app' 'zed:Zed.app' \
  'clash-verge-rev:Clash Verge.app' 'grok-bot:Grok Bot.app'; do
  token="${entry%%:*}"
  app="${entry#*:}"
  if ! brew list --cask "$token" >/dev/null 2>&1 \
    && { [ -d "/Applications/$app" ] || [ -d "$HOME/Applications/$app" ]; }; then
    export HOMEBREW_BUNDLE_CASK_SKIP="${HOMEBREW_BUNDLE_CASK_SKIP:-} $token"
  fi
done
```

### 同名包在两个管理器都存在

**现象**：`brew list --formula` 和 `zb list` 都显示同一个包。

**诊断**：

```bash
# 检查声明归属
cat template/scripts/package-ownership.json | jq -r '.zerobrew_formulas[]' | grep <formula>

# 检查实际安装位置
which <binary>               # 当前 PATH 解析到哪个
brew list <formula> 2>&1     # Homebrew 是否安装
zb list | grep <formula>     # Zerobrew 是否安装
```

**修复**：

1. 确认 `package-ownership.json` 中的预期归属
2. 如果当前机器状态与归属清单不符，按"手动迁移"步骤处理
3. 如果归属清单本身需要调整（策略变更），先修改清单再运行 `make package-migrate`

### home 机器独有的工具（如 rclone、rustic）

在 `private/profiles/home/Brewfile` 声明即可，work 机器不会安装：

```ruby
# private/profiles/home/Brewfile
brew "rclone"
brew "rustic"
```

`package-ownership.json` 中 `rclone` 和 `rustic` 仍标记为 `zerobrew_formulas`，但因为 work profile 未声明它们，work 机器的 `brew-bundle.sh` 不会安装。

---

## 检查清单

添加/移除软件后运行：

- [ ] `make doctor` 通过
- [ ] `brew list --formula` 和 `zb list` 无重复（除非有明确需求）
- [ ] 关键二进制可执行：`command -v <tool> && <tool> --version`
- [ ] `package-ownership.json` 与实际归属一致

---

## 参考

- [private-overlay.md](./private-overlay.md)：Zerobrew 详细配置与恢复流程
- [manual-apps.md](./manual-apps.md)：手动管理的图形应用列表
- `scripts/brew-bundle.sh`：安装与迁移逻辑实现
- `scripts/run-doctor-checks.py`：健康检查实现
