# 拆解页控件交互（ai-devops decompose）

`#/demand/decompose/<id>` 的控件均为自定义实现，无原生 `value` 可赋值，只能展开后点击。本文按控件类型给出实测可用的定位与事件序列。

## 文本字段

- **标题**：`input[placeholder="请输入Story标题"]`。原型链原生 setter 赋值，再派发 `input`、`change`（`bubbles: true`）。
- **描述 / 价值**：两个 `[contenteditable="true"]`（tiptap/ProseMirror），顺序即「描述 → 价值」。设 `textContent` 后同样派发 `input`/`change`。

```js
const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
setter.call(input, value);
input.dispatchEvent(new Event('input',  { bubbles: true }));
input.dispatchEvent(new Event('change', { bubbles: true }));
```

## 下拉选择（产品线 / 子系统）

1. 找文本恰为「请选择」的空叶子（`children.length === 0`），向上取 `BUTTON` 并 `click()`。
2. 等约 600ms，读 `[role="option"]`。
3. 按文本精确匹配点目标项。
4. 子系统依赖产品线：先选产品线，子系统才可选；选项在重新展开后才出现。

## 到期日（日期面板）

1. 点 `*到期日` 行的 `BUTTON`，打开 `[role="dialog"]`。
2. 日期格是 `BUTTON`，`aria-label` 形如 `2026年12月29日 星期二`。
3. 以 `aria-label` 判定真实网格月份，头部标题可能与网格偏移，不可信。
4. 目标月份更晚点 `aria-label="Go to the Next Month"`，更早点 `Go to the Previous Month`，循环到目标日出现再点。
5. 回读表单「到期日」确认落值。

翻月与选日建议派发完整鼠标序列，单纯 `.click()` 有时不生效：

```js
for (const t of ['pointerdown','mousedown','pointerup','mouseup','click'])
  el.dispatchEvent(new MouseEvent(t, { bubbles: true, cancelable: true, view: window }));
```

## 人员计划（四岗认领）

四岗为设计人员、前端工程师、后端工程师、测试工程师，每岗一个 `input[placeholder="输入姓名或工号搜索"]`。

1. **用工号搜索**：姓名常被脱敏成占位符 token，搜姓名无结果。工号取自 `localStorage['tip_closed_ds_theme_launch_<工号>']` 或 `Operator-Name` 旁的已知工号。
2. 注入工号后等约 1.5–2s。候选渲染为姓名 + 工号 + 部门，形如 `10093621 / 信息中心 / 数据智能一组`。
3. **核对部门文本再点击**，避免同名误选。候选项的可点容器是含 `cursor-pointer` 的祖先 `DIV`，不是叶子 `SPAN`。
4. 用完整鼠标序列点击，单 `.click()` 可能不落格。
5. **逐岗回读**该岗位容器内的 chip 文本，非空才算成功。

若点击后 chip 仍为空，停止自动操作转人工，不报成功。

## 卡片切换与弹层

- 同页多张草稿时，字段写入作用于**当前选中卡**。写前断言当前标题等于该卡旧标题。
- 切卡弹「未保存的修改」：点「取消」保留当前编辑；点「确认切换」丢弃。
- 残留弹层会挡住日期面板。先关弹层（取消或 Escape），再重开日期。

## 保存与拦截

- 「保存草稿」在基本信息面板底部；成功 toast 为「草稿已保存」。
- 缺必填时 toast 为「请填写所有必填项后再保存」。
- 保存后回读草稿计数与卡片标题，并记录 `Story-XXXXXX` 编号。
- 「提交Story」创建正式 Story，需用户授权。
