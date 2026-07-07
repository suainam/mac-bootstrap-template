---
type: journal
period: weekly
status: active
owner: local-user
date: {{date:YYYY-[W]ww}}
week_start: {{monday:YYYY-MM-DD}}
week_end: {{sunday:YYYY-MM-DD}}
month: {{date:YYYY-MM}}
quarter: {{date:YYYY-[Q]Q}}
year: {{date:YYYY}}
tags: [weekly, work-log]
---

# {{date:YYYY年第ww周}} ({{monday:MM.DD}}-{{sunday:MM.DD}})

## 本周判断

## AI 总结

<!-- 由 weekly_summary.py 自动填入 -->

## 自动汇总

```dataviewjs
function currentRange() {
  const file = app.workspace.getActiveFile();
  if (!file) return { error: "无法获取当前文件" };
  const fm = app.metadataCache.getFileCache(file)?.frontmatter ?? {};
  if (!fm.week_start || !fm.week_end) return { error: "无法读取 week_start 和 week_end" };
  const start = dv.luxon.DateTime.fromISO(String(fm.week_start).slice(0, 10));
  const end = dv.luxon.DateTime.fromISO(String(fm.week_end).slice(0, 10));
  if (!start.isValid || !end.isValid) return { error: "week_start 或 week_end 不是有效日期" };
  return { start, end };
}

function noteDate(page) {
  const raw = page.date ?? page.file.name;
  return dv.luxon.DateTime.fromISO(String(raw).slice(0, 10));
}

function weekDailies() {
  const range = currentRange();
  if (range.error) return range;
  const dailies = dv.pages('"docs/daily"')
    .where((page) => {
      const date = noteDate(page);
      return date.isValid && date >= range.start && date <= range.end;
    })
    .sort((page) => page.file.name, "asc");
  return { dailies };
}

function topLevel(items) {
  return items.where((item) => !item.parent).sort((item) => item.line, "asc");
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

function renderTaskSection(title, dailies, sourceSection, emptyText) {
  dv.header(3, title);
  let rendered = false;
  for (const page of dailies) {
    const tasks = topLevel(page.file.tasks.where((task) => task.section?.subpath === sourceSection));
    if (!tasks.length) continue;
    rendered = true;
    dv.header(5, page.file.name);
    dv.taskList(tasks, false);
  }
  if (!rendered) dv.paragraph(`> ${emptyText}`);
}

function renderListSections(title, dailies, sourceSections, emptyText) {
  dv.header(3, title);
  let rendered = false;
  for (const page of dailies) {
    const blocks = [];
    for (const section of sourceSections) {
      const items = page.file.lists.where((item) => item.section?.subpath === section);
      const lines = renderListTree(items);
      if (lines.length) blocks.push({ section, lines });
    }
    if (!blocks.length) continue;
    rendered = true;
    dv.header(5, page.file.name);
    for (const block of blocks) {
      dv.el("h6", block.section);
      dv.paragraph(block.lines.join("\n"));
    }
  }
  if (!rendered) dv.paragraph(`> ${emptyText}`);
}

const result = weekDailies();
if (result.error) {
  dv.paragraph(`> ${result.error}`);
} else if (!result.dailies.length) {
  dv.paragraph("> 暂无本周日报");
} else {
  renderTaskSection("本周重点", result.dailies, "今日重点", "本周暂无已记录重点");
  renderListSections("其他事项", result.dailies, ["工作记录", "临时需求", "问题反馈"], "本周无其他事项");
  renderListSections("感想", result.dailies, ["学习&思考"], "本周暂无感想");
  renderTaskSection("下周计划", result.dailies, "明日计划", "本周暂无可汇总的下周计划");
}
```

## 可复制纯文本

```dataviewjs
function currentRange() {
  const file = app.workspace.getActiveFile();
  if (!file) return { error: "无法获取当前文件" };
  const fm = app.metadataCache.getFileCache(file)?.frontmatter ?? {};
  if (!fm.week_start || !fm.week_end) return { error: "无法读取 week_start 和 week_end" };
  const start = dv.luxon.DateTime.fromISO(String(fm.week_start).slice(0, 10));
  const end = dv.luxon.DateTime.fromISO(String(fm.week_end).slice(0, 10));
  if (!start.isValid || !end.isValid) return { error: "week_start 或 week_end 不是有效日期" };
  return { start, end };
}

function noteDate(page) {
  const raw = page.date ?? page.file.name;
  return dv.luxon.DateTime.fromISO(String(raw).slice(0, 10));
}

function weekDailies() {
  const range = currentRange();
  if (range.error) return range;
  const dailies = dv.pages('"docs/daily"')
    .where((page) => {
      const date = noteDate(page);
      return date.isValid && date >= range.start && date <= range.end;
    })
    .sort((page) => page.file.name, "asc");
  return { dailies };
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

function taskLines(dailies, section) {
  const lines = [];
  for (const page of dailies) {
    const tasks = page.file.tasks
      .where((task) => task.section?.subpath === section && !task.parent)
      .sort((task) => task.line, "asc");
    for (const task of tasks) lines.push(`- ${task.text}`);
  }
  return lines;
}

function listLines(dailies, sections) {
  const lines = [];
  for (const page of dailies) {
    for (const section of sections) {
      const items = page.file.lists.where((item) => item.section?.subpath === section);
      lines.push(...renderListTree(items));
    }
  }
  return lines;
}

const result = weekDailies();
if (result.error) {
  dv.paragraph(`> ${result.error}`);
} else if (!result.dailies.length) {
  dv.paragraph("> 暂无本周日报");
} else {
  const lines = [];
  for (const [title, values] of [
    ["本周重点", taskLines(result.dailies, "今日重点")],
    ["其他事项", listLines(result.dailies, ["工作记录", "临时需求", "问题反馈"])],
    ["感想", listLines(result.dailies, ["学习&思考"])],
    ["下周计划", taskLines(result.dailies, "明日计划")],
  ]) {
    lines.push(`## ${title}`);
    lines.push(...(values.length ? values : ["- 无"]));
    lines.push("");
  }
  dv.paragraph("```text\n" + lines.join("\n").trimEnd() + "\n```");
}
```

---
关联月报：[[{{date:YYYY-MM}}]]
