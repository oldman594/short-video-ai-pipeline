from __future__ import annotations

import os
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from app.providers import (
    DeepSeekAnalysisProvider,
    DeepSeekProviderError,
    DIDAvatarVideoProvider,
    ExternalHttpAvatarVideoProvider,
    AvatarVideoProviderError,
    MockASRProvider,
    MockAvatarVideoProvider,
    MockLLMProvider,
    SourceInput,
    default_avatar_video_provider,
    default_llm_provider,
    derive_writing_profile,
    did_authorization_header,
    did_source_url_from_local_photo,
    extract_chat_message_content,
    local_avatar_photo_path,
    normalize_analysis,
    normalize_scripts,
    parse_json_object,
    safe_output_video_filename,
    strip_data_url_prefix,
)
from app.text_extraction import (
    BaseExtractor,
    ExtractionError,
    NetworkCaptionsExtractor,
    ScreenTextExtractor,
    SpeechExtractor,
    SubtitleTrackExtractor,
    TextExtractionRouter,
    ExtractionResult,
    add_voice_segment,
    dedupe_lines,
    filter_ocr_text,
    format_srt,
    format_srt_time,
    is_douyin_url,
    is_fallback_provider,
    is_platform_ui_ocr_line,
    last_line,
    normalize_subtitle_text,
    parse_silencedetect,
    rapidocr_python_config,
    rapidocr_text_from_json,
    read_sidecar_subtitle,
    result_from_text,
    restore_punctuation,
    screen_text_sampling_filter,
    screen_text_sampling_fps,
    screen_text_quality_score,
    select_best_local_auto_result,
    segments_from_text,
    split_long_segments,
    text_extraction_tool_status,
    video_duration_seconds,
    whisper_cpp_config,
)


def source(**overrides: object) -> SourceInput:
    values = {
        "source_type": "upload",
        "title": "测试视频",
        "platform": "local",
        "source_url": None,
        "source_file_path": None,
        "notes": "",
    }
    values.update(overrides)
    return SourceInput(**values)


