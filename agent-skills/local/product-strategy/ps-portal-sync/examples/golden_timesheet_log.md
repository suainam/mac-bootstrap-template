# DevOps 需求流转与工时填报黄金范例 (Golden Example: Timesheet & Story Management)

本范例展示在 `devops.dslbuy.com` 中完成需求拉取定位、状态核验以及工时日历 (`/#/timeWise/timeSheet`) 的合规填报。

---

## 1. 业务场景设定

* **目标周期**：2026-10-12 至 2026-10-16（当周 5 个工作日）
* **专题归属**：商品决策二期项目 (`project_id=154`)
* **关联需求**：`Story-279258`（货源仓禁发策略升级与指标回刷）
* **证据凭据**：本地 Git commit 记录、数仓调度任务 ID `10003135688`
* **工时配比原则**：标准单日 8 小时，严禁超填，严禁漏填。

---

## 2. 自动化执行脚本

```javascript
// 执行命令: jev-browser-use --connect http://127.0.0.1:9222 -e "<script>"
const p = await browser.getPage("devops");
await p.bringToFront();

// 1. 定位工时填报工作台
await p.goto("https://devops.dslbuy.com/#/timeWise/timeSheet");
await p.waitForLoad();

// 2. 提取当前周期已登记工时并核验
const auditSummary = await p.evaluate(() => {
  const rows = Array.from(document.querySelectorAll('.el-table__body tr.el-table__row'));
  return rows.map(tr => {
    const taskName = tr.querySelector('.cell a, .cell span')?.innerText?.trim() || '';
    const dayInputs = Array.from(tr.querySelectorAll('input.el-input__inner')).map(i => parseFloat(i.value) || 0);
    return { taskName, total: dayInputs.reduce((a, b) => a + b, 0), days: dayInputs };
  });
});
console.log("当前工时汇总:", JSON.stringify(auditSummary, null, 2));

// 3. 定位目标需求并填报工时 (遵守 v-model-sync)
await p.evaluate(({ storyCode, hoursPerDay }) => {
  const rows = Array.from(document.querySelectorAll('.el-table__body tr.el-table__row'));
  const targetRow = rows.find(tr => tr.innerText.includes(storyCode));
  if (!targetRow) throw new Error(`未在工时表中找到需求 ${storyCode}`);

  const inputs = Array.from(targetRow.querySelectorAll('input.el-input__inner'));
  // 填报前 5 个工作日，每个工作日 8.0 小时
  inputs.slice(0, 5).forEach((input, idx) => {
    const h = String(hoursPerDay[idx] || 8);
    input.value = h;
    input.dispatchEvent(new Event('input', { bubbles: true }));
    input.dispatchEvent(new Event('change', { bubbles: true }));
    input.dispatchEvent(new Event('blur', { bubbles: true }));
  });
}, { storyCode: 'Story-279258', hoursPerDay: [8, 8, 8, 8, 8] });

// 4. 保存工时 (仅点击暂存/保存)
await p.click('button.el-button--primary:has-text("保存")');
await new Promise(r => setTimeout(r, 1500));

// 5. 校验提示反馈
const feedback = await p.evaluate(() => {
  const msg = document.querySelector('.el-message--success');
  return msg ? msg.innerText.trim() : '未捕获成功提示，请核验页面状态';
});
console.log("填报结果:", feedback);
```

---

## 3. 验收与合规门禁检查项

1. **工时总计校验**：5 个工作日合计严格等于 40.0 小时，无单日 > 10 小时异常。
2. **凭据溯源**：填报的需求编号必须能在需求详情页（`/#/story/list?id=...`）中查到当前状态为“进行中”或“联调中”，且负责人为本人。
3. **安全门禁**：仅点击【保存】，待整周工时无误后，由人工在周五下班前统一核验点击【提交审批】。
