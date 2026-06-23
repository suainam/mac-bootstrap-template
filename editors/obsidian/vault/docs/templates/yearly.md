---
type: journal
period: yearly
status: active
owner: local-user
date: {{date:YYYY}}
tags: [yearly, work-log]
---

# {{date:YYYY年}}年度总结

## 年度概览

## 重点工作

## 问题与风险

## 成长与思考

## 明年规划

## 自动汇总

```dataviewjs
async function main() {
  function yearId() {
    return String(dv.current().date ?? dv.current().file.name);
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

  const currentYear = yearId();
  const quarterlies = dv.pages('"docs/quarterly"')
    .where((page) => String(page.year ?? page.file.name).startsWith(currentYear))
    .sort((page) => page.file.name, "asc");

  if (!quarterlies.length) {
    dv.paragraph("> 暂无本年季报");
  } else {
    dv.header(3, "季报覆盖");
    dv.list(quarterlies.map((page) => page.file.link));

    for (const heading of ["季度概览", "重点工作", "问题与风险", "成长与提升", "下季重点"]) {
      dv.header(3, heading);
      let rendered = false;
      for (const page of quarterlies) {
        const content = (await dv.io.load(page.file.path)).replace(/\r\n/g, "\n");
        const text = sectionText(content, heading);
        if (!text) continue;
        rendered = true;
        dv.header(5, page.file.name);
        dv.paragraph(text);
      }
      if (!rendered) dv.paragraph(`> 各季暂无${heading}`);
    }
  }}

main();
```
