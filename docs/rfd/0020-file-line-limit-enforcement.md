# RFD 0020: File Line Limit Enforcement

## Context

The repository now needs a clear file-size boundary: committed text files should not exceed 400 lines. The goal is to keep source files, tests, and documents small enough to review, split, and maintain.

Several existing tracked text files already exceed 400 lines. Enforcing a full-repository failure immediately would block unrelated commits until those legacy files are split.

## Decision

Add `scripts/check_file_line_limits.py` as the mechanical guard for the rule.

The default commit-time mode checks staged added, copied, renamed, or modified files by reading their index contents. Any staged UTF-8 text file above 400 lines fails the check and must be split before commit. Binary content is skipped.

Add `scripts/install_git_hooks.sh` to install a local `.git/hooks/pre-commit` hook that runs:

```bash
python3 scripts/check_file_line_limits.py --staged
```

The script also supports `--all` for future cleanup work, but `--all` is not wired into the default validation path yet because historical tracked files currently exceed the new limit.

## API or Data Model Impact

No runtime API, workflow, storage, or provider data model changes.

## Failure Modes

- A staged text file above 400 lines fails the pre-commit hook and prints the file path plus observed line count.
- Binary files and non-UTF-8 artifacts are ignored by this rule.
- Developers who have not installed the local hook can still run the check manually.

## Validation Plan

- Unit test the text violation path.
- Unit test binary content skipping.
- Unit test UTF-8 Chinese text handling.
- Run the repository unit tests, coverage command, compile check, and staged line-limit check.

## Validation Results

- `python3 -m unittest tests.test_file_line_limits` passed.
- `python3 -m unittest discover -s tests` passed: 31 tests.
- `python3 scripts/check_line_coverage.py` passed: total measured line coverage 90.8%.
- `python3 -m compileall app tests scripts` passed.
- `python3 scripts/check_file_line_limits.py --staged` passed before staging these changes.
- `scripts/install_git_hooks.sh` installed the local pre-commit hook.

## Open Questions

- Existing long tracked files should be split in later focused changes before making `--all` a required repository-wide check.
