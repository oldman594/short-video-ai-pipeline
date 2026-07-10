# RFD 0019: Conditional Structure Transfer

## Context

Target-topic script generation exposed a product issue: the generated draft could
force the reference video's structure onto an unrelated topic. For example, a
physics/philosophy reference video produced a pet-introduction script that still
mentioned the reference structure and backend planning text.

This is wrong. The reference video should be a candidate source of structure,
not a mandatory template.

## Decision

Add a structure-transfer suitability step before script generation.

Generation now chooses one of two modes:

- `transfer_structure`: reference topic and target topic share a coarse domain or
  meaningful keywords, so paragraph function and progression can be migrated.
- `target_native`: topics are unrelated, so the script uses the target topic's
  natural structure and only borrows broad rhythm such as short sentences or a
  strong opening.

Generated script text must not expose backend planning labels such as:

- `写作模式`
- `目标主题素材`
- `参考视频`
- `结构步骤`

DeepSeek prompts now explicitly instruct the model to make the same suitability
decision and avoid forcing the reference structure when it does not fit.

## Boundaries

- The suitability check is conservative and heuristic in local fallback mode.
- DeepSeek can make a better semantic judgment when configured.
- The target topic remains the source of script content; the reference video only
  contributes structure when appropriate.

## Validation

Automated tests cover:

- target-topic scripts include the selected topic
- target-topic scripts do not expose backend planning labels
- DeepSeek script prompts include a structure suitability instruction
- workflow output does not include backend planning labels

Validation commands:

- `python3 -m unittest discover -s tests`
- `python3 scripts/check_line_coverage.py`
- `python3 -m compileall app tests scripts`

## Validation Results

- Local generation with a physics reference video and target topic `介绍小动物比如小狗`
  produced a dog-focused script using the target topic's own introduction
  structure, without backend planning labels.
- `python3 -m unittest discover -s tests` passed with 28 tests.
- `python3 scripts/check_line_coverage.py` passed with 90.8% measured line
  coverage.
- `python3 -m compileall app tests scripts` passed.
