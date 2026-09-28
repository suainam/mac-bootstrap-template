# Manual Apps

This file records GUI apps that are locally manual, need non-Brew installation,
or need `make doctor` cask overrides so the template stays rerunnable.

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
- 管理：声明于 `template/manifests/external-tools.json`（外部应用清单）
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

以下应用属于企业内部准入、特定硬件配套或专有客户端，无公共 Homebrew cask，统一记录于 `template/manifests/external-tools.json`：

1. **CorpLink**：
   - 路径：`/Applications/CorpLink.app`（bundle id `com.volcengine.corplink`）
   - 来源：火山引擎 / 字节企业内部安全准入与 VPN 客户端，由企业内网门户分发。
2. **阿里云无影云电脑**：
   - 路径：`/Applications/无影云电脑.app`（bundle id `com.aliyun.wuying.osx`）
   - 来源：阿里云官网分发，远程开发与云桌面客户端。
3. **MAXHUB 传屏助手**：
   - 路径：`/Applications/MAXHUBShare.app`（bundle id `com.cvte.MAXHUBShare`）
   - 来源：MAXHUB 会议平板配套无线投屏客户端。
