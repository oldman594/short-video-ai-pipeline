# 技术架构

## 1. 架构目标

系统采用任务驱动架构，把视频导入、音频提取、ASR、内容分析、脚本生成、视频渲染和发布辅助拆成独立阶段。

目标：

- 每个阶段可重试。
- 第三方服务可替换。
- 长耗时任务异步执行。
- 保留人工审核点。
- 支持后续扩展到多平台、多账号、多工作流。

## 2. 推荐技术栈

### 2.1 前端

- Next.js 或 React
- TypeScript
- Tailwind CSS
- Zustand 或 TanStack Query

主要页面：

- 项目列表
- 新建项目
- 项目详情
- ASR 文本编辑
- 内容分析结果
- 脚本审核台
- 视频生成任务
- 发布辅助页

### 2.2 后端

- Python FastAPI
- Pydantic
- SQLAlchemy
- Celery
- Redis
- PostgreSQL

选择 Python 的原因：

- FFmpeg、Whisper、AI 服务 SDK 和媒体处理生态成熟。
- 后台任务和模型调用实现成本低。

### 2.3 文件存储

开发阶段：

- 本地文件系统

生产阶段：

- S3、MinIO、阿里云 OSS 或腾讯云 COS

存储内容：

- 原始视频
- 提取音频
- 字幕文件
- 数字人成片
- 封面图片

### 2.4 AI 与媒体服务

ASR：

- Whisper
- 火山引擎语音识别
- 阿里云智能语音交互

LLM：

- OpenAI API
- 通义千问
- DeepSeek
- 火山方舟

数字人：

- HeyGen
- D-ID
- 硅基智能
- 腾讯智影

视频处理：

- FFmpeg

## 3. 系统模块

### 3.1 Web App

负责用户交互：

- 创建项目
- 上传文件或粘贴链接
- 查看任务状态
- 编辑转写文本
- 审核脚本
- 发起视频生成
- 下载成片

### 3.2 API Server

负责业务 API：

- 用户与项目管理
- 任务创建
- 文件上传
- 任务状态查询
- 审核结果保存
- 视频生成请求

API Server 不直接执行长耗时任务，只把任务写入队列。

### 3.3 Worker

负责异步任务：

- 下载或读取视频
- 路由文本提取策略
- 读取字幕轨、调用 ASR、调用 OCR 或读取网络字幕
- 调用 LLM 分析内容
- 调用 LLM 生成脚本
- 调用数字人服务
- 写入任务结果

### 3.3.1 Text Extraction Router

文本提取是内容生产的上游核心能力，按视频情况路由到不同方案：

- 有字幕轨：优先读取同名字幕文件，再用 FFmpeg / MKVToolNix 提取内嵌字幕轨。
- 只有说话声音：用 Whisper 或云语音识别。
- 文字在画面上：用 FFmpeg 抽帧后优先交给 RapidOCR，未安装时回退 Tesseract；后续仍可接 PaddleOCR 或 VideoSubFinder。
- 网络视频：先尝试授权范围内的字幕提取，再回退语音识别。

MVP 实现 `auto`、`subtitle_track`、`speech`、`screen_text`、`network_captions` 五种偏好。`auto` 内部可以运行多个候选提取器，但对外只返回质量最高的一个结果。缺少本地工具时不阻断项目，而是记录 warnings 并生成可编辑的回退文本。

### 3.4 Prompt Engine

负责管理提示词模板：

- 内容分析 Prompt
- 原创脚本生成 Prompt
- 标题生成 Prompt
- 封面文案 Prompt
- 风险检查 Prompt

建议把 Prompt 模板版本化，便于对比效果。

### 3.5 Provider Adapter

对第三方服务做适配层：

- ASRProvider
- LLMProvider
- AvatarVideoProvider
- StorageProvider
- PublishProvider

每个 Provider 只暴露统一接口，业务逻辑不直接绑定某一家供应商。

## 4. 工作流

### 4.1 导入与转写

```text
User
  -> Web App
  -> API Server
  -> Create Project
  -> Queue ingest_video
  -> Worker
  -> Store source video
  -> Extract audio with FFmpeg
  -> ASR Provider
  -> Save Transcript
```

### 4.2 分析与脚本生成

```text
Transcript
  -> Worker
  -> LLM content analysis
  -> Save Analysis
  -> LLM script generation
  -> Save Script versions
  -> User review
```

### 4.3 数字人成片

```text
Approved Script
  -> API Server
  -> Queue render_video
  -> Worker
  -> AvatarVideoProvider
  -> Poll render status
  -> Save output video
  -> User download
```

## 5. 数据库设计草案

### 5.1 projects

```sql
CREATE TABLE projects (
  id UUID PRIMARY KEY,
  user_id UUID NOT NULL,
  source_type TEXT NOT NULL,
  source_url TEXT,
  source_file_id UUID,
  platform TEXT,
  title TEXT,
  extraction_preference TEXT NOT NULL,
  status TEXT NOT NULL,
  created_at TIMESTAMP NOT NULL,
  updated_at TIMESTAMP NOT NULL
);
```

