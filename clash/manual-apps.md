# 手动安装的应用

以下应用无 Homebrew cask 或需手动安装：

## 小米互联服务 (Xiaomi HyperConnect)

- 路径：`/Applications/小米互联服务.app`
- 下载：从 Xiaomi 官网或小米生态软件中心下载
- 无 brew cask，需手动安装
- 作用：小米手机与 Mac 之间的跨设备协同（剪贴板共享、文件传输、通知同步等）

## Brewfile 中但本机手动安装的应用

以下应用在 Brewfile 中，本机因手动安装未被 brew 管理。
新机器通过 `brew bundle install` 会自动安装：

- `microsoft-edge` — 本机手动安装，brew 未接管
- `clash-verge-rev` — 本机手动安装（DMG），brew 未接管

## 豆包输入法 (Doubao Input Method)

- 路径：`~/Library/Input Methods/DoubaoIme.app`
- 下载：从官网 [shurufa.doubao.com](https://shurufa.doubao.com/) 下载，解压缩后运行其中的安装器应用（`DoubaoImeInstaller_v*.app`）进行安装。
- 说明：目前无官方 Homebrew cask。必须运行官方 GUI 安装器进行安装，以确保系统服务（如设置界面 `DoubaoImeSettings.app`）正常注册，不建议直接进行文件拷贝。

