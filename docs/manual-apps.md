# Manual Apps

This file records GUI apps that are locally manual, need non-Brew installation,
or need `make doctor` cask overrides so the template stays rerunnable.

## 小米互联服务 (Xiaomi HyperConnect)

- 路径：`/Applications/小米互联服务.app`
- Homebrew cask：`xiaomi-cloud`
- 现状：本机是手动安装的 `小米互联服务.app`，`make doctor` 通过
  `scripts/doctor-manifest.json` 的 `cask_overrides` 将其识别为 `xiaomi-cloud`
- 作用：小米手机与 Mac 之间的跨设备协同（剪贴板共享、文件传输、通知同步等）

## Brewfile 中但本机手动安装的应用

以下应用在 Brewfile 中，本机因手动安装未被 brew 管理。
新机器通过 `brew bundle install` 会自动安装：

- `microsoft-edge` — 本机手动安装，brew 未接管
- `clash-verge-rev` — 本机手动安装（DMG），brew 未接管

## WorkBuddy AI

- 路径：`/Applications/WorkBuddy AI.app`（bundle id `com.workbuddy.workbuddy-ai`）
- 安装：`make install-workbuddy`（运行 `scripts/install-workbuddy.sh`）
- 为什么不用 Homebrew：官方仓库没有 `workbuddy` cask（`codebuddy` / `codebuddy-cn`
  是同厂的 IDE，不是本应用），任何 tap 中也不存在，因此不能用 `cask` 声明。
- 上游：脚本从国际版更新接口
  `https://www.codebuddy.ai/v2/update?platform=workbuddy-darwin-arm64` 取版本、
  `.dmg` 地址与 SHA256，下载后校验、挂载、复制到 `/Applications`。
  注意接口返回的 `url` 结尾是 `.zip`，但 `sha256hash` 对应的是同路径的 `.dmg`。
- Gatekeeper：厂商随包提供 `Fix-Damage.txt`，说明安装时若验证往返失败，macOS 会误报
  “已损坏”；脚本在安装后已清除 quarantine 标记。手动安装时可用
  `xattr -rd com.apple.quarantine "/Applications/WorkBuddy AI.app"`。

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
