---
name: web-video-presentation-delivery
description: "Delivers text-to-video work in this repo through one predictable path: script to storyboard, MiMo TTS assets, HTML player, and OBS-ready manual recording. Use when the user provides text, outline, article, or voiceover material and wants a web-video-presentation style video in this project."
disable-model-invocation: true
---

# Web Video Presentation Delivery

单一路径：文本 → 脚本 → TTS → HTML 播放器 → OBS 录制。

---

## 触发条件

使用此技能当工作包含：
- 将文本/大纲/文章转为浏览器视频演示
- 复用现有 chapter HTML + player + MiMo TTS 流程
- 准备 OBS 录制（而非发明新录制机制）

---

## 工作流程

### 1. 单一路径约束

**稳定架构**：
- 一个播放器：`tutorial_video_presentation_player.html`
- 一个录制视图：`?auto=1&obs=1`
- 一个启动方式：浏览器 `Space` 键
- 一个录制工具：OBS

见 `references/PITFALLS.md` 了解已废弃方案。

### 2. 脚本资产

**源文件**：
- `docs/scripts/tutorial_script.md`
- `docs/scripts/voiceover_tts_script.md`
- `docs/scripts/audio_storyboard.md`

**构建工具**：
- `scripts/build_storyboard_json.py`
- `scripts/rewrite_storyboard_v3.py`

**处理新文本**：
1. 对齐到章节/步骤结构
2. 更新 markdown 源（单一真身）
3. 重建 storyboard JSON

### 3. TTS 生成

**现有脚本**：
- 章节原型：`scripts/mimo_tts_ch1.py`
- 步骤克隆：`scripts/mimo_tts_step_clone.py`

**约定**（除非明确更改）：
- 克隆风格：对话式
- 输出目录：`audio/mimo_*`
- 播放器直接读取这些路径

### 4. HTML 编辑

**目标文件**：
- `tutorial_video_presentation_ch1.html` ... `ch7.html`
- `tutorial_video_presentation_player.html`

**播放器模型**：
- 同章节步骤切换：`postMessage`
- 跨章节切换：iframe reload
- `obs=1` 隐藏非必要 UI
- 手动 Space 启动

### 5. 验证顺序

**必须按顺序**：
1. 浏览器播放正常
2. 音频播放正常
3. 步骤切换和章节转换同步
4. `obs=1` 视图正确
5. **然后**才进入 OBS 调试

浏览器播放失败时，不要跳到 OBS。

### 6. OBS 录制

**标准流程**：
1. 启动 HTTP 服务（见 `references/COMMANDS.md`）
2. 打开 `http://127.0.0.1:8787/tutorial_video_presentation_player.html?auto=1&obs=1&session=<timestamp>`
3. 确认 OBS 预览
4. 开始 OBS 录制
5. 浏览器按 Space
6. 验证输出文件有音频

见 `references/TROUBLESHOOTING.md` 处理录制问题。

### 7. 文档更新

**如果工作改变了稳定路径**，更新：
- `docs/video-recording-runbook.md`
- `docs/video-recording-retrospective.md`
- `video_presentation/README.md`
- `.agents/README.md`（如技能接口变化）

---

## 完成标准

- [ ] 文件路径已更新
- [ ] 浏览器播放测试通过
- [ ] OBS 录制路径已验证（或说明录制限制）
- [ ] 文档已更新（如有架构变化）

---

## 引用

- `references/COMMANDS.md` — 稳定命令和配置
- `references/PITFALLS.md` — 已知陷阱和禁区
- `references/TROUBLESHOOTING.md` — 常见问题解决
