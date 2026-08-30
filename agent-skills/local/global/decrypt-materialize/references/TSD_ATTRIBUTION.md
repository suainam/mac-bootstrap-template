# TSD 加密来源归因（2026-08-25 调研）

结论：`%TSD-Header-###%` 加密来自本机安装的 **天锐(teclink) OCular 企业 DLP 套件**，
与 codex / threadripper / codexpro 等 agent 工具链无关。

## 元凶组件（macOS 实测）

| 层 | 组件 | 证据 |
|---|---|---|
| 内核态 | `com.tec-development.LSDEfs2600_arm.kext`（Efs = Encrypt File System） | `kextstat | grep -v com.apple` 可见已加载；VFS 过滤驱动即 TSDENCRYPTDRV |
| 用户态守护 | `/usr/local/OCularApp/LSDHelper.app`、`/usr/local/.OCular/OCular.app/Contents/MacOS/{LAgentUser,LMonitor,LSDConfig,LInject,…}` | 二进制内含大量 TSD 字符串；LaunchDaemon/LaunchAgent KeepAlive 常驻 |
| 策略下发 | DLP 管理服务器 → `/usr/local/.OCular/OPolicy/*.xml`（带混淆头，离线不可解析） | LSDHelper 日志记录服务端连接失败/成功 |

归因复验命令：

```bash
# 用户态加密组件指纹（命中即实锤）
LC_ALL=C grep -ac "TSD-Header" /usr/local/OCularApp/LSDHelper.app/Contents/MacOS/LSDHelper   # 33 处命中
LC_ALL=C grep -ao "TSD[A-Za-z-]*" /usr/local/.OCular/OCular.app/Contents/MacOS/LAgentUser | sort -u
kextstat | rtk grep -v com.apple    # 应见 com.tec-development.LSDEfs*
systemextensionsctl list            # com.tec-development.TNwHelperEp 是网络代理扩展，非文件加密，勿混淆
```

排除法要点：codex / codex-threadripper / codexpro 全部二进制 `grep -a "TSD-Header"` 为 0；
threadripper 自身日志报 `stream did not contain valid UTF-8`，说明它也是受害者。

## 加密行为模型（实证，2026-08-25 writer-differential 实验）

1. **按进程信任列表选择性落盘加密**：同一分钟内，codex(Rust) 写的 sqlite 被加密；
   bash / python3 / sqlite3 CLI 写的 `.toml`/`.db` 探针（`~/.codex` 与 `/tmp` 双路径）保持明文。
2. **读取侧按进程授权透明解密**：授权进程（实测 python3）`open()` 读到明文；
   未授权进程（cat/vim/xxd/dd/node 部分场景）读到密文。
   —— 这就是“Python 判断加密失效、必须 dd/xxd 看原始字节”的根本原因。
3. **时间窗聚集**：加密事件成波次出现（如 7/15、7/17、7/21、7/22 各一波），
   符合“服务端策略推送窗口 / 后台扫描周期”特征，非每次写入必触发。
4. **时有时无的原因**：策略由服务端推送，代理离线（LSDHelper 日志刷
   `InnerTcpClient.cpp.RefreshTransferItem` 断言）期间策略陈旧；信任表随策略版本变化，
   同一进程不同日期产物加密状态可不同。

边界：精确信任进程表存于混淆策略文件与 kext 内存，离线无法导出；
上述模型由当日对照实验支撑，属高置信推断。

## 对解密操作的含义

- 解密后**可能再次被加密**（策略窗口重新激活时）。批量替换前先查进程与最近波次：
  `stat -f '%Sm'` 对比可疑文件 mtime 是否聚集。
- 原地解密（备份 + 透明读 + 原子 os.replace）在 agent 进程运行中是安全的：
  POSIX rename 原子性 + 实测写操作不触发即时重加密。
- 治本路径：请企业 IT 将 `~/.codex` 等目录或 `codex`/`node` 等进程加入加密排除/可信列表。
  本地反复自动解密属于与 DLP 对抗，管理端可能有审计记录，是否采用需自行评估合规。

## 复发监控

```bash
# 一行监控：出现 %TS 即中招
watch -n 1 'dd if=~/.codex/config.toml bs=4 count=1'
# 或看 threadripper 报错（它是灵敏哨兵）
tail ~/Library/Logs/codex-threadripper/*/codex-threadripper.error.log
```
