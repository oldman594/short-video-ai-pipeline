# RFD 0017: Content-Grounded Analysis

## Context

The structure-analysis panel can become a poor user experience when analysis
falls back to deterministic mock content or when an LLM returns generic planning
language. The visible symptom is unrelated template output such as:

- "hook/problem/framework/close"
- "观众正在犯的错误"
- "给出 3 个可执行步骤"
- "引导收藏、评论或转发"

These phrases do not reflect the actual video content and make the workflow look
untrustworthy even when text extraction has succeeded.

## Decision

Make analysis content-grounded at two layers:

1. Strengthen the DeepSeek analysis prompt.
   - Require every field to use concrete objects, concepts, examples, numbers,
     or paragraph functions from the transcript.
   - Forbid placeholder section names such as `hook/problem/framework/close`.
   - Require structure summaries to include actual transcript concepts.

2. Replace the mock analysis template with transcript-derived fallback analysis.
   - Extract meaningful transcript lines.
   - Detect explicit section markers such as "第一个误解 / 第二个误解".
   - Build structure summaries from the transcript lines instead of a fixed
     content template.
   - Derive audience, category, hook, key points, and risks from content terms.

Normalization also rejects obviously generic analysis text and falls back to the
content-derived analysis for those fields.

The UI displays `analysis.provider` so operators can immediately see whether a
project used DeepSeek or the local content-derived fallback.

## Boundaries

- DeepSeek remains opt-in through `DEEPSEEK_API_KEY`.
- The deterministic fallback is not a replacement for a real model; it is a
  safety net that keeps the UI grounded in the transcript instead of displaying
  unrelated templates.
- OCR errors are not corrected aggressively. The fallback only conservatively
  summarizes visible text.

## Validation

Automated tests cover:

- mock analysis includes concrete transcript content
- generic DeepSeek analysis sections are replaced by transcript-grounded fallback
- existing script-generation and workflow contracts still pass

Validation commands:

- `python3 -m unittest discover -s tests`
- `python3 scripts/check_line_coverage.py`
- `python3 -m compileall app tests scripts`
