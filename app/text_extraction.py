from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

from app.config import OUTPUT_DIR, ROOT_DIR
from app.providers import SourceInput


VALID_EXTRACTION_PREFERENCES = {
    "auto",
    "subtitle_track",
    "speech",
    "screen_text",
    "network_captions",
}

TEXT_EXTRACTION_TOOLS = {
    "ffmpeg": {
        "purpose": "读取字幕轨、抽取音频、抽帧给 OCR。",
        "install_hint": "Ubuntu/Debian: sudo apt-get install ffmpeg",
    },
    "mkvextract": {
        "purpose": "使用 MKVToolNix 提取 MKV 字幕轨。",
        "install_hint": "Ubuntu/Debian: sudo apt-get install mkvtoolnix",
    },
    "whisper": {
        "purpose": "本地语音识别。",
        "install_hint": "建议在虚拟环境中安装 openai-whisper，并确保 FFmpeg 可用。",
    },
    "tesseract": {
        "purpose": "画面文字 OCR。",
        "install_hint": "Ubuntu/Debian: sudo apt-get install tesseract-ocr tesseract-ocr-chi-sim",
    },
    "yt-dlp": {
        "purpose": "授权范围内的网络字幕提取。",
        "install_hint": "建议在虚拟环境中安装 yt-dlp，网络提取还需要 ALLOW_NETWORK_MEDIA_FETCH=1。",
    },
}


@dataclass(frozen=True)
class ExtractionResult:
    raw_text: str
    segments: list[dict]
    language: str
    provider: str
    extraction_method: str
    warnings: list[str]
    subtitle_file_url: str | None = None

    def to_transcript(self) -> dict:
        transcript = {
            "raw_text": self.raw_text,
            "segments": self.segments,
            "language": self.language,
            "provider": self.provider,
            "extraction_method": self.extraction_method,
            "warnings": self.warnings,
        }
        if self.subtitle_file_url:
            transcript["subtitle_file_url"] = self.subtitle_file_url
        return transcript


class ExtractionError(RuntimeError):
    pass


class BaseExtractor:
    method = "base"
    provider = "base"

    def extract(self, source: SourceInput) -> ExtractionResult:
        raise NotImplementedError

    def fallback(self, source: SourceInput, warnings: list[str]) -> ExtractionResult:
        subject = source.title or "参考视频"
        raw_text = (
            f"这是通过 {self.method} 路径生成的回退转写。"
            f"视频主题暂定为 {subject}。"
            "当前环境缺少该路径所需的真实提取工具，所以先生成可编辑文本，"
            "用于继续验证内容分析、脚本生成和审核流程。"
        )
        if source.notes:
            raw_text += f" 用户补充背景：{source.notes}"
        return result_from_text(
            raw_text,
            provider=f"{self.provider}-fallback",
            extraction_method=self.method,
            warnings=warnings,
        )


class SubtitleTrackExtractor(BaseExtractor):
    method = "subtitle_track"
    provider = "ffmpeg-or-mkvtoolnix"

    def extract(self, source: SourceInput) -> ExtractionResult:
        warnings: list[str] = []
        if not source.source_file_path:
            return self.fallback(source, ["没有上传文件，无法读取内嵌字幕轨。"])

        path = Path(source.source_file_path)
        sidecar_text = read_sidecar_subtitle(path)
        if sidecar_text:
            return result_from_text(
                sidecar_text,
                provider="sidecar-subtitle",
                extraction_method=self.method,
                warnings=[],
            )

        ffmpeg = shutil.which("ffmpeg")
        ffprobe = shutil.which("ffprobe")
        if ffmpeg and ffprobe:
            try:
                if not has_subtitle_stream(ffprobe, path):
                    warnings.append("视频没有检测到独立字幕轨；如果字幕是画面文字，请使用 OCR 或自动模式。")
                    text = None
                else:
                    text = extract_subtitle_with_ffmpeg(ffmpeg, path)
                if text:
                    return result_from_text(
                        text,
                        provider="ffmpeg",
                        extraction_method=self.method,
                        warnings=[],
                    )
                warnings.append("FFmpeg 未提取到可用独立字幕轨文本。")
            except ExtractionError as exc:
                warnings.append(str(exc))
        else:
            warnings.append("未安装 FFmpeg/FFprobe，无法自动读取视频内嵌字幕轨。")

        if not shutil.which("mkvextract"):
            warnings.append("未安装 MKVToolNix/mkvextract，无法尝试 MKV 字幕轨提取。")

        return self.fallback(source, warnings)


