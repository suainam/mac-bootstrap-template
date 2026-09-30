# 配置操作脚本

当前使用 PyODPS 执行配置表读取、写入和校验；先查当前工作区依赖/项目凭据约定，再运行命令。凭据默认从 `~/.env` 读取，`ODPS_SECRET_KEY` 可映射为 SDK 所需 secret access key。

## 操作顺序

1. 读取生产全表到内存/临时快照，保存行数和完整行值；按 `rule_id` 排序比对。
2. 从最新 `dim_store` 分区查编码，并准备明确的全量目标集合。
3. 确认开发同名表 schema。不存在则按正式 schema `CREATE TABLE IF NOT EXISTS`；若存在且含旧快照，先用全量目标集合覆写。
4. 查询开发表，检查行数、`COUNT(DISTINCT rule_id)`、拟变更记录及所有原有规则一致性。
5. 正式写入前重新读取正式表并与保存快照比较；任何并发差异均停止，不覆盖。
6. 生产 `INSERT OVERWRITE` 使用已验证的完整开发快照，之后读回并执行相同门禁。

开发和生产表应使用不同 ODPS project client，SQL 完全限定表名。若 SDK/网络报错，先确认 instance 最终状态或查询目标行，再决定重试；不确定提交结果时不可重复 `INSERT`。

写入完成证据：dev/prod 各自的行数、唯一 rule_id 检查、目标行字段及保留记录对比。禁止将凭据、连接对象序列化或写入输出。
