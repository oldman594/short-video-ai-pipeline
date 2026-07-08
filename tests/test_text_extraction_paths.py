from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.providers import MockASRProvider, MockAvatarVideoProvider, MockLLMProvider, SourceInput
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
    last_line,
    normalize_subtitle_text,
    parse_silencedetect,
    rapidocr_python_config,
    rapidocr_text_from_json,
    read_sidecar_subtitle,
    result_from_text,
    restore_punctuation,
    screen_text_quality_score,
    select_best_local_auto_result,
    segments_from_text,
    split_long_segments,
    text_extraction_tool_status,
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
        scripts = MockLLMProvider().generate_scripts("text", analysis, "")
        self.assertEqual(len(scripts), 3)

        with tempfile.TemporaryDirectory() as tmp:
            result = MockAvatarVideoProvider().render(Path(tmp), "script-1", "脚本", [])
            self.assertTrue((Path(tmp) / result["output_filename"]).is_file())


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
