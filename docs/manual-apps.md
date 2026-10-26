# Manual Apps

This file records GUI apps that are locally manual, need non-Brew installation,
or need `make doctor` cask overrides so the template stays rerunnable.
`scripts/doctor.sh` (`make doctor`) evaluates `Brewfile` and active profile
extensions once via `brew bundle list` (`HOMEBREW_MAC_BOOTSTRAP_PROFILE` /
`HOMEBREW_MAC_BOOTSTRAP_PRIVATE_DIR`) and verifies formula installation against
the active Brewfile without mutating packages or services.

## 外部工具声明与漂移审计

Brew 软件只在 Brewfile 分层中声明。非 Brew 工具使用公共
`manifests/external-tools.json`，叠加私有覆盖目录下的
`profiles/<profile>/external-tools.json`；没有 profile 清单时仅使用公共层。
有效 profile 与私有目录沿用 `resolve-profile.sh` 及其环境覆盖。
`scripts/install-external-tools.sh` 调用审计脚本的 `--dump-manifest`，
与审计消费同一加载结果；该安装入口只处理 npm 与独立二进制，GUI app 和
daemon plist 的安装仍由各自 runbook 负责。

`make fresh-check` 在 `machine-check` 执行，返回 0 表示无漂移、2 表示
`MISSING` 或 `UNEXPECTED`、3 表示配置或归属查询错误。扫描范围是
`~/.local/bin`、`/Applications`、`~/Applications`、用户及系统 LaunchAgents
和系统 LaunchDaemons；它同时结合 `brew info --json=v2 --casks` 与
`brew services list --json` 排除 Cask 与 Formula 托管的 plists，不卸载软件，也不以 plist 存在证明服务正在运行。
未声明输出需要核实所有权，不能直接作为卸载清单。
复盘结论：声明探针的绿灯不能证明没有多余安装；回归必须用隔离目录覆盖
缺失、未声明和跨 profile 泄漏，并验证 Brew 归属排除。机器盘点留在
machine gate，repository gate 不依赖机器安装状态。迁移清单时同步检查安装入口、
测试与文档，避免重复权威。操作边界拒绝后按原操作等待授权恢复，禁止换工具绕过；
重复授权不累积票据。

## 小米互联服务 (Xiaomi HyperConnect)

- 路径：`/Applications/小米互联服务.app`
- Homebrew cask：`hyperconnect`
- 现状：Homebrew 官方已收录 `hyperconnect` cask 并由 brew 统一管理。
- 作用：小米手机与 Mac 之间的跨设备协同（剪贴板共享、文件传输、通知同步等）

## Brewfile 中但本机手动安装的应用

以下应用在 Brewfile 中，本机若已通过 DMG 手动安装未被 brew 接管，
`template/scripts/brew-bundle.sh` 会自动检测并跳过重复安装：

- `clash-verge-rev` — 本机手动安装（DMG），brew 自动跳过重复安装

## Prism Browser

- 路径：`/Applications/Prism Browser.app`（bundle id `com.prismbrowser.desktop`）
- 管理：声明于 `private/profiles/work/external-tools.json`（work profile 专属外部应用清单）
- 用途：桌面多应用容器浏览器
## 豆包 (Doubao)

- 路径：`/Applications/Doubao.app`
- Homebrew cask：`doubao`（官方 cask）
- 限制：Homebrew 下载后会为 DMG 重新加上 `com.apple.quarantine`，`hdiutil attach`
  因而触发 Gatekeeper 的“此磁盘映像可能有问题”确认框；非交互环境下无人应答，
  `brew install --cask doubao` 会以 `hdiutil: attach canceled` 失败。
  当前 Homebrew 已移除 `--no-quarantine`（`HOMEBREW_CASK_OPTS` 传入会报
  `invalid option`），没有受支持的绕过开关。
- 处理：在该机器上用交互式终端执行 `brew install --cask doubao`，并在弹窗中点“打开”；
  之后 `brew list --cask` 会正常记录该 cask。
- 注意：`brew upgrade --cask doubao` 会重新下载并再次遇到同一确认框，需要交互确认。

## 豆包输入法 (Doubao Input Method)

- 路径：`~/Library/Input Methods/DoubaoIme.app`
- 下载：从官网 [shurufa.doubao.com](https://shurufa.doubao.com/) 下载，解压缩后运行其中的安装器应用（`DoubaoImeInstaller_v*.app`）进行安装。
- 说明：目前无官方 Homebrew cask。必须运行官方 GUI 安装器进行安装，以确保系统服务（如设置界面 `DoubaoImeSettings.app`）正常注册，不建议直接进行文件拷贝。

## Muse (muse.ai)

- 路径：`/Applications/Muse.app`（bundle id `com.meta.endo`）
- Homebrew cask：`local/tools/muse`（对应官方 cask `muse`）
- 现状：Homebrew 官方 cask 声明的下载地址 `https://muse.ai/api/hatch/app-download/mac` 存在 Meta 账号/地域准入限制（直接请求返回 403 `{"error":"not_eligible"}`）。本机通过 Sparkle Appcast CDN 提取 v4.1 DMG 并通过 `local/tools/muse` 完成接管。
- 用途：Meta AI 长期目标与任务规划桌面助手。

## 企业专有与非 Brew 托管应用

以下应用属于企业内部准入、特定硬件配套或专有客户端，无公共 Homebrew cask，统一记录于 `private/profiles/work/external-tools.json`（通用外部工具置于公共 `template/manifests/external-tools.json`）：

1. **CorpLink**：
   - 路径：`/Applications/CorpLink.app`（bundle id `com.volcengine.corplink`）
   - 来源：火山引擎 / 字节企业内部安全准入与 VPN 客户端，由企业内网门户分发。
2. **阿里云无影云电脑**：
   - 路径：`/Applications/无影云电脑.app`（bundle id `com.aliyun.wuying.osx`）
   - 来源：阿里云官网分发，远程开发与云桌面客户端。
3. **MAXHUB 传屏助手**：
   - 路径：`/Applications/MAXHUBShare.app`（bundle id `com.cvte.MAXHUBShare`）
   - 来源：MAXHUB 会议平板配套无线投屏客户端。
