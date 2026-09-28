# Docker 磁盘与构建缓存治理 Runbook

在长期运行的开发机、CI Runner 节点或 GPU 工作站上，`/var/lib/docker/overlay2` 常出现空间持续膨胀，甚至耗尽根分区磁盘的情况。本 runbook 总结此类问题的排查路径、安全清理命令及长效治理策略。

## 典型现象与排查

### 1. 常见表象
* 根分区（`/`）磁盘使用率达到 90%+，`df -h` 显示剩余空间极低。
* 进入 `/var/lib/docker/overlay2` 执行 `du -sh ./* | grep G`，发现大量占用数 GB 的目录。
* 容器或镜像数量看似不多，但磁盘却被占满。

### 2. 诊断方法（非侵入式探测）

```bash
# 1. 总体概览：区分 Images、Containers、Volumes 与 Build Cache
docker system df

# 2. 查看 BuildKit 缓存明细与可回收空间
docker builder du

# 3. 统计 overlay2 目录分类
# - 26 位 base32 命名（如 aw64dt6q0dxlv43...）：BuildKit 快照缓存
# - 64 位 16 进制命名（如 072ebd43f472...）：容器可写层（diff）或镜像层
ls /var/lib/docker/overlay2 | wc -l
```

若 `docker system df` 中 `Build Cache` 达到数十至上百 GB（且 `RECLAIMABLE` 接近 100%），说明核心瓶颈在构建缓存积压。

若某个 64 位 hex 目录特别大，可通过以下命令反查对应的容器：
```bash
docker ps -q | xargs docker inspect --format '{{.Name}}: {{.GraphDriver.Data.MergedDir}}' | grep <layer-id前缀>
```

---

## 核心根因分析

1. **Docker BuildKit 默认机制无 GC 上限**：
   Docker 默认未开启构建缓存配额上限，只要磁盘未达到 100%，Docker 不会自动清理历史构建快照。
2. **多分支与 CI/CD 频繁构建产生分支快照**：
   在单机运行 Runner（如 Gitea/GitHub Act Runner）或频繁为 feature 分支打镜像时，一旦 Dockerfile 前序指令变动，后续所有层均会产生新的孤立快照，日积月累导致成千上万个 snapshot 残留。
3. **脚本/程序中断缺乏 `trap` 清理保护**：
   在容器内执行大文件临时导出或中转时（如通过 `mktemp -d /tmp/...`），若脚本未通过 `trap` 捕获 `SIGINT`/`SIGTERM`/`EXIT` 信号，当中断或报错闪退时，临时数据会永久滞留在容器可写层（`diff/tmp`）中。

---

## 安全清理操作

> 提示：以下清理均不会影响正在运行的容器或已拉取/构建成功的生产镜像。

### 1. 清理 BuildKit 构建缓存（最高收益）
BuildKit 缓存包含数千条条目时，标准输出会逐行打印被删 ID 导致终端严重刷屏，应通过重定向静默执行：

```bash
docker builder prune -a -f > /dev/null 2>&1
```
* **效果**：立即释放全部未被引用的中间层构建缓存（通常为数十至上百 GB）。

### 2. 清理废弃的 `<none>` 虚悬镜像

```bash
docker image prune -f
```
* **效果**：移除多次打标签后被覆盖、无容器引用的历史无名层。

### 3. 清理特定容器内的残留临时目录
若定位到特定工作容器（如开发容器、IDE 容器）的 `/tmp` 存在遗留大文件：

```bash
# 检查容器内临时文件
docker exec <container-name> du -sh /tmp/*

# 清理指定前缀的孤立导出/暂存目录
docker exec <container-name> rm -rf /tmp/<staged-temp-prefix>-*
```

---

## 长效防护机制

为防止数月后磁盘再次被打满，必须部署**被动配额**与**主动定期清理**双层防护：

### 1. 被动配额：配置 Docker 守护进程 BuildKit GC 阈值
编辑 `/etc/docker/daemon.json`，在根对象中增加 `builder.gc` 配置（如限制最大保留 20GB）：

```json
{
  "builder": {
    "gc": {
      "enabled": true,
      "defaultKeepStorage": "20GB"
    }
  }
}
```
* **生效方式**：下次 Docker 守护进程重启（`systemctl restart docker`）后自动生效。无需立即重启生产 Docker。

### 2. 主动防护：Crontab 每周自动修剪
在宿主机 root crontab（`crontab -e`）中添加计划任务，定期修剪超过 7 天未使用的构建缓存与虚悬镜像：

```cron
# 每周日凌晨 3 点自动修剪 >168h 的构建缓存与悬空镜像
0 3 * * 0 /usr/bin/docker builder prune -a -f --filter "until=168h" > /dev/null 2>&1 && /usr/bin/docker image prune -f > /dev/null 2>&1
```

### 3. 脚本健壮性：在临时目录生成脚本中增加 `trap`
所有向 `/tmp` 或工作区写入暂存文件的运维/数据导出脚本，应使用 POSIX `trap` 保证异常退出时必定清理：

```bash
stage_dir="$(mktemp -d /tmp/export-stage-XXXXXX)"
cleanup() {
  rm -rf "$stage_dir"
}
trap cleanup EXIT INT TERM
```
