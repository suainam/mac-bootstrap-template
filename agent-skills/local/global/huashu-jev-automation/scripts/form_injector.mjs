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

/**
 * 严格多图上传防重检查与去重断言门禁 (Deduplication Gate)
 * 解决多图表单（如腾讯文档表单、观点小卡、平台共建）中异步删除延迟或重复注入导致相同图片上传的问题
 */
export async function assertUploadDeduplication(client, tabId, options = {}) {
  const {
    containerSelector = '.question',
    thumbnailSelector = 'img.FileCore-module_picture__xamH2, [class*="thumbnail"], [class*="picture"], [class*="image-item"]',
    expectedCount = null
  } = options;

  const result = await client.call("eval", {
    tabId,
    expr: `(() => {
      const imgs = Array.from(document.querySelectorAll(${JSON.stringify(thumbnailSelector)}));
      const seen = new Map();
      const duplicates = [];

      imgs.forEach((img, idx) => {
        // 获取图片指纹（src、alt、尺寸或背景图）
        const src = img.src || img.getAttribute('src') || '';
        const key = src ? src.split('?')[0] : (img.naturalWidth + 'x' + img.naturalHeight + '_' + img.alt);
        
        if (seen.has(key)) {
          duplicates.push({
            index: idx,
            firstIndex: seen.get(key),
            key: key.slice(0, 80)
          });
        } else {
          seen.set(key, idx);
        }
      });

      const total = imgs.length;
      const uniqueCount = seen.size;
      const hasDuplicates = duplicates.length > 0;

      return {
        total,
        uniqueCount,
        hasDuplicates,
        duplicates,
        passed: !hasDuplicates && (${JSON.stringify(expectedCount)} === null || total === ${JSON.stringify(expectedCount)})
      };
    })()`
  });

  return result;
}

/**
 * 安全清空旧附件并等待 DOM 彻底清除后再注入唯一文件列表
 */
export async function cleanAndInjectUniqueFiles(client, tabId, options) {
  const {
    deleteButtonSelector = '.FileCore-module_deleteContainer__yEQGJ, [class*="delete"], [class*="remove"]',
    thumbnailSelector = 'img.FileCore-module_picture__xamH2, [class*="thumbnail"], [class*="picture"]',
    fileInputSelector = 'input[type="file"]',
    filePaths = [],
    maxWaitMs = 5000
  } = options;

  // 1. 本地文件唯一性校验（防止调用方传入重复路径）
  const uniquePaths = Array.from(new Set(filePaths.map(p => path.resolve(p))));
  if (uniquePaths.length !== filePaths.length) {
    throw new Error(`传入待上传文件列表存在本地重复路径: 总数 ${filePaths.length} vs 唯一 ${uniquePaths.length}`);
  }

  // 2. 清理已存在的图片并等待 DOM 彻底归零
  await client.call("eval", {
    tabId,
    expr: `(() => {
      const btns = Array.from(document.querySelectorAll(${JSON.stringify(deleteButtonSelector)}));
      btns.forEach(b => b.click());
      return { clickedCount: btns.length };
    })()`
  });

  // 等待旧图全部消失
  const start = Date.now();
  while (Date.now() - start < maxWaitMs) {
    const check = await client.call("eval", {
      tabId,
      expr: `document.querySelectorAll(${JSON.stringify(thumbnailSelector)}).length`
    });
    const count = typeof check === 'number' ? check : (check?.result ?? 0);
    if (count === 0) break;
    await new Promise(r => setTimeout(r, 300));
  }

  // 3. 构建唯一文件的 DataTransfer
  const filePayloads = uniquePaths.map(fp => {
    const buf = fs.readFileSync(fp);
    const name = path.basename(fp);
    const mime = fp.endsWith('.png') ? 'image/png' : fp.endsWith('.jpg') || fp.endsWith('.jpeg') ? 'image/jpeg' : 'application/octet-stream';
    return { name, type: mime, b64: buf.toString('base64') };
  });

  // 注入
  await client.call("eval", {
    tabId,
    expr: `(() => {
      function b64toFile(b64, name, type) {
        const chars = atob(b64);
        const nums = new Array(chars.length);
        for (let i = 0; i < chars.length; i++) nums[i] = chars.charCodeAt(i);
        return new File([new Uint8Array(nums)], name, { type });
      }
      const payloads = ${JSON.stringify(filePayloads)};
      const dt = new DataTransfer();
      payloads.forEach(p => dt.items.add(b64toFile(p.b64, p.name, p.type)));

      const inputs = Array.from(document.querySelectorAll(${JSON.stringify(fileInputSelector)}));
      if (inputs.length === 0) return { error: 'no_file_input' };
      const targetInput = inputs[inputs.length - 1];

      targetInput.files = dt.files;
      targetInput.dispatchEvent(new Event('input', { bubbles: true }));
      targetInput.dispatchEvent(new Event('change', { bubbles: true }));
      return { injected: dt.files.length };
    })()`
  });

  // 等待渲染并严格校验去重
  await new Promise(r => setTimeout(r, 2000));
  const dedupeCheck = await assertUploadDeduplication(client, tabId, {
    thumbnailSelector,
    expectedCount: uniquePaths.length
  });

  if (dedupeCheck.hasDuplicates || dedupeCheck.total !== uniquePaths.length) {
    throw new Error(`图片注入去重门禁失败: 期望 ${uniquePaths.length} 张，渲染出 ${dedupeCheck.total} 张 (唯一 ${dedupeCheck.uniqueCount})，检出重复项: ` + JSON.stringify(dedupeCheck.duplicates));
  }

  return { success: true, count: dedupeCheck.total };
}
