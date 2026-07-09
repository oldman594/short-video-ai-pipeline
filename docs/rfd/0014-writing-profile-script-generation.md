# RFD 0014: Writing-Profile Script Generation

## Context

The MVP can already extract transcript text from uploaded media and run content
analysis. The remaining gap in the current chain is that script generation still
looks too generic: it does not explicitly learn the reference video's writing
mode before creating our own video script.

## Decision

Add a deterministic writing-profile step between transcript analysis and script
generation.

The profile records:

- opening pattern
- sentence rhythm
- sentence style
- reusable structure steps
- transition style
- ending pattern
- anti-copy rules

`MockLLMProvider.generate_scripts` now uses this profile to create three
original script drafts that reference the transferable writing mode instead of
copying source lines.

When `DEEPSEEK_API_KEY` is configured, `DeepSeekAnalysisProvider` now attempts a
second JSON chat completion for script generation. The prompt includes the
writing profile, transcript, analysis, and compliance constraints. If the
provider returns malformed data or fails, workflow stability is preserved by
falling back to the deterministic script provider.

## Boundaries

- The feature learns structure, rhythm, and paragraph function only.
- It must not copy the original transcript sentence by sentence.
- It must not clone the original creator's identity, voice, face, catchphrases,
  or distinctive personal expression.
- Human review remains required before avatar rendering.

## Validation

Automated tests cover:

- writing-profile derivation from transcript and analysis fields
- deterministic script generation using the derived profile
- DeepSeek script-generation prompt construction without calling the live API
- normalization of LLM script JSON into the storage contract

Validation commands:

- `python3 -m unittest discover -s tests`
- `python3 scripts/check_line_coverage.py`
- `python3 -m compileall app tests scripts`
