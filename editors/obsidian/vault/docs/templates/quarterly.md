---
type: journal
period: quarterly
status: active
owner: local-user
date: {{date:YYYY-[Q]Q}}
year: {{date:YYYY}}
tags: [quarterly, work-log]
---

# {{date:YYYY年第Q季度}}工作总结

## 季度概览

## AI 总结

<!-- 由 quarterly_summary.py 自动填入 -->

## 重点工作

## 问题与风险

## 成长与提升

### 新业绩

### 新贡献

### 新创新

### 新成长

## 下季重点

1.
2.
3.

## 自动汇总

```dataviewjs
async function main() {
  function quarterId() {
    return String(dv.current().date ?? dv.current().file.name);
  }

  function valueToQuarter(value) {
    if (!value) return "";
    return String(value);
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

  const currentQuarter = quarterId();
  const monthlies = dv.pages('"docs/monthly"')
    .where((page) => valueToQuarter(page.quarter) === currentQuarter)
    .sort((page) => page.file.name, "asc");

  if (!monthlies.length) {
    dv.paragraph("> 暂无本季月报");
  } else {
    dv.header(3, "月报覆盖");
    dv.list(monthlies.map((page) => page.file.link));

    for (const heading of ["月度概览", "重点工作", "问题与风险", "心得与思考", "下月重点"]) {
      dv.header(3, heading);
      let rendered = false;
      for (const page of monthlies) {
        const content = (await dv.io.load(page.file.path)).replace(/\r\n/g, "\n");
        const text = sectionText(content, heading);
        if (!text) continue;
        rendered = true;
        dv.header(5, page.file.name);
        dv.paragraph(text);
      }
      if (!rendered) dv.paragraph(`> 各月暂无${heading}`);
    }
  }}

main();
```

---
关联年报：[[{{date:YYYY}}]]
