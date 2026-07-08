from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from textwrap import dedent


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
