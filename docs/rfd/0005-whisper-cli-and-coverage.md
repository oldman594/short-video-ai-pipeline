# RFD 0005: System Whisper CLI and Line Coverage Gate

## Context

After installing `whisper.cpp`, the server has `/usr/bin/whisper-cli`. Manual testing with the existing tiny model under `.local/models/ggml-tiny.bin` successfully transcribed the `vision/` test video. The application still preferred the previously unpacked local `whisper-cli`, which fails because its Debian ggml backend path is not registered correctly outside a system install.

`AGENTS.md` did not define a concrete line coverage threshold.

## Decision

- Prefer the system `whisper-cli` when it is installed.
- Use `.local/models/ggml-tiny.bin` as the default local whisper.cpp model.
- Keep the unpacked local whisper.cpp as a last fallback only.
- Add a required 90% line coverage threshold to `AGENTS.md`.
- Add a dependency-free coverage checker using Python's standard `trace` module.

## API or Data Model Impact

No API or database schema changes.

## Failure Modes

- If `whisper-cli` is installed but no model exists, speech extraction still falls back.
- Tiny model accuracy is limited; better extraction needs a larger model.
- The standard-library coverage checker is intentionally simple and does not replace a full coverage.py setup.

## Validation Plan

- Run local extraction for the `vision/` video in `speech` mode.
- Run unit tests.
- Run compile checks.
- Run the coverage checker and enforce at least 90% line coverage for measured app modules.

## Validation Results

- Manual `whisper-cli` test with `.local/models/ggml-tiny.bin` succeeded on `vision/61354d2054ca8878ffe02059f360e7fe.mp4`.
- `python3 scripts/extract_text_local.py vision/61354d2054ca8878ffe02059f360e7fe.mp4 --mode speech` returned `provider: whisper.cpp`.
- `python3 -m unittest discover -s tests` passed with 13 tests.
- `python3 scripts/check_line_coverage.py` passed with 91.6% total measured line coverage.
- `python3 -m compileall app tests scripts` passed.