class SpeechExtractor(BaseExtractor):
    method = "speech"
    provider = "whisper-or-cloud-asr"

    def extract(self, source: SourceInput) -> ExtractionResult:
        warnings: list[str] = []
        whisper = shutil.which("whisper")
        if whisper and source.source_file_path:
            try:
                text = extract_speech_with_whisper(whisper, Path(source.source_file_path))
                if text:
                    return result_from_text(
                        text,
                        provider="whisper",
                        extraction_method=self.method,
                        warnings=[],
                    )
                warnings.append("Whisper 没有生成可用文本。")
            except ExtractionError as exc:
                warnings.append(str(exc))
        else:
            warnings.append("未安装 OpenAI Whisper CLI 或没有本地媒体文件。")
        if source.source_file_path:
            whisper_cpp = whisper_cpp_config()
            if whisper_cpp:
                try:
                    text = extract_speech_with_whisper_cpp(whisper_cpp, Path(source.source_file_path))
                    if isinstance(text, ExtractionResult):
                        return text
                    if text:
                        return result_from_text(
                            text,
                            provider="whisper.cpp",
                            extraction_method=self.method,
                            warnings=[],
                        )
                    warnings.append("whisper.cpp 没有生成可用文本。")
                except ExtractionError as exc:
                    warnings.append(str(exc))
            else:
                warnings.append("未找到可用 whisper.cpp CLI 或模型。")
        warnings.append("语音识别使用回退文本。")
        return self.fallback(source, warnings)


class ScreenTextExtractor(BaseExtractor):
    method = "screen_text"
    provider = "paddleocr-tesseract-videosubfinder"

    def extract(self, source: SourceInput) -> ExtractionResult:
        warnings: list[str] = []
        if not source.source_file_path:
            return self.fallback(source, ["没有上传文件，无法对画面文字做 OCR。"])

        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            return self.fallback(source, ["未安装 FFmpeg，无法抽帧给 OCR 使用。"])

        rapidocr = rapidocr_python_config()
        if rapidocr:
            try:
                text = extract_screen_text_with_rapidocr(ffmpeg, rapidocr, Path(source.source_file_path))
                if text:
                    return result_from_text(
                        text,
                        provider="ffmpeg-rapidocr",
                        extraction_method=self.method,
                        warnings=[],
                    )
                warnings.append("RapidOCR 未识别到可用画面文字。")
            except ExtractionError as exc:
                warnings.append(str(exc))
        else:
            warnings.append("未找到 RapidOCR 本地环境，继续尝试 Tesseract OCR。")

        tesseract = shutil.which("tesseract")
        if tesseract and ffmpeg:
            try:
                text = extract_screen_text_with_tesseract(ffmpeg, tesseract, Path(source.source_file_path))
                if text:
                    return result_from_text(
                        text,
                        provider="ffmpeg-tesseract",
                        extraction_method=self.method,
                        warnings=[],
                    )
                warnings.append("Tesseract 未识别到可用画面文字。")
            except ExtractionError as exc:
                warnings.append(str(exc))
        else:
            if not tesseract:
                warnings.append("未安装 Tesseract，无法识别画面文字。")
            warnings.append("如需更好的中文字幕 OCR，可安装 RapidOCR、PaddleOCR 或 VideoSubFinder。")

        return self.fallback(source, warnings)


