from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass
from pathlib import Path
from textwrap import dedent
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class SourceInput:
    source_type: str
    title: str
    platform: str
    source_url: str | None
    source_file_path: str | None
    notes: str


class MockASRProvider:
    name = "mock-asr-v1"

    def transcribe(self, source: SourceInput) -> dict:
        subject = source.title or "参考视频"
        if source.source_type == "upload" and source.source_file_path:
            filename = Path(source.source_file_path).name
            raw_text = (
                f"这是对上传视频 {filename} 的模拟转写。"
                f"视频主题暂定为 {subject}。"
                "开头先指出一个常见痛点，中段用案例解释为什么这个问题反复出现，"
                "最后给出三个可以立即执行的方法，并提醒观众收藏和复盘。"
            )
        else:
            raw_text = (
                f"这是对链接 {source.source_url or '未填写链接'} 的模拟转写。"
                f"视频主题暂定为 {subject}。"
                "内容先用一句反常识观点吸引注意，再拆解错误做法，"
                "然后给出更稳妥的行动步骤，结尾用问题引导评论。"
            )

        if source.notes:
            raw_text += f" 用户补充背景：{source.notes}"

        return {
            "raw_text": raw_text,
            "segments": [
                {"start": 0.0, "end": 5.0, "text": raw_text[:40]},
                {"start": 5.0, "end": 15.0, "text": raw_text[40:100]},
                {"start": 15.0, "end": 30.0, "text": raw_text[100:]},
            ],
            "language": "zh",
            "provider": self.name,
        }


class MockLLMProvider:
    name = "mock-llm-v1"

    def analyze(self, transcript: str, title: str, platform: str) -> dict:
        topic = title or self._derive_topic(transcript)
        return {
            "topic": topic,
            "audience": "希望快速理解并应用该主题的短视频观众",
            "category": "知识口播",
            "hook": "用一个反常识判断或高频痛点开场，压缩进入主题的时间。",
            "structure": [
                {"step": "hook", "summary": "开场指出观众正在犯的错误。"},
                {"step": "problem", "summary": "解释问题为什么会反复出现。"},
                {"step": "framework", "summary": "给出 3 个可执行步骤。"},
                {"step": "close", "summary": "用复盘问题引导收藏、评论或转发。"},
            ],
            "key_points": [
                "开头不要铺垫背景，先给判断。",
                "中段用具体场景承接观点。",
                "结尾要给观众一个可以马上执行的动作。",
            ],
            "risks": [
                "不要逐句复用原视频文案。",
                "不要复用原作者独特口头禅或身份表达。",
                "发布前需要人工确认事实、案例和平台敏感表达。",
            ],
            "provider": self.name,
        }

    def generate_scripts(self, transcript: str, analysis: dict, title: str) -> list[dict]:
        topic = analysis.get("topic") or title or "这个主题"
        hooks = [
            f"很多人做{topic}，一开始就把顺序搞反了。",
            f"如果你也在研究{topic}，先别急着照搬别人的做法。",
            f"真正影响{topic}效果的，往往不是技巧数量，而是判断顺序。",
        ]
        scripts = []
        for index, hook in enumerate(hooks, start=1):
            script_text = dedent(
                f"""
                {hook}

                第一，先确认你的目标观众现在最困惑的点是什么。不要一上来讲完整理论，先把一个具体场景说清楚。

                第二，把参考内容里的结构拆出来，但案例和表达要重新组织。你可以保留“痛点、原因、方法、行动”的节奏，但不要保留原文句子。

                第三，结尾给一个明确动作：让观众保存这条内容，或者在评论区写下自己的场景。这样内容既有信息量，也有互动入口。

                这版脚本适合做 45 到 60 秒口播，语气直接，重点放在可执行方法上。
                """
            ).strip()
            scripts.append(
                {
                    "version": index,
                    "script_text": script_text,
                    "storyboard": [
                        {"scene": 1, "visual": "数字人正面口播，字幕强调开场判断。"},
                        {"scene": 2, "visual": "左侧列出痛点，右侧显示三个步骤。"},
                        {"scene": 3, "visual": "结尾展示行动提示和封面关键词。"},
                    ],
                    "title_options": [
                        f"{topic}别急着照搬，先拆这 3 步",
                        f"把{topic}讲清楚的一个简单框架",
                        f"做{topic}前先看这个判断顺序",
                    ],
                    "cover_text_options": [
                        "先拆结构",
                        "别直接照搬",
                        "3 步改成原创",
                    ],
                    "tags": ["短视频脚本", "内容创作", "原创改写", "数字人口播"],
                }
            )
        return scripts

    @staticmethod
    def _derive_topic(transcript: str) -> str:
        compact = transcript.strip().replace("\n", "")
        return compact[:16] or "参考视频"


class DeepSeekProviderError(RuntimeError):
    pass


