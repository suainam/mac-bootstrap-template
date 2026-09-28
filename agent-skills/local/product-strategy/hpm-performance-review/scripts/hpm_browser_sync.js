/**
 * HPM 季度绩效表单自动化录入脚本模板 (Playwriter Runner)
 * 
 * 用法:
 *   1. playwriter session new
 *   2. playwriter -s <SESSION_ID> -e "$(cat skills/hpm-performance-review/scripts/hpm_browser_sync.js)"
 */

async function syncHpmReview() {
  const pages = page.context().pages();
  const hpmPage = pages.find(p => p.url().includes("/achievement"));
  if (!hpmPage) {
    console.error("未找到 HPM 责任书标签页，请先在 Chrome 中打开目标页面。");
    return;
  }
  await hpmPage.bringToFront();
  console.log("已激活标签页:", await hpmPage.title());

  // 1. 确保切换到“绩效责任书”Tab
  await hpmPage.locator("#tab-detail").click();
  await hpmPage.waitForTimeout(500);

  // 2. 定性指标 (3.1 ~ 3.6) 配置 (行索引 6 ~ 11)
  const qualitativeItems = [
    {
      rowIdx: 6, // 3.1 专业知识/技能
      text: `1、质量保障：季度内组货模型、O2O中心店、缩铺、自动陈列及Agent探索等策略按期交付，无返工或系统故障（P0/P1为0）。\n2、沉淀文档2份：\n- 《非目录商品缩铺配置与结果校验标准SOP》：梳理调度防白跑机制与校验门禁，固化为操作指引；\n- 《O2O重点店/中心店组货效益评估与Cohort追踪方法论》：明确策略同品池回溯口径与Excel自动导出规范。`
    },
    {
      rowIdx: 7, // 3.2 计划/组织/执行/解决问题能力
      text: `1、按期交付：缩铺试点推广、O2O中心店模型落地、49家新店组货及清远阳江陈列推广均按计划完成。\n2、解决问题：\n- 缩铺推广中针对库存消化风险，设计分批次退清和动态分母模型，平稳推进粤西、大广州、粤东库存成本下降984.78万元；\n- 发现智能组货工作流去年同期对比门店漂移问题（门店池差2920店），通过在预聚合层锁定本期门店池并补齐回刷，修复了历史数据。`
    },
    {
      rowIdx: 8, // 3.3 沟通与团队协作能力
      text: `1、日常响应：对业务部门和技术团队的提问与排查需求，均在工作时间内及时回复跟进，无沟通推诿或投诉。\n2、跨组推进：\n- 自动陈列推广中拉通空间布局、陈列系统与百科，跟进货架编码适配、清远阳江陈列图验证和拍照执行流程；\n- O2O中心店组货中与美团外卖业务线密切对接，完成美团与淘闪城市TOP2500目录落地。`
    },
    {
      rowIdx: 9, // 3.4 学习与发展能力
      text: `1、技能应用：跟进大模型Agent开发，搭建单容器核心并跑通工具调用与上下文管理，在数据分析场景尝试落地；针对大数据量报表，引入Arrow/Parquet本地处理方案，降低导出等待时间。\n2、业务复盘：对组货策略13个模型逐一复盘，梳理品种齐全和补充主推2个需调优模型的问题点并出具调整方案。`
    },
    {
      rowIdx: 10, // 3.5 创新能力
      text: `1、策略优化：在原有O2O重点店基础上扩展蜂窝品、美团TOP2500、淘闪TOP2500和JDT销量TOP2000，丰富中心店选品策略。\n2、流程提效：优化报表处理与数据流转方式，改变过去多段SQL与逐行写Excel的耗时模式，减少集群资源占用和等待时间。`
    },
    {
      rowIdx: 11, // 3.6 专业影响力
      text: `1、数据支撑：直营组货销售占比+10.01%、毛利额占比+9.97%、动销率+1.66%，为业务调整目录结构提供数据依据。\n2、推广协同：新店模型向华南、西南、西北三大区推广49家新店，缩铺策略在粤东、广佛、粤西逐步落地，业务沟通与配合更顺畅。`
    }
  ];

  for (const item of qualitativeItems) {
    const row = hpmPage.locator("table tr").nth(item.rowIdx);
    
    // 确保选择 1档
    const select = row.locator(".el-input__inner").first();
    const curVal = await select.inputValue();
    if (!curVal.includes("1档")) {
      await select.click();
      await hpmPage.waitForTimeout(300);
      await hpmPage.evaluate(() => {
        const popups = Array.from(document.querySelectorAll(".el-select-dropdown__item, [role=\"option\"]"));
        const opt = popups.find(p => p.offsetParent !== null && p.innerText.includes("1档"));
        if (opt) opt.click();
      });
      await hpmPage.waitForTimeout(300);
    }

    // 唤起只读 Popover 并填入纯文本
    const textarea = row.locator("textarea");
    await textarea.click();
    await hpmPage.waitForTimeout(300);

    const popover = hpmPage.locator(".el-popper.is-light.el-popover:not([style*=\"display: none\"])");
    const pTextarea = popover.locator("textarea");
    await pTextarea.fill(item.text);
    await hpmPage.waitForTimeout(200);

    await popover.locator("button:has-text(\"确认\")").click();
    await hpmPage.waitForTimeout(300);
  }
  console.log("通用力定性指标录入完毕。");

  // 3. 录入综合评价 (员工自我评价 Tab)
  await hpmPage.locator("#tab-selfEvaluation").click();
  await hpmPage.waitForTimeout(600);

  const textFupan = `新业绩\n- 门店智能组货：直营组货全店动销率+1.66%（达成率166%），销售占比+10.01%、毛利额占比+9.97%；新店组货完成模型优化，在华南、西南、西北三大区推广49家新店，动销率39.59%，店均提效2-3小时。\n- 策略落地推进：缩铺策略落地粤西、大广州、粤东，库存成本下降984.78万元，店品数下降10.40万个；O2O中心店完成蜂窝品、美团TOP2500、淘闪TOP2500落地；清远阳江自动陈列完成推广，全中类试点销售米效环比+2.4%、毛利米效环比+2.2%。\n\n新贡献\n- 沉淀非目录商品缩铺与退清方案，梳理数仓防白跑校验门禁，支撑三省区库存消化。\n- 搭建多渠道O2O中心店选品策略，把线上平台大盘与店内品效对齐。\n- 参与商品决策数据Agent建设，完成核心层与工具层联调，探索数据分析的AI辅助形式。\n\n新创新\n- O2O组货引入同城蜂窝品与平台TOP2500，把选品逻辑从单店静态匹配转为城市动态供给。\n- 探索Arrow/Parquet数据流转方案，解决几十万行大报表在数仓反复计算和导出的性能瓶颈。\n- 搭建Agent会话复用与工具调用流程，尝试用对话方式查询指标与策略数据。\n\n新成长\n- 跨团队协同更主动：在陈列、缩铺、O2O项目中拉通空间布局、陈列系统、百科和前线营运，跟进落地细节。\n- 工程实现与架构意识提升：从写离线SQL分析，扩展到思考Agent工具化、自动化校验和数据流转效率。\n- 业务理解更完整：从单纯算指标，延伸到商品从选品、陈列、补货到缩铺淘汰的全链路逻辑。`;

  const textJihui = `1. 策略推广扩大覆盖：缩铺和O2O中心店策略目前在部分重点省区验证完成，下一步需要继续配合业务向更多省区复制。\n2. Agent融入实际业务：核心技术链路跑通后，后续需要结合业务看盘和采购的真实高频场景，把交互和分析意图磨得更准。\n3. 跨团队协作机制沉淀：针对多方协同的项目，需要把需求对齐、上线跟踪和效果复盘沉淀为常规节奏，减少沟通成本。\n4. 业务经验文档化：把组货策略迭代、缩铺执行和分析排查的经验整理成更清晰的操作指引，方便团队后续复用。`;

  await hpmPage.evaluate(({ fupan, jihui }) => {
    const textareas = Array.from(document.querySelectorAll("#pane-selfEvaluation textarea, form textarea"));
    if (textareas.length >= 2) {
      textareas[0].value = fupan;
      textareas[0].dispatchEvent(new Event("input", { bubbles: true }));
      textareas[0].dispatchEvent(new Event("change", { bubbles: true }));

      textareas[1].value = jihui;
      textareas[1].dispatchEvent(new Event("input", { bubbles: true }));
      textareas[1].dispatchEvent(new Event("change", { bubbles: true }));
    }
  }, { fupan: textFupan, jihui: textJihui });

  console.log("员工自我评价录入完毕。");

  // 4. 保存草稿（严禁点击提交）
  const saveBtn = hpmPage.locator("role=button[name=\"保存\"i]");
  await saveBtn.click();
  await hpmPage.waitForTimeout(2000);

  const msgs = await hpmPage.evaluate(() => {
    const list = Array.from(document.querySelectorAll(".el-message, .el-notification"));
    return list.map(m => m.innerText.trim()).filter(Boolean);
  });
  console.log("保存结果反馈:", msgs);
}

await syncHpmReview();