### 5.2 transcripts

```sql
CREATE TABLE transcripts (
  id UUID PRIMARY KEY,
  project_id UUID NOT NULL REFERENCES projects(id),
  raw_text TEXT NOT NULL,
  segments JSONB NOT NULL,
  language TEXT,
  asr_provider TEXT,
  extraction_method TEXT NOT NULL,
  warnings JSONB NOT NULL,
  created_at TIMESTAMP NOT NULL
);
```

### 5.3 analyses

```sql
CREATE TABLE analyses (
  id UUID PRIMARY KEY,
  project_id UUID NOT NULL REFERENCES projects(id),
  topic TEXT,
  audience TEXT,
  structure JSONB NOT NULL,
  hooks JSONB NOT NULL,
  key_points JSONB NOT NULL,
  risks JSONB NOT NULL,
  created_at TIMESTAMP NOT NULL
);
```

### 5.4 scripts

```sql
CREATE TABLE scripts (
  id UUID PRIMARY KEY,
  project_id UUID NOT NULL REFERENCES projects(id),
  version INTEGER NOT NULL,
  script_text TEXT NOT NULL,
  storyboard JSONB NOT NULL,
  title_options JSONB NOT NULL,
  cover_text_options JSONB NOT NULL,
  tags JSONB NOT NULL,
  status TEXT NOT NULL,
  created_at TIMESTAMP NOT NULL
);
```

### 5.5 render_jobs

```sql
CREATE TABLE render_jobs (
  id UUID PRIMARY KEY,
  project_id UUID NOT NULL REFERENCES projects(id),
  script_id UUID NOT NULL REFERENCES scripts(id),
  provider TEXT NOT NULL,
  avatar_id TEXT,
  voice_id TEXT,
  status TEXT NOT NULL,
  output_video_url TEXT,
  error_message TEXT,
  created_at TIMESTAMP NOT NULL,
  updated_at TIMESTAMP NOT NULL
);
```

## 6. API 草案

### 6.1 Projects

```http
POST /api/projects
GET /api/projects
GET /api/projects/{project_id}
DELETE /api/projects/{project_id}
```

### 6.2 Upload

```http
POST /api/uploads/video
```

### 6.3 Transcript

```http
GET /api/projects/{project_id}/transcript
PATCH /api/projects/{project_id}/transcript
```

### 6.4 Analysis

```http
POST /api/projects/{project_id}/analysis
GET /api/projects/{project_id}/analysis
```

### 6.5 Scripts

```http
POST /api/projects/{project_id}/scripts/generate
GET /api/projects/{project_id}/scripts
PATCH /api/scripts/{script_id}
POST /api/scripts/{script_id}/approve
```

### 6.6 Render

```http
POST /api/scripts/{script_id}/render
GET /api/render-jobs/{render_job_id}
```

## 7. 后台任务设计

任务队列：

- ingest_video
- extract_audio
- transcribe_audio
- analyze_content
- generate_scripts
- render_avatar_video
- sync_render_status

任务状态：

- pending
- running
- succeeded
- failed
- canceled

失败策略：

- 可重试任务最多重试 3 次。
- 第三方服务错误保留错误码和响应摘要。
- 用户可以在前端手动重试。

## 8. Prompt 输出约束

LLM 输出尽量使用 JSON schema，避免自由文本难以解析。

内容分析输出示例：

```json
{
  "topic": "职场沟通",
  "audience": "刚入职的年轻人",
  "hook": "一句话指出常见误区",
  "structure": [
    {"step": "hook", "summary": "提出痛点"},
    {"step": "example", "summary": "给出反面案例"},
    {"step": "solution", "summary": "给出表达模板"}
  ],
  "risks": ["不要复用原文金句", "需要替换案例"]
}
```

## 9. 合规与风控

需要内置风险检查：

- 文案相似度检查。
- 原作者姓名、口头禅和独特表达检查。
- 声音克隆风险检查。
- 平台敏感词检查。
- 医疗、金融、法律等高风险领域提示。

建议默认策略：

- 生成内容必须经过用户确认。
- 原文只作为分析输入，不直接作为发布内容。
- 输出内容需要包含“原创改写说明”和“风险提示”。

## 10. MVP 里程碑

### Milestone 1: 文档和基础项目

- PRD
- 技术架构
- 前后端项目骨架
- 数据库模型草案

### Milestone 2: 导入与转写

- 视频上传
- 链接导入占位
- FFmpeg 音频提取
- ASR 接入

### Milestone 3: 分析与脚本

- 内容分析 Prompt
- 脚本生成 Prompt
- 审核台
- 多版本脚本

### Milestone 4: 视频生成

- TTS 或数字人服务接入
- 字幕生成
- 视频导出

### Milestone 5: 发布辅助

- 标题、封面文案、标签生成
- 发布状态记录
- 数据回填预留接口