class NetworkCaptionsExtractor(BaseExtractor):
    method = "network_captions"
    provider = "yt-dlp-captions"

    def extract(self, source: SourceInput) -> ExtractionResult:
        warnings: list[str] = []
        if not source.source_url:
            return self.fallback(source, ["没有视频链接，无法尝试网络字幕。"])
        if is_douyin_url(source.source_url):
            return self.fallback(
                source,
                ["出于合规边界，MVP 不抓取抖音链接字幕；请上传文件或手动提供字幕文本。"],
            )
        if os.environ.get("ALLOW_NETWORK_MEDIA_FETCH") != "1":
            return self.fallback(
                source,
                ["网络字幕抓取默认关闭；如确认有授权，可设置 ALLOW_NETWORK_MEDIA_FETCH=1 后重试。"],
            )
        ytdlp = shutil.which("yt-dlp")
        if not ytdlp:
            return self.fallback(source, ["未安装 yt-dlp，无法尝试网络字幕提取。"])

        try:
            text = extract_network_captions_with_ytdlp(ytdlp, source.source_url)
            if text:
                return result_from_text(
                    text,
                    provider="yt-dlp",
                    extraction_method=self.method,
                    warnings=[],
                )
            warnings.append("yt-dlp 没有提取到可用字幕。")
        except ExtractionError as exc:
            warnings.append(str(exc))
        return self.fallback(source, warnings)


class TextExtractionRouter:
    def __init__(self):
        self.extractors = {
            "subtitle_track": SubtitleTrackExtractor(),
            "speech": SpeechExtractor(),
            "screen_text": ScreenTextExtractor(),
            "network_captions": NetworkCaptionsExtractor(),
        }

    def extract(self, source: SourceInput, preference: str = "auto") -> dict:
        if preference not in VALID_EXTRACTION_PREFERENCES:
            raise ValueError(f"unknown extraction preference: {preference}")
        if preference == "auto" and source.source_file_path:
            return self.extract_local_auto(source)
        plan = self.plan(source, preference)
        accumulated_warnings: list[str] = []
        last_result: ExtractionResult | None = None
        for method in plan:
            raw_result = self.extractors[method].extract(source)
            combined_warnings = [*accumulated_warnings, *raw_result.warnings]
            result = ExtractionResult(
                raw_text=raw_result.raw_text,
                segments=raw_result.segments,
                language=raw_result.language,
                provider=raw_result.provider,
                extraction_method=raw_result.extraction_method,
                warnings=combined_warnings,
                subtitle_file_url=raw_result.subtitle_file_url,
            )
            if not is_fallback_provider(result.provider):
                return result.to_transcript()
            accumulated_warnings = combined_warnings
            last_result = result
        if last_result is not None:
            return last_result.to_transcript()
        return self.extractors["speech"].extract(source).to_transcript()

    def extract_local_auto(self, source: SourceInput) -> dict:
        subtitle = self.extractors["subtitle_track"].extract(source)
        if not is_fallback_provider(subtitle.provider):
            return subtitle.to_transcript()

        speech = self.extractors["speech"].extract(source)
        ocr = self.extractors["screen_text"].extract(source)
        real_results = [
            result
            for result in (speech, ocr)
            if not is_fallback_provider(result.provider)
        ]
        warnings = [*subtitle.warnings, *speech.warnings, *ocr.warnings]
        if not real_results:
            fallback = ocr if ocr.warnings else speech
            return ExtractionResult(
                raw_text=fallback.raw_text,
                segments=fallback.segments,
                language=fallback.language,
                provider=fallback.provider,
                extraction_method=fallback.extraction_method,
                warnings=warnings,
            ).to_transcript()
        if len(real_results) == 1:
            result = real_results[0]
            return ExtractionResult(
                raw_text=result.raw_text,
                segments=result.segments,
                language=result.language,
                provider=result.provider,
                extraction_method=result.extraction_method,
                warnings=warnings,
                subtitle_file_url=result.subtitle_file_url,
            ).to_transcript()

        raw_text = "\n\n".join(
            f"[{result.extraction_method} / {result.provider}]\n{result.raw_text}"
            for result in real_results
        )
        combined = result_from_text(
            raw_text,
            provider="+".join(result.provider for result in real_results),
            extraction_method="auto_combined",
            warnings=warnings,
        )
        subtitle_urls = [result.subtitle_file_url for result in real_results if result.subtitle_file_url]
        return ExtractionResult(
            raw_text=combined.raw_text,
            segments=combined.segments,
            language=combined.language,
            provider=combined.provider,
            extraction_method=combined.extraction_method,
            warnings=combined.warnings,
            subtitle_file_url=subtitle_urls[0] if subtitle_urls else None,
        ).to_transcript()

    def plan(self, source: SourceInput, preference: str) -> list[str]:
        if preference != "auto":
            return [preference]
        if source.source_file_path:
            return ["subtitle_track", "speech", "screen_text"]
        if source.source_type == "link":
            return ["network_captions", "speech"]
        return ["subtitle_track", "speech"]


