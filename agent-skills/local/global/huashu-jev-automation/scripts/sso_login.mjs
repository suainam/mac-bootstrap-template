import fs from "fs";
import path from "path";
import os from "os";
import { getHuashuClient } from "./huashu_driver.mjs";

const sleep = ms => new Promise(r => setTimeout(r, ms));

/**
 * 读取本地 SSO 凭据配置
 */
export function loadSSOCredentials(envFile = null) {
  const targetPath = envFile || path.join(os.homedir(), ".sso-tech-committee.env");
  if (!fs.existsSync(targetPath)) {
    throw new Error(`SSO 配置文件未找到: ${targetPath}`);
  }
  const content = fs.readFileSync(targetPath, "utf-8");
  const envVars = {};
  for (const line of content.split("\n")) {
    const trimmed = line.trim();
    if (trimmed && !trimmed.startsWith("#") && trimmed.includes("=")) {
      const [k, ...v] = trimmed.split("=");
      envVars[k.trim()] = v.join("=").trim();
    }
  }
  if (!envVars.SSO_USERNAME || !envVars.SSO_PASSWORD) {
    throw new Error("SSO 配置文件缺少 SSO_USERNAME 或 SSO_PASSWORD");
  }
  return envVars;
}

/**
 * 在目标 SSO 标签页执行自动账号密码注入并提交
 */
export async function performSSOLogin(client, tabId, { envFile = null, timeoutMs = 15000 } = {}) {
  const creds = loadSSOCredentials(envFile);

  await client.call("tabs", { action: "select", tabId }).catch(() => {});

  const injectExpr = `
    (() => {
      const passportInput = document.querySelector("input[name='loginWay'][value='passport']");
      if (!passportInput) return { success: false, error: "未找到 passport 登录表单" };
      const form = passportInput.closest("form");
      if (!form) return { success: false, error: "未找到表单容器" };

      const uInput = form.querySelector("input[name='username']");
      const pInput = form.querySelector("input[name='password']");
      if (!uInput || !pInput) return { success: false, error: "未找到用户名或密码输入框" };

      const setVal = (el, val) => {
        el.focus();
        const proto = HTMLInputElement.prototype;
        const setter = Object.getOwnPropertyDescriptor(proto, 'value')?.set;
        if (setter) {
          setter.call(el, val);
        } else {
          el.value = val;
        }
        el.dispatchEvent(new Event('input', { bubbles: true }));
        el.dispatchEvent(new Event('change', { bubbles: true }));
      };

      setVal(uInput, ${JSON.stringify(creds.SSO_USERNAME)});
      setVal(pInput, ${JSON.stringify(creds.SSO_PASSWORD)});

      const submitBtn = form.querySelector(".login-content__form-submit");
      if (submitBtn) {
        submitBtn.click();
        return { success: true };
      }
      return { success: false, error: "未找到登录提交按钮" };
    })()
  `;

  const injectRes = await client.call("eval", { tabId, expr: injectExpr });
  const cleanInjectText = injectRes.text.replace(/（提示：.*?）/gs, "").trim();
  const injectData = JSON.parse(cleanInjectText);

  if (!injectData.success) {
    return { success: false, error: injectData.error };
  }

  // 轮询检查是否完成重定向
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    await sleep(800);
    const snap = await client.call("snapshot", { tabId }).catch(() => null);
    if (!snap) continue;
    if (!snap.text.includes("sso.dslbuy.com/login")) {
      return { success: true, text: "SSO 登录成功，已重定向至目标页面" };
    }
  }

  return { success: false, error: "登录提交超时，可能卡在安全验证码或凭据错误" };
}

// CLI 执行模式
if (process.argv[1] && process.argv[1].endsWith("sso_login.mjs")) {
  const [,, rawTabId, envFile] = process.argv;
  if (!rawTabId) {
    console.log("用法: node sso_login.mjs <tabId> [envFile]");
    console.log("示例: node sso_login.mjs 713198917");
    process.exit(1);
  }

  const tabId = parseInt(rawTabId, 10);
  const client = await getHuashuClient();

  try {
    console.log(`正在对标签页 [${tabId}] 执行 SSO 自动登录...`);
    const res = await performSSOLogin(client, tabId, { envFile });
    console.log("执行结果:", JSON.stringify(res, null, 2));
  } finally {
    client.close();
  }
}
