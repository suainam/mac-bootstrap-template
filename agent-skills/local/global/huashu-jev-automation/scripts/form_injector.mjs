import fs from "fs";
import path from "path";
import { getHuashuClient } from "./huashu_driver.mjs";

/**
 * 通用表单受控组件与动态文件上传注入工具库 (Form Injector)
 * 解决三大前端框架顽疾：
 * 1. Vue/React 受控组件 direct value setter 失效
 * 2. 动态生成的 input[type=file] 或拖拽区域文件注入
 * 3. 提报防错断言（Four-Gate 安全门禁）
 */

/**
 * 注入文本至 Vue/React 受控输入框/文本域（触发真实响应式更新）
 */
export async function injectControlledText(client, tabId, selector, text) {
  return await client.call("eval", {
    tabId,
    expr: `(() => {
      const el = document.querySelector(${JSON.stringify(selector)});
      if (!el) return { success: false, error: "未找到元素: " + ${JSON.stringify(selector)} };
      
      el.focus();
      // 获取原型链上的原始 setter（绕过 Vue/React 拦截）
      const proto = el instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
      const nativeSetter = Object.getOwnPropertyDescriptor(proto, 'value')?.set;
      
      if (nativeSetter) {
        nativeSetter.call(el, ${JSON.stringify(text)});
      } else {
        el.value = ${JSON.stringify(text)};
      }
      
      // 派发冒泡的受控事件
      el.dispatchEvent(new Event('input', { bubbles: true }));
      el.dispatchEvent(new Event('change', { bubbles: true }));
      return { success: true, valueLength: el.value.length };
    })()`
  });
}

/**
 * 注入本地文件到 Web 表单 input[type=file]（即使无拖拽区域或动态渲染）
 */
export async function injectFileUpload(client, tabId, inputSelector, localFilePath) {
  if (!fs.existsSync(localFilePath)) {
    throw new Error(`本地文件不存在: ${localFilePath}`);
  }
  const fileBuf = fs.readFileSync(localFilePath);
  const base64Data = fileBuf.toString("base64");
  const fileName = path.basename(localFilePath);
  const mimeType = fileName.endsWith(".png") ? "image/png" : fileName.endsWith(".jpg") || fileName.endsWith(".jpeg") ? "image/jpeg" : "application/octet-stream";

  return await client.call("eval", {
    tabId,
    expr: `(() => {
      const input = document.querySelector(${JSON.stringify(inputSelector)});
      if (!input) return { success: false, error: "未找到 input 元素: " + ${JSON.stringify(inputSelector)} };
      
      const b64 = "${base64Data}";
      const byteChars = atob(b64);
      const byteNums = new Array(byteChars.length);
      for (let i = 0; i < byteChars.length; i++) {
        byteNums[i] = byteChars.charCodeAt(i);
      }
      const byteArray = new Uint8Array(byteNums);
      const file = new File([byteArray], "${fileName}", { type: "${mimeType}" });
      
      const dt = new DataTransfer();
      dt.items.add(file);
      input.files = dt.files;
      
      input.dispatchEvent(new Event('input', { bubbles: true }));
      input.dispatchEvent(new Event('change', { bubbles: true }));
      return { success: true, fileName: "${fileName}", size: byteArray.length };
    })()`
  });
}

/**
 * 严格单实例文件上传检查
 */
export async function assertUploadSingleInstance(client, tabId, itemSelector) {
  return await client.call("eval", {
    tabId,
    expr: `(() => {
      const items = document.querySelectorAll(${JSON.stringify(itemSelector)});
      return {
        count: items.length,
        isSingle: items.length === 1,
        files: Array.from(items).map(el => el.innerText.trim())
      };
    })()`
  });
}