def text_extraction_tool_status() -> dict:
    tools = []
    for command, metadata in TEXT_EXTRACTION_TOOLS.items():
        path = shutil.which(command)
        tools.append(
            {
                "name": command,
                "available": path is not None,
                "path": path,
                "purpose": metadata["purpose"],
                "install_hint": metadata["install_hint"],
            }
        )
    local_cpp = whisper_cpp_config()
    tools.append(
        {
            "name": "whisper.cpp-model",
            "available": local_cpp is not None,
            "path": str(local_cpp["cli"]) if local_cpp else None,
            "purpose": "whisper.cpp 语音识别命令和本地模型。",
            "install_hint": "安装 whisper.cpp，并运行 scripts/bootstrap_whispercpp_local.sh 下载 tiny 模型。",
        }
    )
    rapidocr = rapidocr_python_config()
    tools.append(
        {
            "name": "rapidocr",
            "available": rapidocr is not None,
            "path": str(rapidocr["python"]) if rapidocr else None,
            "purpose": "RapidOCR 本地画面硬字幕识别。",
            "install_hint": "运行 scripts/bootstrap_ocr_local.sh 创建 .venv-ocr 并安装 rapidocr_onnxruntime。",
        }
    )
    return {
        "tools": tools,
        "network_fetch_enabled": os.environ.get("ALLOW_NETWORK_MEDIA_FETCH") == "1",
        "server_side_extraction": True,
    }


def read_sidecar_subtitle(video_path: Path) -> str | None:
    for suffix in (".srt", ".vtt", ".ass", ".ssa", ".txt"):
        sidecar = video_path.with_suffix(suffix)
        if sidecar.is_file():
            return normalize_subtitle_text(sidecar.read_text(encoding="utf-8", errors="ignore"))
    return None


def extract_subtitle_with_ffmpeg(ffmpeg: str, video_path: Path) -> str | None:
    with tempfile.TemporaryDirectory() as tmp:
        output_path = Path(tmp) / "subtitle.srt"
        proc = subprocess.run(
            [ffmpeg, "-y", "-i", str(video_path), "-map", "0:s:0", str(output_path)],
            text=True,
            capture_output=True,
            timeout=60,
            check=False,
        )
        if proc.returncode != 0:
            raise ExtractionError(f"FFmpeg 字幕提取失败：{last_line(proc.stderr)}")
        if not output_path.is_file():
            return None
        return normalize_subtitle_text(output_path.read_text(encoding="utf-8", errors="ignore"))