class ProviderBranchTest(unittest.TestCase):
    def test_mock_providers_cover_upload_link_derived_topic_and_render_title_fallback(self) -> None:
        # Test objective:
        # Cover the deterministic mock providers used by the MVP when external AI
        # services are not configured.
        #
        # Construction method:
        # 1. Run mock ASR for upload and link sources.
        # 2. Run mock LLM analysis without a title to exercise topic derivation.
        # 3. Render a mock avatar artifact without title options.
        #
        # Input data:
        # Upload and link SourceInput records plus a temporary output directory.
        #
        # Expected behavior:
        # Providers return structured deterministic outputs and the avatar provider
        # writes a local draft artifact.
        upload = MockASRProvider().transcribe(source(source_file_path="/tmp/demo.mp4", notes="补充"))
        link = MockASRProvider().transcribe(source(source_type="link", source_url="https://example.test"))
        self.assertIn("上传视频", upload["raw_text"])
        self.assertIn("链接", link["raw_text"])

        analysis = MockLLMProvider().analyze("第一句话用于推导主题", title="", platform="local")
        self.assertEqual(analysis["topic"], "第一句话用于推导主题")
        self.assertIn("第一句话用于推导主题", analysis["hook"])
        self.assertNotEqual([item["step"] for item in analysis["structure"]], ["hook", "problem", "framework", "close"])
        scripts = MockLLMProvider().generate_scripts("text", analysis, "")
        self.assertEqual(len(scripts), 3)

        with tempfile.TemporaryDirectory() as tmp:
            result = MockAvatarVideoProvider().render(Path(tmp), "script-1", "脚本", [])
            self.assertTrue((Path(tmp) / result["output_filename"]).is_file())

    def test_deepseek_analysis_provider_normalizes_structured_response_without_live_api(self) -> None:
        # Test objective:
        # Verify that the DeepSeek adapter can turn an OpenAI-compatible chat
        # completion response into the analysis shape expected by storage/workflow.
        #
        # Construction method:
        # 1. Subclass the provider to return a deterministic fake chat response.
        # 2. Call analyze and generate_scripts without making any network request.
        # 3. Exercise helper error paths for malformed response/content.
        #
        # Input data:
        # A transcript, title, and fake DeepSeek JSON content.
        #
        # Expected behavior:
        # The provider returns normalized analysis with provider metadata, generates
        # scripts through the script prompt path when possible, and raises clear
        # errors for invalid DeepSeek response shapes.
        class FakeDeepSeek(DeepSeekAnalysisProvider):
            def _post_chat_completion(self, payload: dict) -> dict:
                self.last_payload = payload
                return {
                    "choices": [
                        {
                            "message": {
                                "content": (
                                    '{"topic":"学习方法","audience":"大学生","category":"知识口播",'
                                    '"hook":"反常识开场","structure":[{"step":"hook","summary":"先抛问题"}],'
                                    '"key_points":["保留结构，不复用原句"],"risks":["避免逐句搬运"]}'
                                )
                            }
                        }
                    ]
                }

        provider = FakeDeepSeek(api_key="test-key", base_url="https://example.test", timeout_seconds=1)
        analysis = provider.analyze("期末复习要先抓重点", title="学习技巧", platform="douyin")
        self.assertEqual(analysis["provider"], "deepseek-analysis-v1")
        self.assertEqual(analysis["topic"], "学习方法")
        self.assertIn("期末复习", analysis["hook"])
        self.assertNotEqual(analysis["structure"][0]["step"], "hook")
        self.assertIn("json_object", str(provider.last_payload["response_format"]))
        self.assertEqual(len(provider.generate_scripts("text", analysis, "学习技巧")), 3)

        with self.assertRaises(DeepSeekProviderError):
            extract_chat_message_content({"choices": []})
        with self.assertRaises(DeepSeekProviderError):
            parse_json_object("not-json")

        normalized = normalize_analysis({"structure": ["直接指出痛点"], "key_points": [123, "改写表达"]}, "", "文本", "p")
        self.assertEqual(normalized["structure"][0]["summary"], "直接指出痛点")
        self.assertEqual(normalized["key_points"], ["改写表达"])

    def test_writing_profile_drives_original_script_generation_without_copying_source_lines(self) -> None:
        # Test objective:
        # Verify that script generation is no longer a generic template-only step:
        # it first derives a writing profile from the extracted transcript and then
        # uses that profile to produce original draft scripts.
        #
        # Construction method:
        # 1. Build a transcript with short on-screen subtitle lines, a question, and
        #    numbered steps so the profile has recognizable rhythm and transition cues.
        # 2. Generate scripts through the deterministic mock provider.
        # 3. Normalize a synthetic DeepSeek script response to cover the same storage
        #    contract used by the workflow.
        #
        # Input data:
        # A short Chinese transcript containing the source phrase "期末老师人画重点",
        # a normalized analysis object, and one synthetic LLM script payload.
        #
        # Expected behavior:
        # The writing profile captures short-sentence rhythm and numbered-step
        # transitions; generated scripts mention the transformed writing mode, return
        # three complete versions, and do not copy the source phrase verbatim.
        transcript = "你是不是总在期末慌？\n第一，期末老师人画重点。\n第二，先复盘错题。\n记得收藏。"
        analysis = normalize_analysis(
            {
                "topic": "期末复习",
                "hook": "提问式痛点开场",
                "structure": ["开场提问", "编号拆步骤", "结尾给收藏动作"],
                "key_points": ["保留节奏，不复用原句"],
            },
            "期末复习",
            transcript,
            "test-provider",
        )

        profile = derive_writing_profile(transcript, analysis)
        self.assertIn("短句", profile["rhythm"])
        self.assertIn("编号步骤", profile["transition_style"])
        scripts = MockLLMProvider().generate_scripts(transcript, analysis, "期末复习")

        self.assertEqual(len(scripts), 3)
        self.assertTrue(all("写作模式" in script["script_text"] for script in scripts))
        self.assertTrue(all("期末老师人画重点" not in script["script_text"] for script in scripts))
        self.assertTrue(all(script["storyboard"] for script in scripts))

        normalized_scripts = normalize_scripts(
            [
                {
                    "script_text": "先给结论。\n再讲原因。\n最后给动作。",
                    "title_options": ["复习别乱来"],
                }
            ],
            analysis,
            "期末复习",
            transcript,
            profile,
        )
        self.assertEqual(normalized_scripts[0]["version"], 1)
        self.assertIn("\n", normalized_scripts[0]["script_text"])
        self.assertTrue(normalized_scripts[0]["storyboard"])

    def test_deepseek_script_generation_uses_writing_profile_prompt_without_live_api(self) -> None:
        # Test objective:
        # Verify that the DeepSeek adapter can handle the full content chain after
        # text extraction: structure analysis followed by writing-profile-aware script
        # generation, without calling the live DeepSeek API.
        #
        # Construction method:
        # 1. Subclass the provider and return different fake JSON payloads for the
        #    analysis prompt and the script-generation prompt.
        # 2. Capture the script-generation payload so the prompt contract can be
        #    inspected directly.
        # 3. Call analyze and generate_scripts with one transcript.
        #
        # Input data:
        # A transcript about study planning and fake DeepSeek responses containing
        # two script drafts with title, cover, storyboard, and tag fields.
        #
        # Expected behavior:
        # The provider returns normalized scripts from the DeepSeek response, includes
        # writing-profile fields such as opening pattern and structure steps in the
        # prompt, and does not fall back to the deterministic mock script provider.
        class FakeDeepSeek(DeepSeekAnalysisProvider):
            def _post_chat_completion(self, payload: dict) -> dict:
                user_content = payload["messages"][1]["content"]
                if "请生成 3 个原创视频稿版本" in user_content:
                    self.script_payload = payload
                    return {
                        "choices": [
                            {
                                "message": {
                                    "content": (
                                        '{"scripts":['
                                        '{"version":1,"script_text":"先给结论。\\n再拆原因。",'
                                        '"storyboard":[{"scene":1,"visual":"数字人口播"}],'
                                        '"title_options":["复习先定顺序"],'
                                        '"cover_text_options":["先定顺序"],"tags":["学习"]},'
                                        '{"version":2,"script_text":"先看场景。\\n再给动作。",'
                                        '"storyboard":["步骤字幕"],"title_options":["复习别乱"],'
                                        '"cover_text_options":["别乱复习"],"tags":["方法"]}'
                                        ']}'
                                    )
                                }
                            }
                        ]
                    }
                return {
                    "choices": [
                        {
                            "message": {
                                "content": (
                                    '{"topic":"学习规划","audience":"大学生","category":"知识口播",'
                                    '"hook":"提问式痛点开场","structure":["开场提问","编号步骤","行动收尾"],'
                                    '"key_points":["迁移结构"],"risks":["不要复制原文"]}'
                                )
                            }
                        }
                    ]
                }

        provider = FakeDeepSeek(api_key="test-key", base_url="https://example.test", timeout_seconds=1)
        analysis = provider.analyze("你是不是总在期末慌？第一步先看重点。", "复习规划", "douyin")
        scripts = provider.generate_scripts(
            "你是不是总在期末慌？第一步先看重点。",
            analysis,
            "复习规划",
            target_topic="AI 学习助手",
            target_notes="面向大学新生，强调具体使用边界",
        )

        self.assertEqual(len(scripts), 2)
        self.assertEqual(scripts[0]["script_text"], "先给结论。\n再拆原因。")
        self.assertEqual(scripts[0]["title_options"], ["复习先定顺序"])
        self.assertIn("开场模式", provider.script_payload["messages"][1]["content"])
        self.assertIn("结构步骤", provider.script_payload["messages"][1]["content"])
        self.assertIn("用户选择的新主题：AI 学习助手", provider.script_payload["messages"][1]["content"])
        self.assertIn("面向大学新生", provider.script_payload["messages"][1]["content"])
        self.assertNotIn("很多人做学习规划", scripts[0]["script_text"])

    def test_default_llm_provider_selects_deepseek_only_when_api_key_exists(self) -> None:
        # Test objective:
        # Verify that DeepSeek is opt-in through environment configuration so tests and
        # local MVP runs do not accidentally call a paid third-party API.
        #
        # Construction method:
        # Patch the process environment with and without DEEPSEEK_API_KEY.
        #
        # Input data:
        # Empty environment and one environment containing a placeholder API key.
        #
        # Expected behavior:
        # The default provider is mock without a key and DeepSeekAnalysisProvider with
        # a key; no live request is made by construction.
        with patch.dict(os.environ, {}, clear=True):
            self.assertIsInstance(default_llm_provider(), MockLLMProvider)
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "placeholder"}, clear=True):
            self.assertIsInstance(default_llm_provider(), DeepSeekAnalysisProvider)

    def test_external_avatar_provider_covers_url_base64_and_error_paths(self) -> None:
        # Test objective:
        # Verify the real avatar-video service adapter contract without calling an
        # external provider or requiring paid credentials.
        #
        # Construction method:
        # 1. Patch app.providers.urlopen with fake JSON responses.
        # 2. Exercise both URL-return and base64-return response contracts.
        # 3. Exercise configuration and response validation errors.
        #
        # Input data:
        # Synthetic script text, title options, and fake avatar service responses.
        #
        # Expected behavior:
        # The adapter returns remote URLs directly, stores base64 video bytes under
        # the output directory, maps failures to AvatarVideoProviderError, and is only
        # selected by default when the external-http environment is configured.
        class FakeResponse:
            def __init__(self, body: bytes):
                self.body = body

            def __enter__(self):
                return self

            def __exit__(self, _exc_type, _exc, _tb):
                return False

            def read(self) -> bytes:
                return self.body

        provider = ExternalHttpAvatarVideoProvider("https://avatar.example/render", api_key="secret", timeout_seconds=1)
        with patch("app.providers.urlopen", return_value=FakeResponse(b'{"output_video_url":"https://cdn.example/video.mp4"}')):
            remote = provider.render(Path("/tmp/no-write"), "script-1", "脚本", ["标题"])
        self.assertEqual(remote["output_video_url"], "https://cdn.example/video.mp4")

        with tempfile.TemporaryDirectory() as tmp:
            with patch(
                "app.providers.urlopen",
                return_value=FakeResponse(b'{"filename":"demo video.mp4","output_base64":"ZHVtbXk="}'),
            ):
                local = provider.render(Path(tmp), "script-2", "脚本", [])
            self.assertTrue((Path(tmp) / local["output_filename"]).is_file())
            self.assertEqual((Path(tmp) / local["output_filename"]).read_bytes(), b"dummy")

        with patch("app.providers.urlopen", return_value=FakeResponse(b"{}")):
            with self.assertRaises(AvatarVideoProviderError):
                provider.render(Path("/tmp/no-write"), "script-3", "脚本", [])
        with patch("app.providers.urlopen", return_value=FakeResponse(b'{"output_base64":"not-base64"}')):
            with self.assertRaises(AvatarVideoProviderError):
                provider.render(Path("/tmp/no-write"), "script-4", "脚本", [])

        http_error = HTTPError("https://avatar.example", 500, "server error", {}, BytesIO(b"failed"))
        with patch("app.providers.urlopen", side_effect=http_error):
            with self.assertRaises(AvatarVideoProviderError):
                provider.render(Path("/tmp/no-write"), "script-5", "脚本", [])
        http_error.close()
        with patch("app.providers.urlopen", side_effect=URLError("offline")):
            with self.assertRaises(AvatarVideoProviderError):
                provider.render(Path("/tmp/no-write"), "script-6", "脚本", [])
        with patch("app.providers.urlopen", return_value=FakeResponse(b"not-json")):
            with self.assertRaises(AvatarVideoProviderError):
                provider.render(Path("/tmp/no-write"), "script-7", "脚本", [])

        self.assertEqual(safe_output_video_filename("../bad name.txt", "script-8"), "bad-name.mp4")
        self.assertEqual(strip_data_url_prefix("data:video/mp4;base64,ZHVtbXk="), "ZHVtbXk=")
        with patch.dict(os.environ, {}, clear=True):
            self.assertIsInstance(default_avatar_video_provider(), MockAvatarVideoProvider)
        with patch.dict(os.environ, {"AVATAR_VIDEO_PROVIDER": "external-http"}, clear=True):
            with self.assertRaises(AvatarVideoProviderError):
                default_avatar_video_provider()
        with patch.dict(
            os.environ,
            {"AVATAR_VIDEO_PROVIDER": "external-http", "AVATAR_VIDEO_ENDPOINT": "https://avatar.example/render"},
            clear=True,
        ):
            self.assertIsInstance(default_avatar_video_provider(), ExternalHttpAvatarVideoProvider)

    def test_did_avatar_provider_covers_create_poll_auth_and_errors(self) -> None:
        # Test objective:
        # Verify the D-ID provider integration contract without calling the live D-ID
        # API or spending render credits.
        #
        # Construction method:
        # 1. Patch app.providers.urlopen with ordered fake D-ID create/get responses.
        # 2. Render once through the provider and inspect the generated request.
        # 3. Exercise failed D-ID status, missing configuration, and auth formatting.
        #
        # Input data:
        # A fake D-ID API key, source image URL, script text, and synthetic talk
        # creation/polling JSON responses.
        #
        # Expected behavior:
        # The provider posts a text script to /talks, polls /talks/{id}, returns the
        # completed result_url, maps failure statuses to AvatarVideoProviderError, and
        # is selected by default only when required D-ID env vars are present.
        class FakeResponse:
            def __init__(self, body: bytes):
                self.body = body

            def __enter__(self):
                return self

            def __exit__(self, _exc_type, _exc, _tb):
                return False

            def read(self) -> bytes:
                return self.body

        requests = []

        def fake_urlopen(request, timeout):
            requests.append((request, timeout))
            bodies = [
                b'{"id":"talk-1","status":"created"}',
                b'{"id":"talk-1","status":"started"}',
                b'{"id":"talk-1","status":"done","result_url":"https://cdn.did/video.mp4"}',
            ]
            return FakeResponse(bodies[len(requests) - 1])

        provider = DIDAvatarVideoProvider(
            api_key="user@example.com:secret",
            source_url="https://example.test/avatar.jpg",
            base_url="https://api.d-id.test",
            poll_interval_seconds=0,
            max_polls=3,
            voice_id="zh-CN-XiaoxiaoNeural",
        )
        with patch("app.providers.urlopen", side_effect=fake_urlopen):
            result = provider.render(Path("/tmp/no-write"), "script-1", "口播脚本", ["标题"])

        self.assertEqual(result["provider"], "d-id-avatar-video-v1")
        self.assertEqual(result["output_video_url"], "https://cdn.did/video.mp4")
        create_body = requests[0][0].data.decode("utf-8")
        self.assertIn("https://example.test/avatar.jpg", create_body)
        self.assertIn("zh-CN-XiaoxiaoNeural", create_body)
        self.assertEqual(requests[0][0].get_method(), "POST")
        self.assertEqual(requests[1][0].get_method(), "GET")
        self.assertEqual(did_authorization_header("user@example.com:secret"), "Basic dXNlckBleGFtcGxlLmNvbTpzZWNyZXQ=")
        self.assertEqual(did_authorization_header("Basic already"), "Basic already")

        failed_provider = DIDAvatarVideoProvider(
            api_key="key",
            source_url="https://example.test/avatar.jpg",
            base_url="https://api.d-id.test",
            poll_interval_seconds=0,
            max_polls=1,
        )
        with patch(
            "app.providers.urlopen",
            side_effect=[
                FakeResponse(b'{"id":"talk-2"}'),
                FakeResponse(b'{"id":"talk-2","status":"error","message":"bad source"}'),
            ],
        ):
            with self.assertRaises(AvatarVideoProviderError):
                failed_provider.render(Path("/tmp/no-write"), "script-2", "脚本", [])

        with patch.dict(os.environ, {"AVATAR_VIDEO_PROVIDER": "did"}, clear=True):
            with self.assertRaises(AvatarVideoProviderError):
                default_avatar_video_provider()
        with patch.dict(
            os.environ,
            {
                "AVATAR_VIDEO_PROVIDER": "did",
                "DID_API_KEY": "key",
                "DID_SOURCE_URL": "https://example.test/avatar.jpg",
                "DID_POLL_INTERVAL_SECONDS": "0",
            },
            clear=True,
        ):
            self.assertIsInstance(default_avatar_video_provider(), DIDAvatarVideoProvider)

    def test_did_avatar_provider_can_derive_source_url_from_local_photo_folder(self) -> None:
        # Test objective:
        # Verify that D-ID can use a local photo/ avatar file through the project's
        # public photo route instead of requiring DID_SOURCE_URL to be manually set.
        #
        # Construction method:
        # 1. Patch app.providers.PHOTO_DIR to a temporary directory.
        # 2. Create allowed image files and a disallowed non-image file.
        # 3. Build the provider from environment variables with PUBLIC_BASE_URL only.
        #
        # Input data:
        # A local avatar file with a space in the filename and PUBLIC_BASE_URL.
        #
        # Expected behavior:
        # The helper selects image files only, URL-escapes the filename, and the
        # default D-ID provider receives the derived public /photos URL.
        with tempfile.TemporaryDirectory() as tmp:
            photo_dir = Path(tmp)
            (photo_dir / "avatar face.png").write_bytes(b"png")
            (photo_dir / "notes.txt").write_text("ignore", encoding="utf-8")
            with patch("app.providers.PHOTO_DIR", photo_dir):
                self.assertEqual(local_avatar_photo_path("notes.txt"), None)
                self.assertEqual(local_avatar_photo_path("avatar face.png"), photo_dir / "avatar face.png")
                self.assertEqual(
                    did_source_url_from_local_photo("https://public.example/base", "avatar face.png"),
                    "https://public.example/base/photos/avatar%20face.png",
                )
                with patch.dict(
                    os.environ,
                    {
                        "AVATAR_VIDEO_PROVIDER": "did",
                        "DID_API_KEY": "key",
                        "PUBLIC_BASE_URL": "https://public.example",
                        "DID_PHOTO_FILENAME": "avatar face.png",
                    },
                    clear=True,
                ):
                    provider = default_avatar_video_provider()
                    self.assertIsInstance(provider, DIDAvatarVideoProvider)
                    self.assertEqual(provider.source_url, "https://public.example/photos/avatar%20face.png")

    def test_deepseek_http_client_covers_success_and_error_mapping(self) -> None:
        # Test objective:
        # Cover the DeepSeek HTTP client success path and its local error mapping
        # without sending a live network request or using a real API key.
        #
        # Construction method:
        # 1. Patch app.providers.urlopen with a fake context-manager response.
        # 2. Patch it again to raise HTTPError, URLError, and invalid JSON responses.
        # 3. Exercise helper validation for empty content and non-object JSON.
        #
        # Input data:
        # A minimal chat completion payload and synthetic urllib responses/errors.
        #
        # Expected behavior:
        # Successful responses decode to dictionaries, external failures become
        # DeepSeekProviderError, and malformed model content is rejected.
        class FakeResponse:
            def __init__(self, body: bytes):
                self.body = body

            def __enter__(self):
                return self

            def __exit__(self, _exc_type, _exc, _tb):
                return False

            def read(self) -> bytes:
                return self.body

        provider = DeepSeekAnalysisProvider(api_key="test-key", base_url="https://example.test", timeout_seconds=1)
        with patch("app.providers.urlopen", return_value=FakeResponse(b'{"choices":[]}')):
            self.assertEqual(provider._post_chat_completion({"messages": []}), {"choices": []})

        http_error = HTTPError("https://example.test", 401, "unauthorized", {}, BytesIO(b"bad key"))
        with patch("app.providers.urlopen", side_effect=http_error):
            with self.assertRaises(DeepSeekProviderError):
                provider._post_chat_completion({"messages": []})
        http_error.close()
        with patch("app.providers.urlopen", side_effect=URLError("offline")):
            with self.assertRaises(DeepSeekProviderError):
                provider._post_chat_completion({"messages": []})
        with patch("app.providers.urlopen", return_value=FakeResponse(b"not-json")):
            with self.assertRaises(DeepSeekProviderError):
                provider._post_chat_completion({"messages": []})

        with self.assertRaises(DeepSeekProviderError):
            extract_chat_message_content({"choices": [{"message": {"content": ""}}]})
        with self.assertRaises(DeepSeekProviderError):
            parse_json_object("[]")
        self.assertEqual(normalize_analysis({"structure": "bad"}, "标题", "文本", "p")["provider"], "p")


