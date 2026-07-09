# Short Video AI Pipeline

一个面向短视频内容再创作的自动化工作流项目。

目标不是搬运爆款视频，而是分析高流量视频的选题、结构、节奏和表达方式，生成同领域、同节奏、但内容原创的新脚本，并辅助完成数字人视频制作。

## 当前文档

- [产品 PRD](docs/PRD.md)
- [技术架构](docs/TECH_ARCHITECTURE.md)
- [Agent 规则](AGENTS.md)
- [MVP RFD](docs/rfd/0001-stdlib-mvp.md)

## 本地运行

当前 MVP 的核心服务使用 Python 标准库实现；本地 ASR/OCR 工具按需安装。

```bash
python3 -m app.main
```

然后打开：

```text
http://127.0.0.1:8000
```

运行测试：

```bash
python3 -m unittest discover -s tests
```

运行行覆盖率检查：

```bash
python3 scripts/check_line_coverage.py
```

启用 DeepSeek 做结构分析和原创脚本生成：

```bash
export DEEPSEEK_API_KEY="你的 DeepSeek API Key"
python3 -m app.main
```

可选配置：

```bash
export DEEPSEEK_MODEL="deepseek-v4-flash"
export DEEPSEEK_BASE_URL="https://api.deepseek.com"
```

直接验证某个本地视频的文本提取：

```bash
python3 scripts/extract_text_local.py vision/61354d2054ca8878ffe02059f360e7fe.mp4 --mode auto
```

如果要评估画面硬字幕识别效果，请使用 `screen_text`，不要使用 `speech`：

```bash
bash scripts/bootstrap_ocr_local.sh
python3 scripts/extract_text_local.py vision/61354d2054ca8878ffe02059f360e7fe.mp4 --mode screen_text --json
```

## MVP 已实现

- 创建链接导入项目。
- 链接项目可以同时附带本地保存的视频文件，文本提取由服务端完成。
- 上传本地视频或音频文件并保存到 `data/uploads/`。
- 按情况选择文本提取路径：自动判断、字幕轨、语音识别、画面文字 OCR、网络字幕。
- 后台异步提取文本、分析写作模式，并生成 3 个原创脚本版本。
- 在审核台编辑转写文本和脚本。
- 批准一个脚本版本。
- 批准后生成数字人渲染任务；默认 mock 草稿，也可接外部真实视频服务（开发中）。
- 展示标题、封面文案、简介和标签。

## MVP 范围

第一版建议做成半自动流程：

1. 用户导入短视频链接或上传视频文件。
2. 系统提取音频并转写文字。
3. AI 分析原视频的结构、爆点和表达节奏。
4. AI 生成原创脚本、标题、封面文案和标签。
5. 用户审核脚本。
6. 系统生成数字人口播视频草稿。
7. 用户确认后手动发布，或后续接入官方发布能力。

## 重要边界

- 不依赖爬虫、逆向接口或绕过平台限制的方式读取收藏夹。
- 不直接复刻原视频文案、画面和声音。
- 默认加入人工审核，避免侵权、虚假信息和平台违规。

## 当前限制

- 文本提取路由已经存在，但本机未安装 FFmpeg、Whisper、Tesseract、yt-dlp 等工具时会使用回退文本。
- 未配置 `DEEPSEEK_API_KEY` 时 LLM 使用 mock provider；配置后结构分析和脚本生成会优先调用 DeepSeek，失败时回退到本地 mock provider。
- 真实数字人视频服务处于开发中；未配置外部服务时仍使用 mock 草稿。
- 链接导入默认只记录链接，不下载外部平台视频；如果要从抖音等平台内容提取文本，请先在客户端合法保存视频，再作为本地文件附带上传给服务端。
- 网络字幕抓取需要显式设置 `ALLOW_NETWORK_MEDIA_FETCH=1`，且 MVP 不抓取抖音链接。
- 上传文件使用浏览器 base64 JSON 上传，适合 MVP 验证，不适合大文件生产使用。
- 渲染输出当前是文本草稿文件，不是 MP4。

## 文本提取策略

创建项目时可以选择：

- `自动判断`：本地上传先尝试字幕轨；如果没有独立字幕轨，会对语音识别和画面硬字幕 OCR 做质量仲裁，只返回一个最佳结果。
- `有字幕轨`：优先读取同名 `.srt` / `.vtt` / `.ass` 文件，其次尝试 FFmpeg 内嵌字幕轨。
- `只有说话声音`：使用 Whisper / whisper.cpp，后续可替换为云语音识别。
- `文字在画面上`：优先使用 FFmpeg 抽帧 + RapidOCR；未安装 RapidOCR 时回退 Tesseract OCR。
- `网络视频`：预留 yt-dlp 字幕提取，默认关闭网络抓取并保留合规提示。

服务端工具状态可以在页面左侧查看，也可以请求：

```text
GET /api/system/text-extraction-tools
```

安装常见本地工具：

```bash
bash scripts/install_text_tools.sh
```

安装本地硬字幕 OCR 增强环境：

```bash
bash scripts/bootstrap_ocr_local.sh
```

接入外部真实数字人视频服务（开发中）：

```bash
export AVATAR_VIDEO_PROVIDER="external-http"
export AVATAR_VIDEO_ENDPOINT="https://your-avatar-service.example/render"
export AVATAR_VIDEO_API_KEY="可选服务密钥"
python3 -m app.main
```

外部服务需要接收 JSON 请求并返回 `output_video_url`，或返回 `output_base64` 和可选 `filename`，本项目会保存到 `data/outputs/`。

直接接入 D-ID 数字人服务：

```bash
export AVATAR_VIDEO_PROVIDER="did"
export DID_API_KEY="你的 D-ID API Key"
export DID_SOURCE_URL="https://your-public-avatar-image.example/avatar.jpg"
python3 -m app.main
```

`DID_SOURCE_URL` 必须是 D-ID 可以访问的公开头像图片 URL。也可以把头像图片放到 `photo/` 目录，并用公开服务地址自动生成 source URL：

```bash
export AVATAR_VIDEO_PROVIDER="did"
export DID_API_KEY="你的 D-ID API Key"
export PUBLIC_BASE_URL="https://your-public-domain.example"
export DID_PHOTO_FILENAME="ScreenShot_2026-07-08_173136_011.png"
python3 -m app.main
```

项目会通过 `/photos/<filename>` 只读暴露 `photo/` 中的图片。`PUBLIC_BASE_URL` 必须是公网可访问地址；本机 `127.0.0.1` 不能被 D-ID 云端访问。本地调试可以用内网穿透工具或部署到公网服务器。

可选语音配置：

```bash
export DID_VOICE_ID="zh-CN-XiaoxiaoNeural"
export DID_VOICE_PROVIDER="microsoft"
```

不要把 `DID_API_KEY` 写入代码或提交到仓库。

语音识别路径会在服务端执行：

```text
视频 -> 提取音频 -> 降噪 -> VAD -> 切片 -> ASR -> 时间戳对齐 -> 标点恢复 -> SRT 字幕文件
```
