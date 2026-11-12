#!/usr/bin/env node
// PRD 评分迭代三件套：snapshot（基线+回退点）→ save（直写+精确回读）→ rescore（等缓存+按 create_time 判新分）
// 依赖 huashu-jev-automation 的 huashu_driver / prd_workbench；所有 eval 返回对象（扩展只解析 JSON 对象）。
// 用法：node prd_iterate.mjs <snapshot|save|rescore> <Story-XXXXXX> [--file md] [--out dir] [--tab id] [--wait 45]
import fs from "fs";
import os from "os";
import path from "path";
import crypto from "crypto";
import { pathToFileURL } from "url";

const SCRIPTS = path.join(os.homedir(), ".agents/skills/huashu-jev-automation/scripts");
const { getHuashuClient } = await import(pathToFileURL(path.join(SCRIPTS, "huashu_driver.mjs")));
const { parseEvalReturn, directSavePrd, dumpPrdStatus } = await import(pathToFileURL(path.join(SCRIPTS, "prd_workbench.mjs")));

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const sha = (s) => crypto.createHash("sha256").update(s).digest("hex").slice(0, 12);

// 仅用 new RegExp(字符串)：expr 内的字面量正则里的反斜杠会被转义吞掉（"Invalid regular expression flags"）。
const STATE_EXPR = `(() => {
  const text = document.body.innerText;
  const btn = Array.from(document.querySelectorAll('button')).find(b => new RegExp('重新评分|重新检测').test(b.innerText));
  const out = { title: document.title, editMode: !!document.querySelector('.vditor-ir'), hasScoreButton: !!btn,
    calculating: new RegExp('正在重新检测|正在计算评分|检测中|评分中').test(text), score: null, backendPrd: null, story: null };
  const k = btn && Object.keys(btn).find(x => x.startsWith('__reactFiber'));
  let f = k ? btn[k] : null;
  while (f) {
    const p = f.memoizedProps || {};
    if (!out.score && p.score && p.score.final_score != null) out.score = p.score;
    if (!out.backendPrd && p.backendPrd) { const b = p.backendPrd; out.backendPrd = { prdId: b.prdId, storyCode: b.storyCode, moduleId: b.moduleId, version: b.version, filePath: b.filePath }; }
    if (!out.story && p.currentStory) out.story = { title: p.currentStory.title, description: p.currentStory.description };
    f = f.return;
  }
  return out;
})()`;

const args = process.argv.slice(2);
const [cmd, story] = args;
const opt = (flag, dflt = null) => { const i = args.indexOf(flag); return i >= 0 && args[i + 1] ? args[i + 1] : dflt; };
if (!["snapshot", "save", "rescore"].includes(cmd) || !/^Story-\d+$/.test(story || "")) {
  console.error("用法: prd_iterate.mjs <snapshot|save|rescore> <Story-XXXXXX> [--file md] [--out dir] [--tab id] [--wait 45]");
  process.exit(1);
}
const outDir = opt("--out", path.join("/tmp/prd-score", story));
fs.mkdirSync(outDir, { recursive: true });

const client = await getHuashuClient();
const ev = async (tabId, expr) => parseEvalReturn(await client.call("eval", { expr, tabId }));
const readState = (tabId) => ev(tabId, STATE_EXPR);

async function findTab() {
  if (opt("--tab")) return parseInt(opt("--tab"), 10);
  const res = await client.call("tabs", { action: "list" });
  const line = String(res?.text ?? "").split("\n").find((l) => l.includes(`#/prototype/${story}`));
  const m = line && line.match(/^\[(\d+)\]/);
  if (!m) throw new Error(`未找到已打开的 ${story} 原型工作台标签页（不要新开无登录态实例）`);
  return parseInt(m[1], 10);
}
const fetchText = async (tabId, url) => {
  const r = await ev(tabId, `(async () => { const r = await fetch(${JSON.stringify(url)}); return { status: r.status, text: await r.text() }; })()`);
  if (r.status !== 200) throw new Error(`读取持久化 PRD 失败 HTTP ${r.status}`);
  return r.text;
};
const stripHtml = (h = "") => h.replace(/<br\s*\/?>/g, "\n").replace(/<[^>]+>/g, "").replace(/&gt;/g, ">").replace(/&lt;/g, "<").replace(/&amp;/g, "&");
const printScore = (s) => {
  console.log(`final_score=${s.final_score}  create_time=${s.create_time}`);
  console.log("维度:", (s.dimensions || []).map((d) => `${d.dimension}=${d.score}`).join(" "));
  for (const i of s.issues || []) {
    console.log(`- [${i.severity}] ${i.dimension} ${i.root_cause_key}\n    问题: ${i.problem}\n    建议: ${i.suggestion}\n    位置: ${(i.evidence_locations || []).join(" ｜ ")}`);
  }
};
const requireViewState = (st) => {
  if (!st.hasScoreButton || !st.score || !st.backendPrd) {
    throw new Error(`页面不在可评分视图（editMode=${st.editMode}, title=${st.title}）。先退出编辑并 reload。`);
  }
};