class TextExtractionBranchTest(unittest.TestCase):
    def test_base_and_helper_functions_cover_text_normalization(self) -> None:
        # Test objective:
        # Cover pure helper functions that normalize subtitle/OCR text and segment
        # extracted text for downstream analysis.
        #
        # Construction method:
        # 1. Call helpers with duplicate subtitle lines, timestamps, OCR noise, and URLs.
        # 2. Call BaseExtractor.extract directly to verify the abstract guard.
        #
        # Input data:
        # Small text snippets with timestamps, duplicate lines, Chinese OCR text, and errors.
        #
        # Expected behavior:
        # Helpers remove subtitle metadata, deduplicate lines, classify URLs, and expose
        # fallback/provider predicates correctly.
        with self.assertRaises(NotImplementedError):
            BaseExtractor().extract(source())
        normalized = normalize_subtitle_text("WEBVTT\n1\n00:00 --> 00:01\n你好<br>世界\n你好世界\n")
        self.assertIn("你好世界", normalized)
        self.assertEqual(dedupe_lines("a\na\nb"), "a\nb")
        self.assertIn("期末老师画重点", filter_ocr_text("xx\n期末老师画重点\n--\n"))
        self.assertNotIn("抖音号", filter_ocr_text("抖音号：3863360\n最后得出一个结论\n"))
        self.assertTrue(is_platform_ui_ocr_line("抖音搜索页扫一扫"))
        self.assertTrue(is_platform_ui_ocr_line("来抖音 发现更多创作者"))
        self.assertTrue(is_platform_ui_ocr_line("音号"))
        self.assertFalse(is_platform_ui_ocr_line("最后得出一个结论"))
        self.assertTrue(is_douyin_url("https://www.douyin.com/video/1"))
        self.assertTrue(is_fallback_provider("speech-fallback"))
        self.assertEqual(last_line("a\nb\n"), "b")
        self.assertGreaterEqual(len(segments_from_text("第一句。第二句。")), 2)
        result = result_from_text("", "provider", "method", ["warn"])
        self.assertIn("未提取到可用文本", result.raw_text)
        self.assertEqual(restore_punctuation(" 你好 世界 "), "你好世界。")
        self.assertEqual(format_srt_time(3661.234), "01:01:01,234")
        srt = format_srt([{"start": 0.0, "end": 1.2, "text": "你好。"}])
        self.assertIn("00:00:00,000 --> 00:00:01,200", srt)
        rapid_text = rapidocr_text_from_json(
            '{"items":[{"text":"咪在2.25万平方厘米醒的床","confidence":0.89},{"text":"x","confidence":0.9}]}'
        )
        self.assertIn("咪在2.25万平方厘米醒的床", rapid_text or "")
        with self.assertRaises(ExtractionError):
            rapidocr_text_from_json("not-json")

    def test_screen_text_sampling_covers_long_videos_across_full_duration(self) -> None:
        # Test objective:
        # Verify that hard-subtitle OCR sampling scales across a long video instead
        # of reading only the first fixed number of seconds.
        #
        # Construction method:
        # 1. Call the pure FPS helper with short-video, long-video, invalid-duration,
        #    and invalid-frame-limit inputs.
        # 2. Patch FFprobe command discovery and process execution to return a
        #    deterministic long-video duration.
        # 3. Patch the FFprobe response to invalid output to cover the safe fallback.
        #
        # Input data:
        # A synthetic 384 second duration matching the local long `vision/` sample,
        # a 30 second short video duration, and malformed FFprobe stdout.
        #
        # Expected behavior:
        # Short videos keep 1 fps; long videos lower fps to max_frames / duration so
        # frames are spread through the whole media; missing or malformed FFprobe
        # output falls back to 1 fps rather than failing OCR extraction.
        class FakeProcess:
            def __init__(self, stdout: str, returncode: int = 0):
                self.stdout = stdout
                self.stderr = ""
                self.returncode = returncode

        self.assertEqual(screen_text_sampling_fps(30.0, 120), 1.0)
        self.assertAlmostEqual(screen_text_sampling_fps(384.0, 90), 0.234375)
        self.assertEqual(screen_text_sampling_fps(None, 120), 1.0)
        self.assertEqual(screen_text_sampling_fps(384.0, 0), 1.0)

        with patch("app.text_extraction.shutil.which", return_value="/bin/ffprobe"), patch(
            "app.text_extraction.subprocess.run", return_value=FakeProcess("383.965896\n")
        ):
            self.assertAlmostEqual(video_duration_seconds(Path("long.mp4")) or 0.0, 383.965896)
            fps_filter = screen_text_sampling_filter(Path("long.mp4"), 90)
        self.assertTrue(fps_filter.startswith("fps=0.2343"))

        with patch("app.text_extraction.shutil.which", return_value="/bin/ffprobe"), patch(
            "app.text_extraction.subprocess.run", return_value=FakeProcess("not-a-duration\n")
        ):
            self.assertIsNone(video_duration_seconds(Path("bad.mp4")))
            self.assertEqual(screen_text_sampling_filter(Path("bad.mp4"), 90), "fps=1.000000")

    def test_vad_parsing_and_segment_splitting_cover_timestamp_alignment_helpers(self) -> None:
        # Test objective:
        # Verify the VAD parsing and chunk splitting helpers that align ASR text back
        # to the original media timeline.
        #
        # Construction method:
        # 1. Parse FFmpeg silencedetect stderr with two silence windows.
        # 2. Add a manual padded segment.
        # 3. Split a long speech segment into bounded ASR chunks.
        #
        # Input data:
        # Synthetic silencedetect stderr and segment dictionaries.
        #
        # Expected behavior:
        # Speech regions avoid silence, include padding, respect minimum duration, and
        # long regions are split into smaller chunks.
        stderr = "silence_start: 1.0\nsilence_end: 2.0\nsilence_start: 5.0\nsilence_end: 6.0\n"
        segments = parse_silencedetect(stderr, duration=8.0, padding=0.1, min_duration=0.2)
        self.assertEqual(segments[0], {"start": 0.0, "end": 1.1})
        self.assertEqual(segments[-1], {"start": 5.9, "end": 8.0})

        manual: list[dict] = []
        add_voice_segment(manual, 2.0, 2.1, 3.0, padding=0.1, min_duration=0.5)
        self.assertEqual(manual, [])
        add_voice_segment(manual, 1.0, 2.0, 3.0, padding=0.1, min_duration=0.5)
        self.assertEqual(manual[0], {"start": 0.9, "end": 2.1})

        split = split_long_segments([{"start": 0.0, "end": 40.0}], max_duration=18.0)
        self.assertEqual(len(split), 3)
        self.assertEqual(split[0], {"start": 0.0, "end": 18.0})

    def test_subtitle_track_paths_cover_no_file_sidecar_probe_and_tool_failures(self) -> None:
        # Test objective:
        # Cover subtitle-track routing for missing files, sidecar subtitles, missing tools,
        # no subtitle stream, successful FFmpeg extraction, and extraction exceptions.
        #
        # Construction method:
        # Use temporary files and patch tool detection/helper functions instead of
        # invoking real FFmpeg.
        #
        # Input data:
        # Missing source_file_path, sidecar .srt text, and mocked FFmpeg/FFprobe outcomes.
        #
        # Expected behavior:
        # The extractor returns sidecar text when present and otherwise returns clear
        # fallback warnings for each failure mode.
        extractor = SubtitleTrackExtractor()
        self.assertIn("没有上传文件", extractor.extract(source()).warnings[0])

        with tempfile.TemporaryDirectory() as tmp:
            media = Path(tmp) / "demo.mp4"
            media.write_text("media", encoding="utf-8")
            media.with_suffix(".srt").write_text("1\n00:00 --> 00:01\n字幕文本", encoding="utf-8")
            sidecar = extractor.extract(source(source_file_path=str(media)))
            self.assertEqual(sidecar.provider, "sidecar-subtitle")
            self.assertIn("字幕文本", sidecar.raw_text)
            self.assertIsNone(read_sidecar_subtitle(Path(tmp) / "missing.mp4"))

            media.with_suffix(".srt").unlink()
            with patch("app.text_extraction.shutil.which", return_value=None):
                missing_tools = extractor.extract(source(source_file_path=str(media)))
                self.assertTrue(any("FFmpeg" in item for item in missing_tools.warnings))

            with patch("app.text_extraction.shutil.which", return_value="/bin/tool"), patch(
                "app.text_extraction.has_subtitle_stream", return_value=False
            ):
                no_stream = extractor.extract(source(source_file_path=str(media)))
                self.assertTrue(any("没有检测到" in item for item in no_stream.warnings))

            with patch("app.text_extraction.shutil.which", return_value="/bin/tool"), patch(
                "app.text_extraction.has_subtitle_stream", return_value=True
            ), patch("app.text_extraction.extract_subtitle_with_ffmpeg", return_value="内嵌字幕"):
                success = extractor.extract(source(source_file_path=str(media)))
                self.assertEqual(success.provider, "ffmpeg")

            with patch("app.text_extraction.shutil.which", return_value="/bin/tool"), patch(
                "app.text_extraction.has_subtitle_stream", side_effect=ExtractionError("probe failed")
            ):
                failed = extractor.extract(source(source_file_path=str(media)))
                self.assertTrue(any("probe failed" in item for item in failed.warnings))

    def test_speech_paths_cover_openai_whisper_whisper_cpp_and_fallbacks(self) -> None:
        # Test objective:
        # Cover speech extraction success and fallback paths without invoking actual ASR.
        #
        # Construction method:
        # Patch command detection and ASR helper functions for each branch.
        #
        # Input data:
        # A fake media path with mocked Whisper/OpenAI and whisper.cpp responses.
        #
        # Expected behavior:
        # OpenAI Whisper wins when it returns text; otherwise whisper.cpp can return text,
        # helper exceptions become warnings, and missing model/tool paths fall back.
        media_source = source(source_file_path="/tmp/media.mp4")
        extractor = SpeechExtractor()
        with patch("app.text_extraction.shutil.which", return_value="/bin/whisper"), patch(
            "app.text_extraction.extract_speech_with_whisper", return_value="openai text"
        ):
            self.assertEqual(extractor.extract(media_source).provider, "whisper")

        with patch("app.text_extraction.shutil.which", return_value="/bin/whisper"), patch(
            "app.text_extraction.extract_speech_with_whisper", return_value=""
        ), patch("app.text_extraction.whisper_cpp_config", return_value=None):
            fallback = extractor.extract(media_source)
            self.assertTrue(any("没有生成" in item for item in fallback.warnings))

        with patch("app.text_extraction.shutil.which", return_value=None), patch(
            "app.text_extraction.whisper_cpp_config", return_value={"cli": Path("/bin/whisper-cli"), "model": Path("m"), "lib_dir": None}
        ), patch("app.text_extraction.extract_speech_with_whisper_cpp", return_value="cpp text"):
            cpp = extractor.extract(media_source)
            self.assertEqual(cpp.provider, "whisper.cpp")

        with patch("app.text_extraction.shutil.which", return_value=None), patch(
            "app.text_extraction.whisper_cpp_config", return_value={"cli": Path("/bin/whisper-cli"), "model": Path("m"), "lib_dir": None}
        ), patch("app.text_extraction.extract_speech_with_whisper_cpp", side_effect=ExtractionError("cpp failed")):
            failed = extractor.extract(media_source)
            self.assertTrue(any("cpp failed" in item for item in failed.warnings))

    def test_screen_text_paths_cover_success_missing_tools_and_errors(self) -> None:
        # Test objective:
        # Cover OCR extraction branches for missing file, missing tools, RapidOCR
        # success, Tesseract fallback success, empty OCR result, and helper exceptions.
        #
        # Construction method:
        # Patch tool detection and OCR helper calls without invoking real OCR tools.
        #
        # Input data:
        # A fake media path and mocked OCR outcomes.
        #
        # Expected behavior:
        # The extractor returns OCR text on success and fallback warnings otherwise.
        extractor = ScreenTextExtractor()
        self.assertIn("没有上传文件", extractor.extract(source()).warnings[0])
        media_source = source(source_file_path="/tmp/media.mp4")
        with patch("app.text_extraction.shutil.which", return_value=None), patch(
            "app.text_extraction.rapidocr_python_config", return_value=None
        ):
            missing = extractor.extract(media_source)
            self.assertTrue(any("FFmpeg" in item for item in missing.warnings))
        with patch("app.text_extraction.shutil.which", return_value="/bin/ffmpeg"), patch(
            "app.text_extraction.rapidocr_python_config",
            return_value={"python": Path("/tmp/python"), "helper": Path("/tmp/helper.py")},
        ), patch("app.text_extraction.extract_screen_text_with_rapidocr", return_value="硬字幕"):
            self.assertEqual(extractor.extract(media_source).provider, "ffmpeg-rapidocr")
        with patch("app.text_extraction.shutil.which", return_value="/bin/tool"), patch(
            "app.text_extraction.rapidocr_python_config", return_value=None
        ), patch(
            "app.text_extraction.extract_screen_text_with_tesseract", return_value="画面字幕"
        ):
            self.assertEqual(extractor.extract(media_source).provider, "ffmpeg-tesseract")
        with patch("app.text_extraction.shutil.which", return_value="/bin/tool"), patch(
            "app.text_extraction.rapidocr_python_config",
            return_value={"python": Path("/tmp/python"), "helper": Path("/tmp/helper.py")},
        ), patch("app.text_extraction.extract_screen_text_with_rapidocr", side_effect=ExtractionError("rapid failed")), patch(
            "app.text_extraction.extract_screen_text_with_tesseract", return_value=""
        ):
            warnings = extractor.extract(media_source).warnings
            self.assertTrue(any("rapid failed" in item for item in warnings))
            self.assertTrue(any("未识别" in item for item in warnings))
        with patch("app.text_extraction.shutil.which", return_value="/bin/tool"), patch(
            "app.text_extraction.rapidocr_python_config", return_value=None
        ), patch(
            "app.text_extraction.extract_screen_text_with_tesseract", side_effect=ExtractionError("ocr failed")
        ):
            self.assertTrue(any("ocr failed" in item for item in extractor.extract(media_source).warnings))

    def test_network_caption_paths_cover_compliance_disabled_tools_success_and_errors(self) -> None:
        # Test objective:
        # Cover network-caption extraction branches while preserving the compliance
        # boundary that blocks Douyin scraping by default.
        #
        # Construction method:
        # Patch environment variables, tool detection, and yt-dlp helper results.
        #
        # Input data:
        # Sources with no URL, a Douyin URL, and a generic URL.
        #
        # Expected behavior:
        # The extractor emits clear warnings for blocked/disabled paths and returns
        # yt-dlp text only when the network fetch flag and tool are available.
        extractor = NetworkCaptionsExtractor()
        self.assertIn("没有视频链接", extractor.extract(source(source_type="link")).warnings[0])
        douyin = extractor.extract(source(source_type="link", source_url="https://www.douyin.com/video/1"))
        self.assertTrue(any("不抓取抖音" in item for item in douyin.warnings))
        generic_source = source(source_type="link", source_url="https://example.test/video")
        with patch.dict(os.environ, {}, clear=True):
            disabled = extractor.extract(generic_source)
            self.assertTrue(any("默认关闭" in item for item in disabled.warnings))
        with patch.dict(os.environ, {"ALLOW_NETWORK_MEDIA_FETCH": "1"}, clear=True), patch(
            "app.text_extraction.shutil.which", return_value=None
        ):
            no_tool = extractor.extract(generic_source)
            self.assertTrue(any("yt-dlp" in item for item in no_tool.warnings))
        with patch.dict(os.environ, {"ALLOW_NETWORK_MEDIA_FETCH": "1"}, clear=True), patch(
            "app.text_extraction.shutil.which", return_value="/bin/yt-dlp"
        ), patch("app.text_extraction.extract_network_captions_with_ytdlp", return_value="网络字幕"):
            self.assertEqual(extractor.extract(generic_source).provider, "yt-dlp")
        with patch.dict(os.environ, {"ALLOW_NETWORK_MEDIA_FETCH": "1"}, clear=True), patch(
            "app.text_extraction.shutil.which", return_value="/bin/yt-dlp"
        ), patch("app.text_extraction.extract_network_captions_with_ytdlp", side_effect=ExtractionError("network failed")):
            self.assertTrue(any("network failed" in item for item in extractor.extract(generic_source).warnings))

    def test_router_and_tool_status_cover_invalid_and_empty_plan_paths(self) -> None:
        # Test objective:
        # Cover router validation, empty-plan defensive behavior, and server tool status.
        #
        # Construction method:
        # Use normal router construction plus a temporary monkey patch for an empty plan.
        #
        # Input data:
        # Invalid preference and a link source.
        #
        # Expected behavior:
        # Invalid preferences raise ValueError, empty plans fall back to speech, and tool
        # status reports server-side extraction metadata.
        router = TextExtractionRouter()
        with self.assertRaises(ValueError):
            router.extract(source(), "bad")
        with patch.object(TextExtractionRouter, "plan", return_value=[]):
            fallback = router.extract(source(source_type="link"), "auto")
            self.assertEqual(fallback["extraction_method"], "speech")
        status = text_extraction_tool_status()
        self.assertTrue(status["server_side_extraction"])
        self.assertIn("tools", status)
        config = whisper_cpp_config()
        self.assertTrue(config is None or "cli" in config)
        ocr_config = rapidocr_python_config()
        self.assertTrue(ocr_config is None or "python" in ocr_config)

    def test_auto_local_media_selects_high_quality_screen_text_over_speech(self) -> None:
        # Test objective:
        # Verify that auto mode returns a single best transcript and prefers strong
        # visual subtitle OCR over ASR when both are available.
        #
        # Construction method:
        # 1. Replace router extractors with small fake extractors.
        # 2. Make subtitle-track return a fallback result.
        # 3. Make speech and screen_text both return real results, with OCR using
        #    enough Chinese subtitle text to pass the quality threshold.
        #
        # Input data:
        # A local media source with a source_file_path.
        #
        # Expected behavior:
        # Auto mode returns the OCR transcript only; ASR text is not mixed into the
        # user-facing raw_text.
        class FakeExtractor:
            def __init__(self, method: str, provider: str, text: str, warnings: list[str] | None = None):
                self.method = method
                self.provider = provider
                self.text = text
                self.warnings = warnings or []

            def extract(self, _source: SourceInput):
                return result_from_text(
                    self.text,
                    provider=self.provider,
                    extraction_method=self.method,
                    warnings=self.warnings,
                )

        router = TextExtractionRouter()
        router.extractors = {
            "subtitle_track": FakeExtractor("subtitle_track", "subtitle-fallback", "fallback", ["no track"]),
            "speech": FakeExtractor("speech", "whisper.cpp", "语音文本"),
            "screen_text": FakeExtractor("screen_text", "ffmpeg-rapidocr", "第一行画面字幕\n第二行画面字幕"),
            "network_captions": NetworkCaptionsExtractor(),
        }
        router.extractors["speech"].extract = lambda _source: ExtractionResult(
            raw_text="语音文本",
            segments=[{"start": 0.0, "end": 1.0, "text": "语音文本。"}],
            language="zh",
            provider="whisper.cpp",
            extraction_method="speech",
            warnings=[],
            subtitle_file_url="/outputs/speech-test.srt",
        )
        result = router.extract(source(source_file_path="/tmp/media.mp4"), "auto")

        self.assertEqual(result["extraction_method"], "screen_text")
        self.assertEqual(result["provider"], "ffmpeg-rapidocr")
        self.assertNotIn("语音文本", result["raw_text"])
        self.assertIn("第一行画面字幕", result["raw_text"])
        self.assertNotIn("subtitle_file_url", result)

    def test_subtitle_track_preference_falls_back_to_screen_text_for_burned_in_subtitles(self) -> None:
        # Test objective:
        # Verify the browser-facing route when a user selects "subtitle track" for
        # a short-video file whose captions are actually burned into the picture.
        #
        # Construction method:
        # 1. Replace the subtitle-track extractor with a fallback result representing
        #    "no independent subtitle stream".
        # 2. Replace the screen-text extractor with a successful OCR result.
        # 3. Run the router with explicit subtitle_track preference and a local file.
        #
        # Input data:
        # A local media source with source_file_path, a subtitle-track fallback, and
        # a successful RapidOCR transcript.
        #
        # Expected behavior:
        # The router returns the OCR transcript and preserves the subtitle warning so
        # the UI explains why it moved from independent subtitles to screen OCR.
        class FakeExtractor:
            def __init__(self, method: str, provider: str, text: str, warnings: list[str] | None = None):
                self.method = method
                self.provider = provider
                self.text = text
                self.warnings = warnings or []

            def extract(self, _source: SourceInput):
                return result_from_text(
                    self.text,
                    provider=self.provider,
                    extraction_method=self.method,
                    warnings=self.warnings,
                )

        router = TextExtractionRouter()
        router.extractors["subtitle_track"] = FakeExtractor(
            "subtitle_track",
            "ffmpeg-or-mkvtoolnix-fallback",
            "字幕轨回退文本",
            ["视频没有检测到独立字幕轨"],
        )
        router.extractors["screen_text"] = FakeExtractor(
            "screen_text",
            "ffmpeg-rapidocr",
            "第一行画面字幕\n第二行画面字幕",
        )

        result = router.extract(source(source_file_path="/tmp/media.mp4"), "subtitle_track")

        self.assertEqual(result["extraction_method"], "screen_text")
        self.assertEqual(result["provider"], "ffmpeg-rapidocr")
        self.assertIn("第一行画面字幕", result["raw_text"])
        self.assertTrue(any("独立字幕轨" in warning for warning in result["warnings"]))

    def test_auto_local_media_falls_back_to_speech_when_screen_text_quality_is_low(self) -> None:
        # Test objective:
        # Ensure that a weak OCR result does not override a real speech transcript.
        #
        # Construction method:
        # Call the auto-result arbitration helper directly with a real ASR result and
        # a short noisy OCR result that does not meet the visual-text score threshold.
        #
        # Input data:
        # Synthetic ExtractionResult records for speech and OCR candidates.
        #
        # Expected behavior:
        # The selector chooses speech for low-quality OCR, but chooses OCR when the
        # OCR quality score is strong.
        speech = result_from_text("语音转写文本", "whisper.cpp", "speech", [])
        low_ocr = result_from_text("噪声", "ffmpeg-tesseract", "screen_text", [])
        high_ocr = result_from_text("第一行画面字幕\n第二行画面字幕", "ffmpeg-rapidocr", "screen_text", [])

        self.assertEqual(screen_text_quality_score(low_ocr), 2)
        self.assertEqual(select_best_local_auto_result(speech, low_ocr), speech)
        self.assertEqual(select_best_local_auto_result(speech, high_ocr), high_ocr)

    def test_auto_local_media_returns_subtitle_track_without_combining(self) -> None:
        # Test objective:
        # Verify that real subtitle-track text remains the highest-quality source and
        # short-circuits local auto mode.
        #
        # Construction method:
        # Replace the subtitle extractor with a fake real subtitle result.
        #
        # Input data:
        # A local media source with a source_file_path.
        #
        # Expected behavior:
        # Auto mode returns the subtitle-track result directly rather than combining
        # lower-priority ASR/OCR outputs.
        class FakeSubtitle:
            def extract(self, _source: SourceInput):
                return result_from_text("字幕轨文本", "sidecar-subtitle", "subtitle_track", [])

        router = TextExtractionRouter()
        router.extractors["subtitle_track"] = FakeSubtitle()
        result = router.extract(source(source_file_path="/tmp/media.mp4"), "auto")

        self.assertEqual(result["extraction_method"], "subtitle_track")
        self.assertEqual(result["raw_text"], "字幕轨文本")


if __name__ == "__main__":
    unittest.main()