class DeepSeekAnalysisProvider:
    name = "deepseek-analysis-v1"

    def __init__(
        self,
        api_key: str,
        model: str | None = None,
        base_url: str | None = None,
        timeout_seconds: int = 60,
        script_provider: MockLLMProvider | None = None,
    ):
        self.api_key = api_key
        self.model = model or os.environ.get("DEEPSEEK_MODEL") or "deepseek-v4-flash"
        self.base_url = (base_url or os.environ.get("DEEPSEEK_BASE_URL") or "https://api.deepseek.com").rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.script_provider = script_provider or MockLLMProvider()

    def analyze(self, transcript: str, title: str, platform: str) -> dict:
        payload = self._chat_completion_payload(transcript, title, platform)
        response = self._post_chat_completion(payload)
        content = extract_chat_message_content(response)
        analysis = parse_json_object(content)
        return normalize_analysis(analysis, title, transcript, self.name)

    def generate_scripts(self, transcript: str, analysis: dict, title: str) -> list[dict]:
        return self.script_provider.generate_scripts(transcript, analysis, title)

    def _chat_completion_payload(self, transcript: str, title: str, platform: str) -> dict:
        system_prompt = dedent(
            """
            你是短视频内容结构分析师。请只输出 json 对象，不要输出 markdown。
            目标是分析参考视频的选题、受众、开场钩子、叙事结构、可迁移要点和风险。
            不能逐句复刻原文，不能建议克隆原作者身份、声音、脸或独特口头禅。

            json schema:
            {
              "topic": "主题",
              "audience": "目标受众",
              "category": "内容类型",
              "hook": "开场钩子总结",
              "structure": [{"step": "hook", "summary": "这一段承担的作用"}],
              "key_points": ["可迁移的原创表达要点"],
              "risks": ["合规、事实或相似度风险"]
            }
            """
        ).strip()
        user_prompt = dedent(
            f"""
            请基于下面信息输出 json 结构分析。

            标题：{title or "未填写"}
            平台：{platform or "unknown"}
            转写文本：
            {transcript[:6000]}
            """
        ).strip()
        return {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "response_format": {"type": "json_object"},
            "thinking": {"type": "disabled"},
            "temperature": 0.2,
            "max_tokens": 1800,
        }

    def _post_chat_completion(self, payload: dict) -> dict:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = Request(
            f"{self.base_url}/chat/completions",
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")[:500]
            raise DeepSeekProviderError(f"DeepSeek API returned HTTP {exc.code}: {detail}") from exc
        except URLError as exc:
            raise DeepSeekProviderError(f"DeepSeek API request failed: {exc.reason}") from exc
        except json.JSONDecodeError as exc:
            raise DeepSeekProviderError("DeepSeek API returned invalid JSON response.") from exc


def default_llm_provider() -> MockLLMProvider | DeepSeekAnalysisProvider:
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if api_key:
        return DeepSeekAnalysisProvider(api_key=api_key)
    return MockLLMProvider()


def extract_chat_message_content(response: dict) -> str:
    try:
        content = response["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise DeepSeekProviderError("DeepSeek API response did not include message content.") from exc
    if not isinstance(content, str) or not content.strip():
        raise DeepSeekProviderError("DeepSeek API returned empty analysis content.")
    return content


def parse_json_object(content: str) -> dict:
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        raise DeepSeekProviderError("DeepSeek analysis content was not valid JSON.") from exc
    if not isinstance(parsed, dict):
        raise DeepSeekProviderError("DeepSeek analysis JSON must be an object.")
    return parsed


def normalize_analysis(analysis: dict, title: str, transcript: str, provider: str) -> dict:
    fallback = MockLLMProvider().analyze(transcript, title, "unknown")
    structure = normalize_structure_list(analysis.get("structure"))
    key_points = normalize_string_list(analysis.get("key_points"))
    risks = normalize_string_list(analysis.get("risks"))
    return {
        "topic": clean_string(analysis.get("topic")) or fallback["topic"],
        "audience": clean_string(analysis.get("audience")) or fallback["audience"],
        "category": clean_string(analysis.get("category")) or fallback["category"],
        "hook": clean_string(analysis.get("hook")) or fallback["hook"],
        "structure": structure or fallback["structure"],
        "key_points": key_points or fallback["key_points"],
        "risks": risks or fallback["risks"],
        "provider": provider,
    }


def normalize_structure_list(value: object) -> list[dict]:
    if not isinstance(value, list):
        return []
    normalized = []
    for item in value:
        if isinstance(item, dict):
            step = clean_string(item.get("step")) or f"step-{len(normalized) + 1}"
            summary = clean_string(item.get("summary"))
        else:
            step = f"step-{len(normalized) + 1}"
            summary = clean_string(item)
        if summary:
            normalized.append({"step": step, "summary": summary})
    return normalized[:8]


def normalize_string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    items = [clean_string(item) for item in value]
    return [item for item in items if item][:10]


def clean_string(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.split()).strip()


class MockAvatarVideoProvider:
    name = "mock-avatar-video-v1"

    def render(self, output_dir: Path, script_id: str, script_text: str, title_options: list[str]) -> dict:
        output_dir.mkdir(parents=True, exist_ok=True)
        filename = f"render-{script_id}.txt"
        output_path = output_dir / filename
        title = title_options[0] if title_options else "短视频草稿"
        output_path.write_text(
            dedent(
                f"""
                Mock digital human video draft
                Provider: {self.name}
                Title: {title}

                Script:
                {script_text}

                Production note:
                This file is a placeholder render artifact. Replace MockAvatarVideoProvider
                with a real avatar video provider to generate an MP4.
                """
            ).strip()
            + "\n",
            encoding="utf-8",
        )
        return {
            "provider": self.name,
            "output_filename": filename,
            "output_video_url": f"/outputs/{filename}",
        }


class AvatarVideoProviderError(RuntimeError):
    pass


class ExternalHttpAvatarVideoProvider:
    name = "external-http-avatar-video-dev"

    def __init__(
        self,
        endpoint: str,
        api_key: str | None = None,
        timeout_seconds: int = 300,
    ):
        self.endpoint = endpoint
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds

    def render(self, output_dir: Path, script_id: str, script_text: str, title_options: list[str]) -> dict:
        title = title_options[0] if title_options else "短视频草稿"
        payload = {
            "script_id": script_id,
            "script_text": script_text,
            "title": title,
            "title_options": title_options,
            "output_format": "mp4",
            "provider_contract": "short-video-ai-pipeline.avatar.render.v1",
            "development_status": "in_development",
        }
        response = self._post_render(payload)
        return self._normalize_render_response(response, output_dir, script_id)

    def _post_render(self, payload: dict) -> dict:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = Request(self.endpoint, data=body, method="POST", headers=headers)
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")[:500]
            raise AvatarVideoProviderError(f"Avatar video service returned HTTP {exc.code}: {detail}") from exc
        except URLError as exc:
            raise AvatarVideoProviderError(f"Avatar video service request failed: {exc.reason}") from exc
        except json.JSONDecodeError as exc:
            raise AvatarVideoProviderError("Avatar video service returned invalid JSON response.") from exc

    def _normalize_render_response(self, response: dict, output_dir: Path, script_id: str) -> dict:
        if not isinstance(response, dict):
            raise AvatarVideoProviderError("Avatar video service response must be a JSON object.")
        output_url = clean_string(
            response.get("output_video_url")
            or response.get("output_url")
            or response.get("video_url")
        )
        if output_url:
            return {"provider": self.name, "output_video_url": output_url}

        output_base64 = response.get("output_base64") or response.get("video_base64")
        if isinstance(output_base64, str) and output_base64.strip():
            filename = safe_output_video_filename(
                clean_string(response.get("filename")) or f"render-{script_id}.mp4",
                script_id,
            )
            output_dir.mkdir(parents=True, exist_ok=True)
            output_path = output_dir / filename
            try:
                output_path.write_bytes(base64.b64decode(strip_data_url_prefix(output_base64), validate=True))
            except ValueError as exc:
                raise AvatarVideoProviderError("Avatar video service returned invalid base64 video data.") from exc
            return {
                "provider": self.name,
                "output_filename": filename,
                "output_video_url": f"/outputs/{filename}",
            }

        raise AvatarVideoProviderError("Avatar video service response did not include output_video_url or output_base64.")


def default_avatar_video_provider() -> MockAvatarVideoProvider | ExternalHttpAvatarVideoProvider:
    provider = os.environ.get("AVATAR_VIDEO_PROVIDER", "mock").strip().lower()
    if provider in {"external-http", "http"}:
        endpoint = os.environ.get("AVATAR_VIDEO_ENDPOINT")
        if not endpoint:
            raise AvatarVideoProviderError("AVATAR_VIDEO_ENDPOINT is required when AVATAR_VIDEO_PROVIDER=external-http.")
        timeout = int(os.environ.get("AVATAR_VIDEO_TIMEOUT_SECONDS", "300"))
        return ExternalHttpAvatarVideoProvider(
            endpoint=endpoint,
            api_key=os.environ.get("AVATAR_VIDEO_API_KEY"),
            timeout_seconds=timeout,
        )
    return MockAvatarVideoProvider()


def safe_output_video_filename(filename: str, script_id: str) -> str:
    cleaned = "".join(char if char.isalnum() or char in "._-" else "-" for char in filename).strip(".-")
    if not cleaned:
        cleaned = f"render-{script_id}.mp4"
    suffix = Path(cleaned).suffix.lower()
    if suffix not in {".mp4", ".mov", ".webm", ".mkv"}:
        cleaned = f"{Path(cleaned).stem or f'render-{script_id}'}.mp4"
    return cleaned


def strip_data_url_prefix(value: str) -> str:
    return value.split(",", 1)[1] if "," in value and value.lstrip().startswith("data:") else value
