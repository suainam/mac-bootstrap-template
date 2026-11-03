import fs from "fs";
import path from "path";
import os from "os";

let cachedBridgeClient = null;

/**
 * 跨平台/跨目录自动寻址 huashu-chrome 运行库
 */
export async function findBridgeClient() {
  if (cachedBridgeClient) return cachedBridgeClient;

  // 1. 本地 node_modules
  try {
    const local = await import("huashu-chrome/src/lib/rpc.js");
    cachedBridgeClient = local.BridgeClient;
    return cachedBridgeClient;
  } catch {}

  // 2. npx 缓存目录逆序查找（优先最新版本）
  const npxDir = path.join(os.homedir(), ".npm/_npx");
  if (fs.existsSync(npxDir)) {
    const subdirs = fs.readdirSync(npxDir).reverse();
    for (const sub of subdirs) {
      const candidate = path.join(npxDir, sub, "node_modules/huashu-chrome/src/lib/rpc.js");
      if (fs.existsSync(candidate)) {
        const mod = await import(candidate);
        cachedBridgeClient = mod.BridgeClient;
        return cachedBridgeClient;
      }
    }
  }

  // 3. 全局 node_modules 常见路径
  const globalPaths = [
    "/usr/local/lib/node_modules/huashu-chrome/src/lib/rpc.js",
    path.join(os.homedir(), ".nvm/versions/node", process.version, "lib/node_modules/huashu-chrome/src/lib/rpc.js")
  ];
  for (const gp of globalPaths) {
    if (fs.existsSync(gp)) {
      const mod = await import(gp);
      cachedBridgeClient = mod.BridgeClient;
      return cachedBridgeClient;
    }
  }

  throw new Error("未能找到 huashu-chrome 运行库，请运行 npx huashu-chrome 或 npm i -g huashu-chrome");
}

/**
 * 获取连接到真实 Chrome 登录会话的 huashu-chrome 客户端
 * @param {Object} options
 * @param {string} options.client 客户端标识，默认 "huashu-automation"
 * @param {string} options.label 会话标签
 * @param {string} options.sessionId 指定持久化会话 ID
 */
export async function getHuashuClient({ client: clientName = "huashu-automation", label, sessionId } = {}) {
  const BridgeClient = await findBridgeClient();
  const client = new BridgeClient({ client: clientName, label, sessionId });
  await client.connect();
  if (!client.extensionOnline) {
    throw new Error("huashu-chrome 扩展未在线或处于休眠状态，请先激活 Chrome 扩展");
  }
  return client;
}
/**
 * 仅在顶层 Frame 执行原生 fetch（穿透跨域 iframe 权限壁垒并自动复用当前站点登录态）
 */
export async function callTopFetch(client, { tabId, url, method = "GET", headers = {}, body }) {
  const init = {
    method,
    headers: { "X-Atlassian-Token": "nocheck", ...headers }
  };
  if (body) {
    init.body = typeof body === "string" ? body : JSON.stringify(body);
    if (!init.headers["Content-Type"] && typeof body !== "string") {
      init.headers["Content-Type"] = "application/json";
    }
  }
  const res = await client.call("fetch", { url, init }, { tabId });
  return res;
}

/**
 * 在页面环境直接上传文件到 Confluence 附件端点（免下载与防截断）
 */
export async function uploadAttachmentToPage(client, { tabId, pageId, fileName, content, comment = "" }) {
  const expr = `
    (async () => {
      const content = ${JSON.stringify(content)};
      const fileName = ${JSON.stringify(fileName)};
      const pageId = ${JSON.stringify(pageId)};
      const comment = ${JSON.stringify(comment)};
      
      const fd = new FormData();
      fd.append("file", new Blob([content], { type: "application/octet-stream" }), fileName);
      if (comment) fd.append("comment", comment);

      const res = await fetch(\`/rest/api/content/\${pageId}/child/attachment\`, {
        method: "POST",
        headers: { "X-Atlassian-Token": "nocheck" },
        body: fd
      });
      return { status: res.status, text: (await res.text()).slice(0, 500) };
    })()
  `;
  return await client.call("eval", { expr }, { tabId });
}
// CLI 执行模式：node huashu_driver.mjs <cmd> [json_params]
if (process.argv[1] && process.argv[1].endsWith("huashu_driver.mjs")) {
  const [,, cmd, argJson] = process.argv;
  if (!cmd) {
    console.log("用法: node huashu_driver.mjs <cmd> [json_params]");
    console.log("示例: node huashu_driver.mjs tabs '{\"action\":\"list\"}'");
    console.log("      node huashu_driver.mjs snapshot '{\"tabId\":12345}'");
    process.exit(1);
  }
  const params = argJson ? JSON.parse(argJson) : {};
  const client = await getHuashuClient();
  try {
    if (params.tabId) {
      await client.call("tabs", { action: "select", tabId: params.tabId }).catch(() => {});
    }
    const res = await client.call(cmd, params);
    console.log(JSON.stringify(res, null, 2));
  } finally {
    client.close();
  }
}