def has_subtitle_stream(ffprobe: str, video_path: Path) -> bool:
    proc = subprocess.run(
        [
            ffprobe,
            "-hide_banner",
            "-loglevel",
            "error",
            "-select_streams",
            "s",
            "-show_entries",
            "stream=index",
            "-of",
            "csv=p=0",
            str(video_path),
        ],
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    if proc.returncode != 0:
        raise ExtractionError(f"FFprobe 字幕轨检测失败：{last_line(proc.stderr)}")
    return bool(proc.stdout.strip())


def extract_speech_with_whisper(whisper: str, media_path: Path) -> str | None:
    with tempfile.TemporaryDirectory() as tmp:
        proc = subprocess.run(
            [
                whisper,
                str(media_path),
                "--language",
                "Chinese",
                "--task",
                "transcribe",
                "--output_format",
                "txt",
                "--output_dir",
                tmp,
            ],
            text=True,
            capture_output=True,
            timeout=300,
            check=False,
        )
        if proc.returncode != 0:
            raise ExtractionError(f"Whisper 语音识别失败：{last_line(proc.stderr)}")
        txt_files = list(Path(tmp).glob("*.txt"))
        if not txt_files:
            return None
        return txt_files[0].read_text(encoding="utf-8", errors="ignore").strip()


def whisper_cpp_config() -> dict | None:
    model = ROOT_DIR / ".local" / "models" / "ggml-tiny.bin"
    system_cli = shutil.which("whisper-cli")
    if system_cli and model.is_file():
        return {"cli": Path(system_cli), "lib_dir": None, "model": model}
    cli = ROOT_DIR / ".local" / "whispercpp" / "usr" / "bin" / "whisper-cli"
    lib_dir = ROOT_DIR / ".local" / "whispercpp" / "usr" / "lib" / "x86_64-linux-gnu"
    if cli.is_file() and model.is_file() and lib_dir.is_dir():
        return {"cli": cli, "lib_dir": lib_dir, "model": model}
    return None


def rapidocr_python_config() -> dict | None:
    helper = ROOT_DIR / "scripts" / "rapidocr_screen_text.py"
    if not helper.is_file():
        return None
    candidates = []
    env_python = os.environ.get("RAPIDOCR_PYTHON")
    if env_python:
        candidates.append(Path(env_python))
    candidates.append(ROOT_DIR / ".venv-ocr" / "bin" / "python")
    for python in candidates:
        if python.is_file():
            return {"python": python, "helper": helper}
    return None


def extract_speech_with_whisper_cpp(config: dict, media_path: Path) -> str | None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise ExtractionError("whisper.cpp 需要 FFmpeg 先抽取 WAV 音频。")
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        denoised_audio = prepare_asr_audio(ffmpeg, media_path, tmp_dir)
        speech_segments = detect_voice_segments(ffmpeg, denoised_audio)
        if not speech_segments:
            duration = audio_duration_seconds(shutil.which("ffprobe") or "ffprobe", denoised_audio)
            speech_segments = [{"start": 0.0, "end": max(duration, 0.1)}]

        aligned_segments: list[dict] = []
        for index, segment in enumerate(speech_segments, start=1):
            chunk_path = slice_audio(ffmpeg, denoised_audio, segment, tmp_dir, index)
            text = run_whisper_cpp_chunk(config, chunk_path, tmp_dir, index)
            punctuated = restore_punctuation(text)
            if punctuated:
                aligned_segments.append(
                    {
                        "start": round(segment["start"], 2),
                        "end": round(segment["end"], 2),
                        "text": punctuated,
                    }
                )

        if not aligned_segments:
            return None
        raw_text = "\n".join(segment["text"] for segment in aligned_segments)
        subtitle_url = write_srt_file(aligned_segments)
        return ExtractionResult(
            raw_text=raw_text,
            segments=aligned_segments,
            language="zh",
            provider="whisper.cpp",
            extraction_method="speech",
            warnings=[],
            subtitle_file_url=subtitle_url,
        )


def prepare_asr_audio(ffmpeg: str, media_path: Path, output_dir: Path) -> Path:
    output_path = output_dir / "asr-denoised.wav"
    proc = subprocess.run(
        [
            ffmpeg,
            "-y",
            "-i",
            str(media_path),
            "-af",
            "highpass=f=80,lowpass=f=7600,afftdn=nf=-25,dynaudnorm=f=150:g=15,loudnorm=I=-16:LRA=11:TP=-1.5",
            "-ar",
            "16000",
            "-ac",
            "1",
            "-c:a",
            "pcm_s16le",
            str(output_path),
        ],
        text=True,
        capture_output=True,
        timeout=180,
        check=False,
    )
    if proc.returncode != 0:
        raise ExtractionError(f"FFmpeg 音频抽取/降噪失败：{last_line(proc.stderr)}")
    return output_path


def detect_voice_segments(ffmpeg: str, audio_path: Path) -> list[dict]:
    proc = subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-i",
            str(audio_path),
            "-af",
            "silencedetect=noise=-35dB:d=0.35",
            "-f",
            "null",
            "-",
        ],
        text=True,
        capture_output=True,
        timeout=180,
        check=False,
    )
    if proc.returncode != 0:
        raise ExtractionError(f"FFmpeg VAD 检测失败：{last_line(proc.stderr)}")
    duration = audio_duration_seconds(shutil.which("ffprobe") or "ffprobe", audio_path)
    return split_long_segments(parse_silencedetect(proc.stderr, duration))


