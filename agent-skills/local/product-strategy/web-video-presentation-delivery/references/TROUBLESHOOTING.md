# Troubleshooting

常见问题和解决方案。

---

## 浏览器播放问题

### 音频不播放

**症状**：点击 Space，视觉效果正常，但无声音

**诊断**：
```bash
# 1. 检查音频文件存在
ls -la audio/mimo_*.wav

# 2. 检查浏览器控制台
# 打开开发者工具 → Console
# 查找 404 或音频加载错误
```

**解决**：
- 确认 HTTP 服务运行在正确目录
- 检查音频文件路径拼写
- 验证 WAV 文件完整性：`file audio/mimo_step1.wav`

### 步骤切换卡顿

**症状**：章节内步骤切换延迟 >1 秒

**原因**：
- 音频文件过大（未压缩）
- 浏览器内存占用高

**解决**：
```bash
# 检查音频文件大小
du -h audio/*.wav

# 如果单个文件 >5MB，考虑压缩
# ffmpeg -i input.wav -ar 44100 -b:a 128k output.wav
```

### 章节跳转失败

**症状**：点击章节按钮，iframe 未加载

**诊断**：
- 浏览器控制台查看网络请求
- 确认章节 HTML 文件存在

**解决**：
```bash
# 验证章节文件
ls -la tutorial_video_presentation_ch*.html

# 检查 player 中的章节路径
grep -n "tutorial_video_presentation_ch" tutorial_video_presentation_player.html
```

---

## OBS 录制问题

### OBS 输出无声音

**症状**：浏览器有声音，OBS 预览有声音，但最终文件无声音

**常见原因**：OBS 音频源配置错误

**解决步骤**：
1. **检查音频源**：
   - OBS → 设置 → 音频
   - 确认"桌面音频"或"扬声器"已选择
   
2. **验证音频监听**：
   - 右键点击音频源（混音器中）
   - 音频高级属性 → 音频监听 → "监听和输出"
   
3. **测试录制**：
   ```bash
   # 录制 5 秒测试
   # OBS → 开始录制 → 播放音频 → 停止录制
   
   # 检查输出文件
   ffprobe ~/Movies/test.mp4 2>&1 | grep Audio
   ```

4. **如果仍无声**：
   - 确认浏览器音量未静音
   - 确认系统音量 >50%
   - 重启 OBS

### OBS 捕获黑屏

**症状**：OBS 预览显示黑屏

**解决**：
1. **浏览器源设置**：
   - OBS → 来源 → 添加 → 浏览器
   - URL: `http://127.0.0.1:8787/tutorial_video_presentation_player.html?auto=1&obs=1`
   - 宽度: 1920, 高度: 1080
   - ✓ 关闭源不活跃时的情况

2. **硬件加速**：
   - Chrome → 设置 → 高级 → 系统
   - 关闭"使用硬件加速"
   - 重启浏览器

3. **权限**：
   - macOS: 系统偏好设置 → 安全与隐私 → 屏幕录制
   - 确保 OBS 已授权

### OBS 帧率不稳定

**症状**：录制结果卡顿或掉帧

**解决**：
1. **降低输出分辨率**：1920x1080 → 1280x720
2. **检查 CPU 占用**：Activity Monitor → 确认 OBS < 80%
3. **使用硬件编码**：OBS → 设置 → 输出 → 编码器 → H264 (硬件)

---

## HTTP 服务问题

### 端口被占用

**症状**：`python3 -m http.server 8787` 报错 "Address already in use"

**解决**：
```bash
# 找到占用进程
lsof -i :8787

# 杀掉进程
kill -9 <PID>

# 或换个端口
python3 -m http.server 8788
# 更新 player URL
```

### 跨域错误

**症状**：控制台显示 CORS 错误

**原因**：使用了 `file://` 而非 `http://`

**解决**：
- 确保使用 `http://127.0.0.1:8787`
- 不要直接打开 HTML 文件

---

## 同步问题

### 音频与视觉不同步

**症状**：文字已切换，音频还在播放上一步

**原因**：
- 音频文件过长
- 步骤时长配置错误

**解决**：
```bash
# 检查音频时长
for f in audio/mimo_step*.wav; do
  echo "$f: $(ffprobe -v error -show_entries format=duration \
    -of default=noprint_wrappers=1:nokey=1 "$f") 秒"
done

# 对比 storyboard JSON 中的 duration_ms
```

### 自动播放意外跳过步骤

**症状**：`auto=1` 模式下跳过某些步骤

**原因**：音频文件缺失或加载失败

**解决**：
- 检查浏览器控制台 404 错误
- 验证所有音频文件存在且可访问

---

## 系统特定问题

### macOS: 浏览器无法播放音频

**症状**：Chrome 显示"用户未与文档交互"错误

**原因**：浏览器自动播放策略

**解决**：
- 使用手动 Space 启动（而非完全自动）
- 或 Chrome 设置 → 网站设置 → 声音 → 允许

### macOS: OBS 捕获系统混音

**当前状态**：正常行为

**说明**：
- OBS 捕获"扬声器/Global"时录制系统混音
- 意味着其他应用声音也会被录制
- **录制时需要**：
  1. 关闭音乐播放器
  2. 静音聊天工具
  3. 关闭通知声音

**未来改进**（如需要）：
- 安装 BlackHole 虚拟音频设备
- 配置浏览器输出到 BlackHole
- OBS 仅捕获 BlackHole
- 参考：https://github.com/ExistentialAudio/BlackHole

---

## 调试技巧

### 启用详细日志

在 player HTML 中：
```javascript
// 添加到 <script> 开头
const DEBUG = true;
function log(...args) {
  if (DEBUG) console.log('[Player]', ...args);
}
```

### 慢动作测试

测试同步问题时：
```javascript
// 在浏览器控制台
document.querySelectorAll('audio').forEach(a => a.playbackRate = 0.5);
```

### 验证 postMessage

```javascript
// 在 player 控制台
window.addEventListener('message', (e) => {
  console.log('Received message:', e.data);
});
```

---

## 快速诊断清单

录制前检查：
- [ ] HTTP 服务运行在 8787
- [ ] 浏览器能正常播放（Space 测试）
- [ ] OBS 预览显示内容
- [ ] OBS 混音器显示音频电平
- [ ] 系统其他音频源已静音
- [ ] 录制路径有足够磁盘空间

录制后验证：
- [ ] 文件大小 >0
- [ ] `ffprobe` 显示视频和音频流
- [ ] 播放前 10 秒确认音频同步
