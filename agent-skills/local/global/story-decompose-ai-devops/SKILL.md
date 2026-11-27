---
name: story-decompose-ai-devops
description: 在 ai-devops 需求拆解页（#/demand/decompose/<demandId>）创建或改写 Story 草稿：定位标签、AI拆解/重新拆解、改写标题描述价值、填必填选择器（产品线/子系统/到期日/人员四岗）、保存核验。用于拆 Story、拆分、重新拆解、挂工时、缩铺、全栈 Story 规范化。
---

# ai-devops 需求拆解（Story Decompose）

在 `ai-devops.dslbuy.com/#/demand/decompose/<demandId>` 产出可挂工时的 Story 草稿，内容只取自已确认口径。

## 进入条件

用户给出 `#/demand/decompose/<id>` 链接，或说「拆 Story / 拆分 / AI拆解 / 重新拆解 / 挂工时」。

浏览器一律经 huashu `BridgeClient` 驱动。`tabId` 是 `call` 的第三参，不是 params 字段：

```js
client.call("eval", { expr }, { tabId })      // 正确
client.call("eval", { expr, tabId })          // 报「还没有受控标签页」
```

控件级交互细节（选择器、事件派发、候选定位）见 `references/decompose-ui-patterns.md`。

## 操作流程

### 1. 定位标签

`client.call("tabs", { action: "list" })` 找 URL 已含 `decompose/<demandId>` 的标签。没有则 `tabs action:"new"` 打开拆解链接，取返回 `tabId`。

**完成标准**：拿到一个 `tabId`，其页面 URL 含目标 demandId。

### 2. 读需求与现状

`read_text scope:"page"` 记录四项：原始需求标题、描述与价值、Story草稿数与各草稿标题、已提交 Story 数。

**完成标准**：能列出每张现有草稿的标题与「草稿/已提交」状态，据此判断哪些可改、哪些不能动。

### 3. 选拆分来源

| 情况 | 动作 |
|---|---|
| 原始需求文本即目标口径 | 点「AI拆解」或顶部「重新拆解」；后者会弹「确认重新拆解（原Story草稿将被覆盖）」，仅获授权后点「确认」 |
| 用户指定改写现有草稿 | 直接进入第 4 步，不点重新拆解 |
| 口径与原文不同 | 点「手动新增」建空白草稿，再按口径改写 |

**完成标准**：草稿列表已含目标数量的草稿，且每张的标题能对应到用户要的范围。

### 4. 改写字段

标题用原生 setter + `input`/`change` 冒泡；描述与价值是两个 `[contenteditable="true"]`，设 `textContent` 后同样派发事件。

**卡片绑定是本节唯一硬要求**：同页多张草稿时，写入作用于当前选中卡。写入前断言当前标题等于该卡旧标题，不等就停止；写入后立刻回读标题与正文首段。

```js
// 写入前
if (document.querySelector('input[placeholder="请输入Story标题"]').value !== OLD_TITLE) throw new Error('wrong card');
// 写入后
({ title: input.value, body: editors[0].innerText.slice(0, 120) })
```

切换卡片会弹「未保存的修改」。点「取消」保留当前编辑；残留弹层会挡住日期面板，先关弹层再重开日期。

**完成标准**：每张草稿回读的标题与正文首段都对应它自己的范围，没有两张卡内容相同或串位。

### 5. 填必填选择器

产品线、子系统、到期日、人员计划四岗，全部是自定义控件，只能展开后点击。产品线决定子系统选项；四岗各有一个独立搜索框。

人员一律用工号搜索并核对部门文本，姓名可能被脱敏成占位符 token。当前登录人工号可从 `localStorage` 的 `tip_closed_ds_theme_launch_<工号>` 读取。

**完成标准**：回读显示到期日为目标日期、产品线与子系统为预期值、四岗每格都有非空人名。

### 6. 保存与核验

点「保存草稿」。成功 toast 为「草稿已保存」。

**完成标准**：toast 出现；草稿计数与卡片标题回读一致；记录每张草稿的 `Story-XXXXXX` 编号。

### 7. 提交

「提交Story」创建正式 Story，仅在用户明确授权后点击，之后回读状态。

**完成标准**：仅保存时，草稿计数不变、无已提交 Story；获授权提交时，该 Story 出现在已提交列表。

## 边界

- 选择器交互只做受控注入，不盲点未知选项。候选未出现或落格失败时停止并转人工，不报成功。
- 一个 Story 只写一个业务范围；用户给定范围与数量后直接执行，不自行拆分或合并。
- 原始需求与已确认口径冲突时按口径写，并在正文注明未启用维度，避免把未确认规则写成已生效门禁。
