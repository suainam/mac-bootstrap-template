---
type: journal
period: monthly
status: active
owner: local-user
date: {{date:YYYY-MM}}
year: {{date:YYYY}}
quarter: {{date:YYYY-[Q]Q}}
tags: [monthly, work-log]
---

# {{date:YYYY年MM月}}工作总结

## 月度概览

## AI 总结

<!-- 由 monthly_summary.py 自动填入 -->

## 重点工作

## 问题与风险

## 心得与思考

## 下月重点

1.
2.
3.

## 自动汇总

```dataviewjs
async function main() {
  function monthId() {
    const raw = dv.current().date ?? dv.current().file.name;
    return String(raw).slice(0, 7);
  }

  function valueToMonth(value) {
    if (!value) return "";
    if (value.year && value.month) return `${value.year}-${String(value.month).padStart(2, "0")}`;
    return String(value).slice(0, 7);
  }

  function renderListTree(items, parentLine = null, indent = 0, lines = []) {
    const children = items
      .where((item) => (parentLine === null ? !item.parent : item.parent === parentLine))
      .sort((item) => item.line, "asc");
    for (const item of children) {
      lines.push(`${"  ".repeat(indent)}- ${item.text}`);
      renderListTree(items, item.line, indent + 1, lines);
    }
    return lines;
  }

  function sectionText(content, heading) {
    const escaped = heading.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    const match = content.match(new RegExp(`^## ${escaped}\\n([\\s\\S]*?)(?=\\n## |\\n---|$)`, "m"));
    if (!match) return "";
    return match[1]
      .replace(/```[\\s\\S]*?```/g, "")
      .replace(/<!--([\\s\\S]*?)-->/g, "")
      .trim();
  }

  const currentMonth = monthId();
  const dailies = dv.pages('"docs/daily"')
    .where((page) => valueToMonth(page.month ?? page.date ?? page.file.name) === currentMonth)
    .sort((page) => page.file.name, "asc");
  const weeklies = dv.pages('"docs/weekly"')
    .where((page) => valueToMonth(page.month ?? page.date ?? page.file.name) === currentMonth)
    .sort((page) => page.file.name, "asc");

  dv.header(3, "本月日报覆盖");
  dv.paragraph(dailies.length ? `本月记录 **${dailies.length}** 篇日报` : "> 暂无本月日报");

  dv.header(3, "本月重点");
  let hasFocus = false;
  for (const page of dailies) {
    const tasks = page.file.tasks.where((task) => task.section?.subpath === "今日重点" && !task.parent);
    if (!tasks.length) continue;
    hasFocus = true;
    dv.header(5, page.file.name);
    dv.taskList(tasks, false);
  }
  if (!hasFocus) dv.paragraph("> 本月暂无重点记录");

  dv.header(3, "本月问题与临时事项");
  let hasOther = false;
  for (const page of dailies) {
    const blocks = [];
    for (const section of ["临时需求", "问题反馈"]) {
      const lines = renderListTree(page.file.lists.where((item) => item.section?.subpath === section));
      if (lines.length) blocks.push({ section, lines });
    }
    if (!blocks.length) continue;
    hasOther = true;
    dv.header(5, page.file.name);
    for (const block of blocks) {
      dv.el("h6", block.section);
      dv.paragraph(block.lines.join("\n"));
    }
  }
  if (!hasOther) dv.paragraph("> 本月暂无临时事项或问题反馈");

  dv.header(3, "周报判断摘录");
  let hasWeekly = false;
  for (const page of weeklies) {
    const content = await dv.io.load(page.file.path);
    const text = sectionText(content.replace(/\r\n/g, "\n"), "本周判断");
    if (!text) continue;
    hasWeekly = true;
    dv.header(5, page.file.name);
    dv.paragraph(text);
  }
  if (!hasWeekly) dv.paragraph("> 本月暂无周报判断摘录");}

main();
```

---
关联季报：[[{{date:YYYY-[Q]Q}}]]
