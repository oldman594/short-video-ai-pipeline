# RFD 0018: Target-Topic Script Generation

## Context

The previous workflow used the reference video title and analysis topic as the
main script topic. This made generated drafts too close to the reference video
theme and weak for the intended use case: learn a successful video's writing
structure, then create a new script about a different user-selected topic.

## Decision

Add an explicit `target_topic` to projects.

The workflow now separates:

- Reference video title/transcript: used for extraction, structure analysis, and
  writing-pattern derivation.
- Target topic: used as the actual subject of generated scripts.
- Notes: used as user-provided material, persona, target audience, and rewrite
  direction for the target topic.

Script generation now receives `target_topic` and `target_notes`.

For DeepSeek-backed generation, the prompt requires the model to:

- Use the reference video only for structure, rhythm, and paragraph function.
- Collect and organize material around the target topic before writing.
- Use user notes as first-priority source material.
- Mark facts that require human verification when the target topic depends on
  current data, policy, pricing, people, medical, legal, financial, or other
  high-risk details.

For local deterministic fallback, the mock script provider builds a conservative
target-topic brief from the selected topic and notes, then applies the extracted
writing profile.

## API or Data Model Impact

`projects` gains:

- `target_topic TEXT`

Create-project payload accepts:

- `target_topic`
- `targetTopic`

If absent, generation falls back to the reference title to preserve existing
behavior.

## UI Impact

The create form adds a "新视频主题" input. Project metadata displays the selected
target topic.

## Boundaries

- The MVP does not perform live web search in this change.
- "Collect information" means organizing user-provided notes plus model/general
  knowledge for the target topic.
- For time-sensitive or high-stakes topics, the generated script must preserve a
  human fact-checking requirement.

## Validation

Automated tests cover:

- API storage of `target_topic`
- workflow script generation using `target_topic` instead of the reference title
- DeepSeek script prompt including target topic and user notes

Validation commands:

- `python3 -m unittest discover -s tests`
- `python3 scripts/check_line_coverage.py`
- `python3 -m compileall app tests scripts`

## Validation Results

- Local workflow smoke test with reference title `杨振宁谈造物主` and target topic
  `AI 编程工具怎么影响普通开发者` reached `ready_for_review`; analysis kept the
  reference topic while the generated script used the target topic.
- `python3 -m unittest discover -s tests` passed with 28 tests.
- `python3 scripts/check_line_coverage.py` passed with 90.6% measured line
  coverage.
- `python3 -m compileall app tests scripts` passed.
