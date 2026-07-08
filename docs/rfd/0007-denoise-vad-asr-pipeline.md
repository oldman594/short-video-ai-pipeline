# RFD 0007: Denoise, VAD, Chunked ASR, Timestamp Alignment

## Context

Whole-file `whisper.cpp` transcription produced noisy text on the local `vision/` sample. The desired server-side speech pipeline is:

```text
video -> extract audio -> denoise -> VAD -> chunks -> ASR
      -> timestamp alignment -> punctuation restoration -> subtitle file
```

The server has FFmpeg filters for denoising, normalization, and silence detection, plus system `whisper-cli`.

## Decision

Replace direct whole-file `whisper.cpp` speech extraction with a staged local ASR pipeline:

- Extract 16 kHz mono WAV from media.
- Apply high-pass, low-pass, FFT denoise, dynamic normalization, and loudness normalization.
- Use FFmpeg `silencedetect` as VAD.
- Slice speech regions with small padding.
- Run `whisper-cli` per speech chunk.
- Align each chunk result back to the original media timeline.
- Restore simple Chinese punctuation.
- Write an SRT subtitle file under `data/outputs/`.

The transcript object gains `subtitle_file_url` when a generated subtitle file exists.

## API or Data Model Impact

`transcripts` adds:

- `subtitle_file_url TEXT`

Project detail responses include `transcript.subtitle_file_url`.

## Failure Modes

- VAD based on silence detection may under-segment when background music is continuous.
- Tiny whisper.cpp model still limits recognition quality; larger models remain recommended.
- Punctuation restoration is heuristic.

## Validation Plan

- Unit tests for VAD parsing, segment splitting, punctuation, and SRT formatting.
- Local test against `vision/61354d2054ca8878ffe02059f360e7fe.mp4`.
- Run unittest, coverage, and compile checks.

## Validation Results

- `python3 scripts/extract_text_local.py vision/61354d2054ca8878ffe02059f360e7fe.mp4 --mode speech --json` returned timestamped segments and `subtitle_file_url`.
- `python3 scripts/extract_text_local.py vision/61354d2054ca8878ffe02059f360e7fe.mp4 --mode auto` returned combined ASR/OCR text.
- `python3 -m unittest discover -s tests` passed with 16 tests.
- `python3 scripts/check_line_coverage.py` passed with 91.7% measured line coverage.
- `python3 -m compileall app tests scripts` passed.
