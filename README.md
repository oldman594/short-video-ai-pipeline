# Short Video AI Pipeline

一个面向短视频内容再创作的自动化工作流项目。

目标不是搬运爆款视频，而是分析高流量视频的选题、结构、节奏和表达方式，生成同领域、同节奏、但内容原创的新脚本，并辅助完成数字人视频制作。

## 当前文档

- [产品 PRD](docs/PRD.md)
- [技术架构](docs/TECH_ARCHITECTURE.md)
- [Agent 规则](AGENTS.md)
- [MVP RFD](docs/rfd/0001-stdlib-mvp.md)

## 本地运行

当前 MVP 使用 Python 标准库实现，不需要安装第三方依赖。

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

直接验证某个本地视频的文本提取：

```bash
python3 scripts/extract_text_local.py vision/61354d2054ca8878ffe02059f360e7fe.mp4 --mode auto
```

## MVP 已实现

- 创建链接导入项目。
- 链接项目可以同时附带本地保存的视频文件，文本提取由服务端完成。
- 上传本地视频或音频文件并保存到 `data/uploads/`。
- 按情况选择文本提取路径：自动判断、字幕轨、语音识别、画面文字 OCR、网络字幕。
- 后台异步生成模拟转写、结构分析和 3 个原创脚本版本。
- 在审核台编辑转写文本和脚本。
- 批准一个脚本版本。
- 批准后生成 mock 数字人草稿文件并可下载。
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
- LLM 和数字人渲染是 mock provider，不调用真实第三方服务。
- 链接导入默认只记录链接，不下载外部平台视频；如果要从抖音等平台内容提取文本，请先在客户端合法保存视频，再作为本地文件附带上传给服务端。
- 网络字幕抓取需要显式设置 `ALLOW_NETWORK_MEDIA_FETCH=1`，且 MVP 不抓取抖音链接。
- 上传文件使用浏览器 base64 JSON 上传，适合 MVP 验证，不适合大文件生产使用。
- 渲染输出当前是文本草稿文件，不是 MP4。

## 文本提取策略

创建项目时可以选择：

- `自动判断`：链接先尝试网络字幕，本地上传先尝试字幕轨，失败后回退语音识别。
- `有字幕轨`：优先读取同名 `.srt` / `.vtt` / `.ass` 文件，其次尝试 FFmpeg 内嵌字幕轨。
- `只有说话声音`：优先使用 Whisper CLI，后续可替换为云语音识别。
- `文字在画面上`：预留 FFmpeg 抽帧 + Tesseract OCR，后续可接 PaddleOCR 或 VideoSubFinder。
- `网络视频`：预留 yt-dlp 字幕提取，默认关闭网络抓取并保留合规提示。

服务端工具状态可以在页面左侧查看，也可以请求：

```text
GET /api/system/text-extraction-tools
```

安装常见本地工具：

```bash
bash scripts/install_text_tools.sh
```

语音识别路径会在服务端执行：

```text
视频 -> 提取音频 -> 降噪 -> VAD -> 切片 -> ASR -> 时间戳对齐 -> 标点恢复 -> SRT 字幕文件
```