def audio_duration_seconds(ffprobe: str, audio_path: Path) -> float:
    proc = subprocess.run(
        [
            ffprobe,
            "-hide_banner",
            "-loglevel",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(audio_path),
        ],
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    if proc.returncode != 0:
        raise ExtractionError(f"FFprobe 音频时长检测失败：{last_line(proc.stderr)}")
    try:
        return float(proc.stdout.strip())
    except ValueError as exc:
        raise ExtractionError("FFprobe 没有返回有效音频时长。") from exc


def parse_silencedetect(stderr: str, duration: float, padding: float = 0.2, min_duration: float = 0.35) -> list[dict]:
    silence_starts = [float(value) for value in re.findall(r"silence_start:\s*([0-9.]+)", stderr)]
    silence_ends = [float(value) for value in re.findall(r"silence_end:\s*([0-9.]+)", stderr)]
    segments: list[dict] = []
    cursor = 0.0
    for start, end in zip(silence_starts, silence_ends):
        if start > cursor:
            add_voice_segment(segments, cursor, start, duration, padding, min_duration)
        cursor = max(cursor, end)
    if cursor < duration:
        add_voice_segment(segments, cursor, duration, duration, padding, min_duration)
    if not segments and duration > 0:
        add_voice_segment(segments, 0.0, duration, duration, padding, 0.0)
    return segments


def add_voice_segment(
    segments: list[dict],
    start: float,
    end: float,
    media_duration: float,
    padding: float,
    min_duration: float,
) -> None:
    padded_start = max(0.0, start - padding)
    padded_end = min(media_duration, end + padding)
    if padded_end - padded_start >= min_duration:
        segments.append({"start": round(padded_start, 3), "end": round(padded_end, 3)})


def split_long_segments(segments: list[dict], max_duration: float = 18.0) -> list[dict]:
    split_segments: list[dict] = []
    for segment in segments:
        start = segment["start"]
        end = segment["end"]
        while end - start > max_duration:
            split_segments.append({"start": round(start, 3), "end": round(start + max_duration, 3)})
            start += max_duration
        split_segments.append({"start": round(start, 3), "end": round(end, 3)})
    return split_segments


def slice_audio(ffmpeg: str, audio_path: Path, segment: dict, output_dir: Path, index: int) -> Path:
    output_path = output_dir / f"chunk-{index:03d}.wav"
    duration = max(0.1, segment["end"] - segment["start"])
    proc = subprocess.run(
        [
            ffmpeg,
            "-y",
            "-ss",
            f"{segment['start']:.3f}",
            "-t",
            f"{duration:.3f}",
            "-i",
            str(audio_path),
            "-c:a",
            "pcm_s16le",
            str(output_path),
        ],
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )
    if proc.returncode != 0:
        raise ExtractionError(f"FFmpeg 音频切片失败：{last_line(proc.stderr)}")
    return output_path


def run_whisper_cpp_chunk(config: dict, chunk_path: Path, output_dir: Path, index: int) -> str:
    output_base = output_dir / f"chunk-{index:03d}-transcript"
    env = os.environ.copy()
    if config.get("lib_dir"):
        env["LD_LIBRARY_PATH"] = f"{config['lib_dir']}:{env.get('LD_LIBRARY_PATH', '')}"
    proc = subprocess.run(
        [
            str(config["cli"]),
            "-m",
            str(config["model"]),
            "-f",
            str(chunk_path),
            "-l",
            "zh",
            "-otxt",
            "-of",
            str(output_base),
            "-nt",
            "-np",
        ],
        text=True,
        capture_output=True,
        timeout=180,
        check=False,
        env=env,
    )
    if proc.returncode != 0:
        raise ExtractionError(f"whisper.cpp 语音识别失败：{last_line(proc.stderr)}")
    output_path = output_base.with_suffix(".txt")
    if output_path.is_file():
        return output_path.read_text(encoding="utf-8", errors="ignore").strip()
    return proc.stdout.strip()


def restore_punctuation(text: str) -> str:
    cleaned = re.sub(r"\s+", "", text.strip())
    cleaned = re.sub(r"([。！？!?]){2,}", r"\1", cleaned)
    if cleaned and cleaned[-1] not in "。！？!?…":
        cleaned += "。"
    return cleaned


def write_srt_file(segments: list[dict]) -> str:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"speech-{uuid4()}.srt"
    output_path = OUTPUT_DIR / filename
    output_path.write_text(format_srt(segments), encoding="utf-8")
    return f"/outputs/{filename}"


def format_srt(segments: list[dict]) -> str:
    blocks = []
    for index, segment in enumerate(segments, start=1):
        blocks.append(
            "\n".join(
                [
                    str(index),
                    f"{format_srt_time(segment['start'])} --> {format_srt_time(segment['end'])}",
                    segment["text"],
                ]
            )
        )
    return "\n\n".join(blocks) + "\n"


def format_srt_time(seconds: float) -> str:
    milliseconds = int(round(seconds * 1000))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def extract_screen_text_with_tesseract(ffmpeg: str, tesseract: str, video_path: Path) -> str | None:
    with tempfile.TemporaryDirectory() as tmp:
        frame_pattern = str(Path(tmp) / "subtitle-%03d.png")
        proc = subprocess.run(
            [
                ffmpeg,
                "-y",
                "-i",
                str(video_path),
                "-vf",
                "fps=1,crop=iw*0.92:ih*0.34:iw*0.04:ih*0.52,scale=iw*2:ih*2,format=gray,eq=contrast=1.6:brightness=0.02",
                "-frames:v",
                "30",
                frame_pattern,
            ],
            text=True,
            capture_output=True,
            timeout=120,
            check=False,
        )
        if proc.returncode != 0:
            raise ExtractionError(f"FFmpeg 抽帧失败：{last_line(proc.stderr)}")
        texts: list[str] = []
        for frame in sorted(Path(tmp).glob("subtitle-*.png")):
            texts.extend(run_tesseract_variants(tesseract, frame))
        return filter_ocr_text("\n".join(texts))


def extract_screen_text_with_rapidocr(ffmpeg: str, config: dict, video_path: Path) -> str | None:
    with tempfile.TemporaryDirectory() as tmp:
        frame_pattern = str(Path(tmp) / "subtitle-%03d.png")
        proc = subprocess.run(
            [
                ffmpeg,
                "-y",
                "-i",
                str(video_path),
                "-vf",
                "fps=1,crop=iw*0.88:ih*0.16:iw*0.06:ih*0.64,"
                "scale=iw*3:ih*3,format=gray,eq=contrast=2.2:brightness=0.02,"
                "unsharp=5:5:1.2",
                "-frames:v",
                "45",
                frame_pattern,
            ],
            text=True,
            capture_output=True,
            timeout=180,
            check=False,
        )
        if proc.returncode != 0:
            raise ExtractionError(f"FFmpeg 抽帧失败：{last_line(proc.stderr)}")
        frames = sorted(Path(tmp).glob("subtitle-*.png"))
        if not frames:
            return None
        ocr = subprocess.run(
            [
                str(config["python"]),
                str(config["helper"]),
                "--json",
                "--min-confidence",
                "0.55",
                *[str(frame) for frame in frames],
            ],
            text=True,
            capture_output=True,
            timeout=240,
            check=False,
        )
        if ocr.returncode != 0:
            raise ExtractionError(f"RapidOCR 识别失败：{last_line(ocr.stderr)}")
        return rapidocr_text_from_json(ocr.stdout)


def rapidocr_text_from_json(output: str) -> str | None:
    try:
        payload = json.loads(output)
    except json.JSONDecodeError as exc:
        raise ExtractionError("RapidOCR 没有返回有效 JSON。") from exc
    texts = [item.get("text", "") for item in payload.get("items", []) if isinstance(item, dict)]
    return filter_ocr_text("\n".join(texts))


def run_tesseract_variants(tesseract: str, frame: Path) -> list[str]:
    outputs: list[str] = []
    for psm in ("6", "7", "11"):
        ocr = subprocess.run(
            [tesseract, str(frame), "stdout", "-l", "chi_sim+eng", "--psm", psm],
            text=True,
            capture_output=True,
            timeout=60,
            check=False,
        )
        if ocr.returncode == 0 and ocr.stdout.strip():
            outputs.append(ocr.stdout.strip())
    return outputs


def extract_network_captions_with_ytdlp(ytdlp: str, url: str) -> str | None:
    with tempfile.TemporaryDirectory() as tmp:
        output_template = str(Path(tmp) / "captions.%(ext)s")
        proc = subprocess.run(
            [
                ytdlp,
                "--skip-download",
                "--write-subs",
                "--write-auto-subs",
                "--sub-langs",
                "zh.*,zh-Hans,zh-CN,en",
                "--sub-format",
                "vtt/srt/best",
                "-o",
                output_template,
                url,
            ],
            text=True,
            capture_output=True,
            timeout=120,
            check=False,
        )
        if proc.returncode != 0:
            raise ExtractionError(f"yt-dlp 字幕提取失败：{last_line(proc.stderr)}")
        caption_files = list(Path(tmp).glob("captions*"))
        texts = [
            normalize_subtitle_text(path.read_text(encoding="utf-8", errors="ignore"))
            for path in caption_files
            if path.is_file()
        ]
        return dedupe_lines("\n".join(texts))


def normalize_subtitle_text(text: str) -> str:
    lines: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.upper() == "WEBVTT":
            continue
        if stripped.isdigit():
            continue
        if "-->" in stripped:
            continue
        stripped = re.sub(r"<[^>]+>", "", stripped)
        stripped = re.sub(r"\{\\.*?\}", "", stripped)
        if stripped:
            lines.append(stripped)
    return dedupe_lines("\n".join(lines))


def dedupe_lines(text: str) -> str:
    seen: set[str] = set()
    lines: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped and stripped not in seen:
            seen.add(stripped)
            lines.append(stripped)
    return "\n".join(lines).strip()


def filter_ocr_text(text: str) -> str:
    lines: list[str] = []
    for line in dedupe_lines(text).splitlines():
        cleaned = re.sub(r"\s+", " ", line).strip()
        cleaned = re.sub(r"[|=_~`^•·]+", "", cleaned).strip()
        if not cleaned:
            continue
        cjk_count = len(re.findall(r"[\u4e00-\u9fff]", cleaned))
        alpha_count = len(re.findall(r"[A-Za-z0-9]", cleaned))
        if cjk_count >= 4:
            lines.append(cleaned)
        elif cjk_count >= 2 and len(cleaned) <= 24:
            lines.append(cleaned)
        elif alpha_count >= 8 and cjk_count > 0:
            lines.append(cleaned)
    return dedupe_lines("\n".join(lines))


def result_from_text(
    text: str,
    provider: str,
    extraction_method: str,
    warnings: list[str],
) -> ExtractionResult:
    compact = text.strip()
    if not compact:
        compact = "未提取到可用文本，请手动补充转写内容。"
    return ExtractionResult(
        raw_text=compact,
        segments=segments_from_text(compact),
        language="zh",
        provider=provider,
        extraction_method=extraction_method,
        warnings=warnings,
    )


def segments_from_text(text: str) -> list[dict]:
    chunks = [chunk for chunk in re.split(r"(?<=[。！？!?])\s*|\n+", text) if chunk.strip()]
    if not chunks:
        chunks = [text]
    segments = []
    start = 0.0
    for chunk in chunks[:20]:
        duration = max(3.0, min(12.0, len(chunk) / 5))
        segments.append({"start": round(start, 2), "end": round(start + duration, 2), "text": chunk})
        start += duration
    return segments


def is_douyin_url(url: str) -> bool:
    host = urlparse(url).netloc.lower()
    return "douyin.com" in host or "iesdouyin.com" in host


def is_fallback_provider(provider: str) -> bool:
    return provider.endswith("-fallback")


def last_line(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return lines[-1] if lines else "unknown error"
