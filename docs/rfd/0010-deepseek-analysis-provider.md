# RFD 0010: DeepSeek Analysis Provider

## Context

The MVP originally used `MockLLMProvider` for both structure analysis and script generation. The next useful production step is to use a real LLM for content structure analysis while keeping the rest of the workflow stable.

## Decision

Add `DeepSeekAnalysisProvider` for the analysis step:

- Enable it only when `DEEPSEEK_API_KEY` is present.
- Call DeepSeek's OpenAI-compatible `/chat/completions` endpoint.
- Request JSON output with `response_format: {"type": "json_object"}`.
- Normalize returned analysis into the existing storage shape.
- Keep script generation delegated to `MockLLMProvider` for now.
- Keep the API key out of repository files; use environment variables.

Supported environment variables:

- `DEEPSEEK_API_KEY`
- `DEEPSEEK_MODEL` defaulting to `deepseek-v4-flash`
- `DEEPSEEK_BASE_URL` defaulting to `https://api.deepseek.com`

## API or Data Model Impact

No schema changes. Analysis records can now have:

- `provider`: `deepseek-analysis-v1`

## Failure Modes

- Missing API key uses the mock provider.
- HTTP failures, malformed DeepSeek responses, and non-JSON model output fail the project with a clear error message.
- Live DeepSeek tests are not run by default to avoid cost and credential coupling.

## Validation Plan

- Unit test provider selection with and without `DEEPSEEK_API_KEY`.
- Unit test DeepSeek response parsing and analysis normalization using fake responses.
- Run unittest, coverage, and compile checks.

## Validation Results

- `python3 -m unittest discover -s tests` passed with 20 tests.
- `python3 scripts/check_line_coverage.py` passed with 91.7% measured line coverage.
- `python3 -m compileall app tests scripts` passed.
- Live DeepSeek API validation was intentionally not run; unit tests use fake responses to avoid committing credentials or incurring API cost.
