from __future__ import annotations

import base64
import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from textwrap import dedent
from urllib.parse import quote
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.config import PHOTO_DIR


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
        lines = meaningful_transcript_lines(transcript)
        structure = derive_content_structure(lines, topic)
        return {
            "topic": topic,
            "audience": derive_content_audience(lines, topic),
            "category": derive_content_category(lines),
            "hook": derive_content_hook(lines, topic),
            "structure": structure,
            "key_points": derive_content_key_points(lines, structure),
            "risks": derive_content_risks(lines, topic),
            "provider": self.name,
        }

    def generate_scripts(self, transcript: str, analysis: dict, title: str) -> list[dict]:
        topic = analysis.get("topic") or title or "这个主题"
        writing_profile = derive_writing_profile(transcript, analysis)
        structure_line = " -> ".join(writing_profile["structure_steps"])
        rhythm_line = writing_profile["rhythm"]
        hooks = [
            f"很多人做{topic}，问题不是不会做，而是开头就站错了位置。",
            f"如果你也在研究{topic}，先别急着找技巧，先把判断顺序理清楚。",
            f"真正影响{topic}效果的，往往不是方法数量，而是你先讲什么、后讲什么。",
        ]
        angles = [
            "痛点拆解版",
            "反差判断版",
            "行动清单版",
        ]
        transitions = ["先看场景", "接着拆原因", "最后给动作"]
        scripts = []
        for index, hook in enumerate(hooks, start=1):
            script_text = dedent(
                f"""
                {hook}

                这版参考的不是原文句子，而是它的写作模式：{structure_line}。节奏上用{rhythm_line}，让观众不用等铺垫，先听到结论。

                {transitions[0]}：把观众正在遇到的具体问题说出来。不要讲一大段背景，直接指出一个他们会点头的瞬间。

                {transitions[1]}：把这个问题为什么反复出现讲清楚。这里换成我们自己的案例和表达，只保留“先判断、再解释、再给路径”的推进方式。

                {transitions[2]}：给三个可以马上执行的小步骤。第一步先定目标观众，第二步重写案例，第三步检查有没有复用原视频的句子、口头禅和身份表达。

                结尾回到一个明确动作：收藏这条内容，按这个顺序把自己的选题重写一遍。{angles[index - 1]}适合做 45 到 60 秒数字人口播。
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
                        f"{topic}别照搬，先拆写作模式",
                        f"把{topic}重写成原创稿的 3 步",
                        f"做{topic}前先看这个结构顺序",
                    ],
                    "cover_text_options": [
                        "先拆模式",
                        "原创重写",
                        "3 步出稿",
                    ],
                    "tags": ["短视频脚本", "内容创作", "原创改写", "数字人口播"],
                }
            )
        return scripts

    @staticmethod
    def _derive_topic(transcript: str) -> str:
        compact = " ".join(meaningful_transcript_lines(transcript)).replace(" ", "")
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
        writing_profile = derive_writing_profile(transcript, analysis)
        try:
            payload = self._script_generation_payload(transcript, analysis, title, writing_profile)
            response = self._post_chat_completion(payload)
            content = extract_chat_message_content(response)
            parsed = parse_json_object(content)
            scripts = normalize_scripts(parsed.get("scripts"), analysis, title, transcript, writing_profile)
            if scripts:
                return scripts
        except DeepSeekProviderError:
            pass
        return self.script_provider.generate_scripts(transcript, analysis, title)

    def _chat_completion_payload(self, transcript: str, title: str, platform: str) -> dict:
        system_prompt = dedent(
            """
            你是短视频内容结构分析师。请只输出 json 对象，不要输出 markdown。
            目标是分析参考视频的选题、受众、开场钩子、叙事结构、写作模式、可迁移要点和风险。
            每个字段都必须结合转写文本里的具体对象、概念、例子或原有段落功能。
            不要输出“观众正在犯的错误”“给出 3 个步骤”“引导收藏评论”等通用模板，除非转写文本确实这么表达。
            不能逐句复刻原文，不能建议克隆原作者身份、声音、脸或独特口头禅。

            json schema:
            {
              "topic": "主题",
              "audience": "目标受众",
              "category": "内容类型",
              "hook": "结合具体内容的开场钩子总结",
              "structure": [{"step": "内容段落名称", "summary": "这一段讲了什么具体内容以及承担的叙事作用"}],
              "key_points": ["结合具体内容的可迁移原创表达要点"],
              "risks": ["结合具体内容的合规、事实或相似度风险"]
            }
            """
        ).strip()
        user_prompt = dedent(
            f"""
            请基于下面信息输出 json 结构分析。
            输出要求：
            1. structure 至少 4 段；step 使用中文段落名，不要使用 hook/problem/framework/close 这种占位词。
            2. 每段 summary 必须包含转写文本里的具体词，例如人物、问题、概念、数字、类比或结论。
            3. key_points 必须描述这个视频实际可学习的表达方式，不能写空泛方法论。
            4. 如果转写有 OCR 错字，请根据上下文保守概括，不要编造视频外信息。

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

    def _script_generation_payload(self, transcript: str, analysis: dict, title: str, writing_profile: dict) -> dict:
        system_prompt = dedent(
            """
            你是短视频原创脚本策划。请只输出 json 对象，不要输出 markdown。
            任务是参考原视频的写作结构、节奏和段落功能，生成新的原创数字人口播脚本。
            严禁逐句改写、搬运原文金句、复用原作者独特身份表达、声音或口头禅。

            json schema:
            {
              "scripts": [
                {
                  "version": 1,
                  "script_text": "完整口播稿",
                  "storyboard": [{"scene": 1, "visual": "画面建议"}],
                  "title_options": ["标题"],
                  "cover_text_options": ["封面文案"],
                  "tags": ["标签"]
                }
              ]
            }
            """
        ).strip()
        user_prompt = dedent(
            f"""
            请生成 3 个原创视频稿版本，每版 45 到 60 秒。

            标题：{title or analysis.get("topic") or "未填写"}
            主题：{analysis.get("topic") or "未识别"}
            受众：{analysis.get("audience") or "短视频观众"}
            内容类型：{analysis.get("category") or "知识口播"}
            开场模式：{writing_profile["opening_pattern"]}
            叙事节奏：{writing_profile["rhythm"]}
            句式风格：{writing_profile["sentence_style"]}
            结构步骤：{" -> ".join(writing_profile["structure_steps"])}
            转场方式：{writing_profile["transition_style"]}
            结尾方式：{writing_profile["ending_pattern"]}
            合规要求：{"; ".join(writing_profile["avoid_copy_rules"])}

            参考转写文本只用于理解结构，不要复制其中句子：
            {transcript[:5000]}
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
            "temperature": 0.6,
            "max_tokens": 3600,
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


def meaningful_transcript_lines(transcript: str, limit: int = 80) -> list[str]:
    lines: list[str] = []
    for raw_line in transcript.splitlines():
        line = clean_string(raw_line)
        if not line:
            continue
        if is_low_value_analysis_line(line):
            continue
        lines.append(line)
    if lines:
        return dedupe_preserving_order(lines)[:limit]
    compact = clean_string(transcript)
    if not compact:
        return []
    return [compact[:40]]


def is_low_value_analysis_line(line: str) -> bool:
    compact = re.sub(r"\s+", "", line)
    if len(compact) <= 1:
        return True
    platform_markers = ("抖音号", "截图保存", "扫一扫", "搜索页", "发现更多创作者")
    return any(marker in compact for marker in platform_markers)


def derive_content_structure(lines: list[str], topic: str) -> list[dict]:
    if not lines:
        return [{"step": "内容概览", "summary": f"围绕{topic}展开，但当前转写文本太短，需要人工补充上下文。"}]
    marker_indexes = [
        index
        for index, line in enumerate(lines)
        if re.search(r"第[一二三四五六七八九十0-9]+个|第一|第二|第三", line)
    ]
    sections: list[tuple[str, list[str]]] = []
    if marker_indexes:
        if marker_indexes[0] > 0:
            sections.append(("开场设问", lines[: marker_indexes[0]]))
        for position, start in enumerate(marker_indexes):
            end = marker_indexes[position + 1] if position + 1 < len(marker_indexes) else len(lines)
            sections.append((strip_terminal_punctuation(lines[start]) or f"段落 {position + 1}", lines[start:end]))
    else:
        section_count = min(4, max(2, len(lines)))
        chunk_size = max(1, (len(lines) + section_count - 1) // section_count)
        names = ["开场信息", "核心展开", "论证推进", "结尾收束"]
        for index in range(section_count):
            chunk = lines[index * chunk_size : (index + 1) * chunk_size]
            if chunk:
                sections.append((names[min(index, len(names) - 1)], chunk))

    structure = []
    for name, chunk in sections[:6]:
        summary = summarize_content_lines(chunk)
        if summary:
            structure.append({"step": name[:20], "summary": summary})
    return structure or [{"step": "内容概览", "summary": summarize_content_lines(lines[:6])}]


def summarize_content_lines(lines: list[str]) -> str:
    selected = [strip_terminal_punctuation(line) for line in lines if clean_string(line)]
    selected = selected[:4]
    summary = "、".join(selected)
    return summary[:90] if summary else ""


def derive_content_hook(lines: list[str], topic: str) -> str:
    if not lines:
        return f"围绕{topic}开场，但当前转写文本不足，需要人工补充。"
    opening = "、".join(strip_terminal_punctuation(line) for line in lines[:4])
    return f"开头用“{opening[:60]}”把观众带入{topic}。"


def derive_content_audience(lines: list[str], topic: str) -> str:
    joined = "\n".join(lines)
    if any(term in joined for term in ("宇宙", "物理", "科学", "大爆炸", "碳原子")):
        return "对宇宙、科学与信仰关系感兴趣的泛科普观众"
    if any(term in joined for term in ("期末", "老师", "学习", "学术", "复习")):
        return "关注学习效率、课堂和复习场景的学生群体"
    if any(term in joined for term in ("职场", "沟通", "老板", "同事", "客户")):
        return "希望解决职场沟通和工作决策问题的观众"
    return f"已经关注{topic}、希望从短视频里快速获得观点和例子的观众"


def derive_content_category(lines: list[str]) -> str:
    joined = "\n".join(lines)
    if any(term in joined for term in ("宇宙", "物理", "科学", "大爆炸", "碳原子")):
        return "泛科普观点口播"
    if any(term in joined for term in ("第一个", "第二个", "第三个", "误解")):
        return "观点拆解口播"
    if any(term in joined for term in ("教程", "步骤", "方法", "清单")):
        return "方法论口播"
    return "知识观点口播"


def derive_content_key_points(lines: list[str], structure: list[dict]) -> list[str]:
    points: list[str] = []
    if lines:
        points.append(f"开场先抓住具体意象：{summarize_content_lines(lines[:3])}。")
    if any("误解" in item["step"] or "误解" in item["summary"] for item in structure):
        points.append("中段用“第一个误解、第二个误解、第三个误解”的连续拆解保持推进感。")
    if any(term in "\n".join(lines) for term in ("宇宙", "大爆炸", "碳原子", "扑克牌")):
        points.append("用宇宙、碳原子、扑克牌这类具象类比承接抽象观点，降低理解门槛。")
    if lines:
        points.append(f"结尾可学习它把讨论收回到观众自身选择：{summarize_content_lines(lines[-4:])}。")
    return points[:4] or ["先抽取原视频的具体意象和段落顺序，再重新组织为原创表达。"]


def derive_content_risks(lines: list[str], topic: str) -> list[str]:
    risks = [
        f"围绕{topic}再创作时不要复用原视频的连续句子和独特表达。",
        "OCR 文本可能有错字，发布前需要人工核对关键名词、数字和事实。",
    ]
    joined = "\n".join(lines)
    if any(term in joined for term in ("科学", "宇宙", "大爆炸", "杨振宁", "物理")):
        risks.append("涉及科学、人物或宇宙论观点时，需要核实表述，避免把观点包装成确定事实。")
    return risks


def dedupe_preserving_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def normalize_analysis(analysis: dict, title: str, transcript: str, provider: str) -> dict:
    fallback = MockLLMProvider().analyze(transcript, title, "unknown")
    structure = normalize_structure_list(analysis.get("structure"))
    key_points = normalize_string_list(analysis.get("key_points"))
    risks = normalize_string_list(analysis.get("risks"))
    hook = clean_string(analysis.get("hook"))
    grounded_key_points = [item for item in key_points if not is_generic_analysis_text(item)]
    return {
        "topic": clean_string(analysis.get("topic")) or fallback["topic"],
        "audience": clean_string(analysis.get("audience")) or fallback["audience"],
        "category": clean_string(analysis.get("category")) or fallback["category"],
        "hook": hook if hook and not is_generic_analysis_text(hook) else fallback["hook"],
        "structure": structure if structure and not is_generic_structure(structure) else fallback["structure"],
        "key_points": grounded_key_points or fallback["key_points"],
        "risks": risks or fallback["risks"],
        "provider": provider,
    }


def is_generic_structure(structure: list[dict]) -> bool:
    generic_steps = {"hook", "problem", "framework", "close", "opening", "solution"}
    generic_count = 0
    for item in structure:
        step = clean_string(item.get("step")).lower()
        summary = clean_string(item.get("summary"))
        if step in generic_steps or is_generic_analysis_text(summary):
            generic_count += 1
    return generic_count >= max(1, len(structure) // 2)


def is_generic_analysis_text(text: str) -> bool:
    compact = re.sub(r"\s+", "", text)
    if not compact:
        return True
    generic_markers = (
        "反常识开场",
        "高频痛点",
        "观众正在犯的错误",
        "为什么会反复出现",
        "3个可执行步骤",
        "三个可执行步骤",
        "引导收藏",
        "评论或转发",
        "保留结构",
        "不复用原句",
        "不要铺垫背景",
        "具体场景承接观点",
        "马上执行的动作",
    )
    return any(marker in compact for marker in generic_markers)


def derive_writing_profile(transcript: str, analysis: dict) -> dict:
    lines = [clean_string(line) for line in transcript.splitlines()]
    lines = [line for line in lines if line]
    structure = normalize_structure_list(analysis.get("structure"))
    structure_steps = [strip_terminal_punctuation(item["summary"]) for item in structure[:5]]
    if not structure_steps:
        structure_steps = ["先抛出痛点或反差判断", "用具体场景解释原因", "给出可执行步骤", "用互动动作收尾"]

    avg_line_length = sum(len(line) for line in lines) / max(len(lines), 1)
    has_numbered_steps = any(marker in transcript for marker in ["第一", "第二", "第三", "1.", "2.", "3."])
    has_question = "?" in transcript or "？" in transcript
    has_action_close = any(marker in transcript for marker in ["收藏", "评论", "转发", "关注", "试试", "复盘"])

    if avg_line_length <= 18:
        rhythm = "短句快节奏推进"
        sentence_style = "短句、直接判断、少铺垫"
    elif avg_line_length <= 36:
        rhythm = "中等长度句子承接观点和解释"
        sentence_style = "判断句搭配解释句"
    else:
        rhythm = "长句解释较多，需要压缩成口播短句"
        sentence_style = "先拆长句，再改成可听懂的短句"

    opening_pattern = clean_string(analysis.get("hook")) or "用一个痛点、反差或问题快速开场"
    if has_question:
        opening_pattern = f"{opening_pattern}，可加入提问式钩子"
    if has_numbered_steps:
        transition_style = "用编号步骤推进，让观众清楚记住顺序"
    else:
        transition_style = "用场景、原因、方法的转场推进"
    if has_action_close:
        ending_pattern = "结尾给收藏、评论或复盘动作"
    else:
        ending_pattern = "结尾补一个可立即执行的动作"

    return {
        "opening_pattern": opening_pattern,
        "rhythm": rhythm,
        "sentence_style": sentence_style,
        "structure_steps": structure_steps,
        "transition_style": transition_style,
        "ending_pattern": ending_pattern,
        "avoid_copy_rules": [
            "只学习结构和节奏，不复制原文句子",
            "替换案例、身份表达和口头禅",
            "输出前保留人工审核，确认事实和相似度风险",
        ],
    }


def normalize_scripts(
    value: object,
    analysis: dict,
    title: str,
    transcript: str,
    writing_profile: dict,
) -> list[dict]:
    if not isinstance(value, list):
        return []
    topic = clean_string(analysis.get("topic")) or title or MockLLMProvider._derive_topic(transcript)
    normalized = []
    for item in value:
        if not isinstance(item, dict):
            continue
        script_text = clean_multiline_text(item.get("script_text"))
        if not script_text:
            continue
        normalized.append(
            {
                "version": len(normalized) + 1,
                "script_text": script_text,
                "storyboard": normalize_storyboard_list(item.get("storyboard")),
                "title_options": normalize_string_list(item.get("title_options"))
                or [f"{topic}的原创表达框架"],
                "cover_text_options": normalize_string_list(item.get("cover_text_options"))
                or ["原创脚本", "结构拆解"],
                "tags": normalize_string_list(item.get("tags")) or ["短视频脚本", "原创改写"],
            }
        )
        if len(normalized) == 3:
            break
    if normalized:
        for script in normalized:
            if not script["storyboard"]:
                script["storyboard"] = [
                    {"scene": 1, "visual": f"数字人口播，字幕强调{writing_profile['opening_pattern'][:18]}"},
                    {"scene": 2, "visual": "屏幕列出结构步骤和原创案例。"},
                    {"scene": 3, "visual": "结尾展示互动动作和封面关键词。"},
                ]
    return normalized


def normalize_storyboard_list(value: object) -> list[dict]:
    if not isinstance(value, list):
        return []
    normalized = []
    for item in value:
        if isinstance(item, dict):
            visual = clean_string(item.get("visual"))
            scene = item.get("scene")
        else:
            visual = clean_string(item)
            scene = len(normalized) + 1
        if visual:
            normalized.append({"scene": scene if isinstance(scene, int) else len(normalized) + 1, "visual": visual})
    return normalized[:8]


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


def clean_multiline_text(value: object) -> str:
    if not isinstance(value, str):
        return ""
    lines = [clean_string(line) for line in value.splitlines()]
    compact_lines = [line for line in lines if line]
    return "\n".join(compact_lines).strip()


def strip_terminal_punctuation(value: str) -> str:
    return value.rstrip("。！？!?；;，,、 ")


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


def default_avatar_video_provider() -> MockAvatarVideoProvider | ExternalHttpAvatarVideoProvider | DIDAvatarVideoProvider:
    provider = os.environ.get("AVATAR_VIDEO_PROVIDER", "mock").strip().lower()
    if provider in {"did", "d-id"}:
        api_key = os.environ.get("DID_API_KEY")
        source_url = os.environ.get("DID_SOURCE_URL") or did_source_url_from_local_photo(
            os.environ.get("PUBLIC_BASE_URL") or os.environ.get("APP_PUBLIC_BASE_URL"),
            os.environ.get("DID_PHOTO_FILENAME"),
        )
        if not api_key:
            raise AvatarVideoProviderError("DID_API_KEY is required when AVATAR_VIDEO_PROVIDER=did.")
        if not source_url:
            raise AvatarVideoProviderError(
                "DID_SOURCE_URL is required when AVATAR_VIDEO_PROVIDER=did, "
                "or set PUBLIC_BASE_URL with a local photo/ image."
            )
        return DIDAvatarVideoProvider(
            api_key=api_key,
            source_url=source_url,
            base_url=os.environ.get("DID_BASE_URL"),
            timeout_seconds=int(os.environ.get("DID_HTTP_TIMEOUT_SECONDS", "60")),
            poll_interval_seconds=float(os.environ.get("DID_POLL_INTERVAL_SECONDS", "3")),
            max_polls=int(os.environ.get("DID_MAX_POLLS", "80")),
            voice_id=os.environ.get("DID_VOICE_ID"),
            voice_provider=os.environ.get("DID_VOICE_PROVIDER"),
        )
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


class DIDAvatarVideoProvider:
    name = "d-id-avatar-video-v1"

    def __init__(
        self,
        api_key: str,
        source_url: str,
        base_url: str | None = None,
        timeout_seconds: int = 60,
        poll_interval_seconds: float = 3.0,
        max_polls: int = 80,
        voice_id: str | None = None,
        voice_provider: str | None = None,
    ):
        self.api_key = api_key
        self.source_url = source_url
        self.base_url = (base_url or "https://api.d-id.com").rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.poll_interval_seconds = poll_interval_seconds
        self.max_polls = max_polls
        self.voice_id = voice_id
        self.voice_provider = voice_provider or "microsoft"

    def render(self, output_dir: Path, script_id: str, script_text: str, title_options: list[str]) -> dict:
        create_response = self._request_json("POST", "/talks", self._talk_payload(script_text))
        immediate_url = clean_string(create_response.get("result_url"))
        if immediate_url:
            return {"provider": self.name, "output_video_url": immediate_url}
        talk_id = clean_string(create_response.get("id"))
        if not talk_id:
            raise AvatarVideoProviderError("D-ID create talk response did not include id or result_url.")
        return self._poll_talk_result(talk_id)

    def _talk_payload(self, script_text: str) -> dict:
        script = {
            "type": "text",
            "input": script_text[:8000],
        }
        if self.voice_id:
            script["provider"] = {
                "type": self.voice_provider,
                "voice_id": self.voice_id,
            }
        return {
            "source_url": self.source_url,
            "script": script,
        }

    def _poll_talk_result(self, talk_id: str) -> dict:
        last_status = ""
        for _attempt in range(self.max_polls):
            response = self._request_json("GET", f"/talks/{talk_id}", None)
            result_url = clean_string(response.get("result_url"))
            status = clean_string(response.get("status")).lower()
            if result_url:
                return {"provider": self.name, "output_video_url": result_url}
            if status in {"error", "failed", "rejected"}:
                message = clean_string(response.get("error")) or clean_string(response.get("message")) or status
                raise AvatarVideoProviderError(f"D-ID render failed: {message}")
            last_status = status or last_status
            time.sleep(self.poll_interval_seconds)
        raise AvatarVideoProviderError(f"D-ID render timed out while waiting for talk {talk_id}; last status: {last_status}.")

    def _request_json(self, method: str, path: str, payload: dict | None) -> dict:
        data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = Request(
            f"{self.base_url}{path}",
            data=data,
            method=method,
            headers={
                "Authorization": did_authorization_header(self.api_key),
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                parsed = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")[:500]
            raise AvatarVideoProviderError(f"D-ID API returned HTTP {exc.code}: {detail}") from exc
        except URLError as exc:
            raise AvatarVideoProviderError(f"D-ID API request failed: {exc.reason}") from exc
        except json.JSONDecodeError as exc:
            raise AvatarVideoProviderError("D-ID API returned invalid JSON response.") from exc
        if not isinstance(parsed, dict):
            raise AvatarVideoProviderError("D-ID API response must be a JSON object.")
        return parsed


def did_authorization_header(api_key: str) -> str:
    stripped = api_key.strip()
    if stripped.lower().startswith(("basic ", "bearer ")):
        return stripped
    encoded = base64.b64encode(stripped.encode("utf-8")).decode("ascii")
    return f"Basic {encoded}"


def did_source_url_from_local_photo(public_base_url: str | None, filename: str | None = None) -> str | None:
    if not public_base_url:
        return None
    photo_path = local_avatar_photo_path(filename)
    if photo_path is None:
        return None
    return f"{public_base_url.rstrip('/')}/photos/{quote(photo_path.name)}"


def local_avatar_photo_path(filename: str | None = None) -> Path | None:
    allowed_suffixes = {".jpg", ".jpeg", ".png", ".webp"}
    if filename:
        candidate = PHOTO_DIR / Path(filename).name
        return candidate if candidate.is_file() and candidate.suffix.lower() in allowed_suffixes else None
    if not PHOTO_DIR.is_dir():
        return None
    candidates = [
        path
        for path in sorted(PHOTO_DIR.iterdir())
        if path.is_file() and path.suffix.lower() in allowed_suffixes
    ]
    return candidates[0] if candidates else None


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
