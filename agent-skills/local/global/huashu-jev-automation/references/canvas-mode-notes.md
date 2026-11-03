# 模式 C 实测要点（Canvas / Box，Jev 1.14）

企微 sheet canvas 实测记录（2026-10-27）。查阅时机：模式 C 首次接入或调参时。

- **截图尺寸**：原尺寸 2560×1267 被拒（`Invalid image dimensions`）；缩至宽 1280 后成功。上传前先 `sips --resampleWidth 1280 shot.png`。
- **版本解析**：`model: "jev-latest"` 实际解析为 `jev-1.14.0`。
- **一次 Noul+Box 返回示例**：`noul: 0.99`、`box { left: 0.02, right: 0.96, top: 0.11, bottom: 0.99 }`（confidence 0.62）。与"网格占画布大部分"吻合；坐标直接换算供 `act` x/y 点击。
- **计费**：图像按 input token，与文本同价（$0.042/Mtok，output 免费）。1280×633 一张 ≈ 2420 tokens ≈ $0.0001/次。同一图每被引用一次重复计费；共享图放 `state` 一次。
- **省 token 靠像素数**：压缩字节不省 token；长边 ≤ 1568、短边 ≥ 280 是有效区间。
- **格式限制**：仅收 PNG/JPEG；WebP/HEIC/GIF 被拒；JPEG 用标准 baseline。
