# Colima 本地容器运行时

本模板使用 Colima 提供按需启动的本地 Docker runtime。Docker CLI、Compose 与
Colima 由 Homebrew 管理；Python、Node 和应用依赖仍留在容器内。

## 默认契约

- profile：`www`
- 资源：4 CPU、6 GiB 内存、80 GiB 稀疏数据盘
- 宿主 HTTP/HTTPS 代理：由 `COLIMA_PROXY_PORT` 显式提供
- Docker 日志：`json-file`，单文件 `10m`，保留 `3` 个文件
- Kubernetes：不启用
- 登录启动：不启用；需要时手动启动

资源和日志默认值可通过 `COLIMA_*` 环境变量覆盖。代理端口属于机器实例配置，
公开模板不提供默认值；父仓应从 private overlay 注入。脚本不会读取或写入代理
订阅、token 或应用凭据。

## 使用

首次 Homebrew bootstrap 后启动：

```bash
COLIMA_PROXY_PORT=<port> make colima-start
```

检查 profile、Docker context、宿主代理和日志策略：

```bash
COLIMA_PROXY_PORT=<port> make colima-doctor
```

停止并释放 CPU/内存：

```bash
make colima-stop
```

容器镜像和 volume 会保留在稀疏数据盘；停止 profile 不会删除数据。

## 项目接入

项目继续使用标准 `docker` 与 `docker compose` 命令。脚本创建并激活
`colima-www` context；自动化若不依赖当前 context，应显式传入该名称。

本地 dashboard 应使用测试数据，并关闭初始 ETL 与 cron。真实凭据仍由各项目
运行态管理，不进入镜像、Brewfile 或本模板。