const tabId = await findTab();
await client.call("tabs", { action: "select", tabId }).catch(() => {});
if (cmd === "snapshot") {
  const st = await readState(tabId);
  requireViewState(st);
  if (st.backendPrd.storyCode !== story) throw new Error(`标签页绑定 ${st.backendPrd.storyCode}，与 ${story} 不符`);
  const md = await fetchText(tabId, st.backendPrd.filePath);
  const baseline = path.join(outDir, "baseline.prd.md");
  if (!fs.existsSync(baseline)) {
    fs.writeFileSync(baseline, md);
    fs.writeFileSync(path.join(outDir, "baseline.score.json"), JSON.stringify(st.score, null, 2));
  }
  fs.writeFileSync(path.join(outDir, "latest.prd.md"), md);
  fs.writeFileSync(path.join(outDir, "latest.score.json"), JSON.stringify(st.score, null, 2));
  fs.writeFileSync(path.join(outDir, "story.txt"), stripHtml(st.story?.description));
  fs.writeFileSync(path.join(outDir, "meta.json"), JSON.stringify({ tabId, ...st.backendPrd, mdSha: sha(md) }, null, 2));
  console.log(`tab=${tabId} prd_id=${st.backendPrd.prdId} module_id=${st.backendPrd.moduleId} md=${md.length}字符 sha=${sha(md)}`);
  console.log(`落盘: ${outDir}/{baseline.prd.md(回退点),latest.prd.md,latest.score.json,story.txt(原始需求事实源),meta.json}`);
  printScore(st.score);
} else if (cmd === "save") {
  const file = opt("--file");
  if (!file || !fs.existsSync(file)) throw new Error("--file 必须是存在的 Markdown 文件");
  if (!fs.existsSync(path.join(outDir, "baseline.prd.md"))) throw new Error(`缺回退点：先运行 snapshot（需要 ${outDir}/baseline.prd.md）`);
  const md = fs.readFileSync(file, "utf8");

  let st = await readState(tabId);
  if (!st.editMode) {
    requireViewState(st);
    await ev(tabId, `(() => { const b = Array.from(document.querySelectorAll('button')).find(x => x.innerText.trim() === '编辑'); if (!b) return { ok: false }; const k = Object.keys(b).find(k => k.startsWith('__reactFiber')); let f = k ? b[k] : null; while (f) { if (typeof f.memoizedProps?.onClick === 'function') { f.memoizedProps.onClick(); return { ok: true }; } f = f.return; } b.click(); return { ok: true }; })()`);
    await sleep(900);
  }
  const bind = await dumpPrdStatus(client, tabId);
  if (bind.storyCode !== story || !bind.editMode) throw new Error(`编辑态绑定异常: ${JSON.stringify({ storyCode: bind.storyCode, prdId: bind.prdId, editMode: bind.editMode })}`);

  const saved = await directSavePrd(client, tabId, md);
  if (!saved.ok || !saved.saveRes?.file_path) throw new Error(`保存失败: ${JSON.stringify(saved)}`);
  const back = await fetchText(tabId, saved.saveRes.file_path);
  if (back !== md) throw new Error(`回读与提交正文不一致（提交 ${md.length} / 回读 ${back.length}）`);
  console.log(`已持久化 prd_id=${saved.saveRes.prd_id} module_id=${saved.saveRes.file_path.match(/module_(\d+)/)?.[1]} changed_fields=${(saved.saveRes.changed_fields || []).join(",")} 回读精确一致 sha=${sha(md)}`);

  // 退出编辑：取消编辑 → 放弃修改（正文已落库，放弃的只是编辑器草稿）→ reload 清掉“● 未保存”残留
  await ev(tabId, `(() => { const b = Array.from(document.querySelectorAll('button')).find(x => x.innerText.trim() === '取消编辑'); if (b) b.click(); return { ok: true, clicked: !!b }; })()`);
  await sleep(400);
  await ev(tabId, `(() => { const b = Array.from(document.querySelectorAll('button')).find(x => x.innerText.trim() === '放弃修改'); if (b) b.click(); return { ok: true, clicked: !!b }; })()`);
  await sleep(400);
  try { await ev(tabId, `(() => { location.reload(); return { ok: true }; })()`); } catch { /* 导航中断属预期 */ }
  for (let i = 0; i < 10; i++) {
    await sleep(1500);
    st = await readState(tabId).catch(() => ({ hasScoreButton: false }));
    if (st.hasScoreButton && !String(st.title).startsWith("● 未保存") && !st.editMode) break;
  }
  requireViewState(st);
  console.log("已退出编辑并 reload；下一步 rescore（脚本自带约 45s 缓存等待）");
} else {
  const wait = parseInt(opt("--wait", "45"), 10);
  const before = await readState(tabId);
  requireViewState(before);
  const t0 = before.score.create_time;
  console.log(`基线分 ${before.score.final_score} (create_time=${t0})；等待缓存 ${wait}s`);
  await sleep(wait * 1000);
  const click = await ev(tabId, `(() => { const b = Array.from(document.querySelectorAll('button')).find(x => new RegExp('重新评分|重新检测').test(x.innerText.trim())); if (!b) return { ok: false }; const k = Object.keys(b).find(k => k.startsWith('__reactFiber')); let f = k ? b[k] : null; while (f) { if (typeof f.memoizedProps?.onClick === 'function') { f.memoizedProps.onClick(); return { ok: true }; } f = f.return; } b.click(); return { ok: true }; })()`);
  if (!click.ok) throw new Error("未找到重新评分按钮");
  let now = null;
  for (let t = 0; t < 110; t += 5) {
    await sleep(5000);
    now = await readState(tabId);
    if (now.score && !now.calculating && now.score.create_time !== t0) break;
    now = null;
  }
  if (!now) { console.error("create_time 未变化：评分仍是缓存旧结果。再等 30~60s 后重跑 rescore --wait 0"); process.exit(2); }
  fs.writeFileSync(path.join(outDir, "latest.score.json"), JSON.stringify(now.score, null, 2));
  printScore(now.score);
}
process.exit(0);
