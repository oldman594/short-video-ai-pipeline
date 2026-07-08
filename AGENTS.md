# Agent Rules

## Source of Truth

- Repository files MUST be the source of truth.
- `README.md`, `docs/PRD.md`, and `docs/TECH_ARCHITECTURE.md` define the current product scope, architecture intent, MVP boundaries, and compliance constraints.
- Agents MUST gather local evidence first before designing or changing behavior.
- Agents MUST NOT rely on chat memory, undocumented assumptions, or platform behavior that is not captured in this repository.
- If future modules add `diag/` artifacts, those artifacts MUST be treated as repository ground truth for design intent, coverage expectations, and review state.
- If a new implementation conflicts with existing documentation, update the relevant documentation in the same atomic change or explicitly record why no documentation change is required.

## Product Boundaries

- The product is a short-video content analysis and original re-creation workflow, not a content scraping, copying, or account automation tool.
- Agents MUST preserve the MVP boundary of link import or video upload unless the user explicitly changes scope.
- Agents MUST NOT implement unofficial scraping, reverse-engineered platform APIs, collection-folder monitoring, account automation, or bypasses for Douyin or any other platform.
- Agents MUST NOT implement cloning of an original creator's voice, face, identity, or unique signature expression.
- Generated content workflows MUST preserve human review before export or publishing.
- Any publishing integration MUST use documented official APIs or manual export flows.

## Workflow

- Non-trivial work MUST create or update a local design note under `docs/rfd/`.
- Substantial product, architecture, API, database, workflow, provider, prompt, or compliance changes MUST update `docs/PRD.md`, `docs/TECH_ARCHITECTURE.md`, or a module-local `docs/rfd/` document as appropriate.
- Agents MUST design APIs, data boundaries, invariants, failure modes, acceptance criteria, and validation strategy before implementation.
- Agents MUST keep changes scoped to the requested behavior and avoid unrelated refactors.
- Agents MUST NOT format unrelated files.
- Agents MUST NOT rewrite generated media, fixtures, lockfiles, or large assets unless the task requires it.
- After execution starts, agents SHOULD continue autonomously until the task is implemented, validated, and summarized.
- Agents SHOULD pause only for blockers, unresolved ambiguity, credential requirements, cost-incurring third-party calls, or scope-changing decisions.

## Execution Model

- The task-receiving agent acts as orchestrator and final reviewer.
- Non-trivial work SHOULD be split into bounded research, implementation, review, and testing steps.
- If multi-agent tooling is available and the task is large enough, research, implementation, review, and testing SHOULD be separated.
- Validation gaps, intentional deviations, third-party service limitations, and untested assumptions MUST be recorded in the relevant `docs/rfd/` entry.
- Every completed atomic change SHOULD be committed immediately when the project is inside a git repository. If the project is not a git repository, agents MUST state that commits were not possible.

## Architecture Rules

- Long-running work MUST be modeled as asynchronous jobs, not blocking request handlers.
- API code MUST not directly bind business logic to a single third-party provider.
- Third-party integrations MUST go through provider adapters such as ASR, LLM, AvatarVideo, Storage, and Publish providers.
- Provider interfaces MUST define request shape, response shape, retry behavior, timeout behavior, error mapping, and idempotency expectations.
- Prompt templates MUST be versioned or otherwise traceable.
- LLM outputs intended for downstream processing SHOULD use structured schemas.
- Media files MUST be stored through a storage abstraction once the project has one.
- User-visible project states and job states MUST be explicit and recoverable.

## Compliance and Safety

- Any feature using external video content MUST respect platform access rules and user authorization.
- ASR transcripts of source videos are analysis inputs, not publishable final content.
- Script generation MUST transform structure and ideas into original expression rather than copying source text.
- Risk checks SHOULD cover textual similarity, unique phrases, original creator references, regulated topics, sensitive claims, and platform policy concerns.
- Medical, legal, financial, political, and other high-risk content MUST include review warnings and conservative generation behavior.
- Agents MUST not add functionality that automatically publishes AI-generated content without a user approval step.

## Build and Environment

- `just` SHOULD be the primary entrypoint for environment, bootstrap, build, and test workflows once a `justfile` exists.
- If a matching `just` target exists, agents MUST use it instead of ad hoc shell commands.
- If no `justfile` exists, agents MUST use the repository's documented package-manager or framework-native commands.
- When bootstrap is required and `just build` exists, agents MUST run `just build` first.
- After relevant code changes, agents MUST run `just test` when available, or the narrowest documented test command that validates the change.
- Validation scope and remaining gaps MUST be recorded in the relevant `docs/rfd/` entry for non-trivial work.

## Testing

- Tests MUST focus on observable behavior, state transitions, API contracts, provider adapter behavior, and failure recovery.
- Measured Python application code MUST maintain at least 90% line coverage.
- After relevant code changes, agents MUST run the repository coverage command when available and treat coverage below 90% as a validation failure.
- Tests involving third-party services MUST use fakes, mocks, fixtures, or recorded contract responses unless the task explicitly requires live integration testing.
- Tests for async jobs MUST cover success, retryable failure, non-retryable failure, and idempotent re-run behavior where applicable.
- Each new non-trivial test MUST include comments explaining the test objective, construction method, input data, and expected behavior.
- Snapshot or fixture updates MUST be intentional and explained.

## Documentation

- Documentation updates MUST be made alongside behavior changes when user-facing workflows, architecture, API contracts, database schema, provider behavior, or compliance boundaries change.
- `docs/rfd/` documents SHOULD use a concise structure:
  - Context
  - Decision
  - API or data model impact
  - Failure modes
  - Validation plan
  - Validation results
  - Open questions
- Public-facing descriptions MUST avoid implying guaranteed virality, unauthorized automation, or platform bypasses.

## Enforcement

- If a rule can be checked mechanically, the project SHOULD enforce it with linting, tests, templates, CI, or pre-commit hooks.
- Agents SHOULD add automation for repeated checks when doing so is small, local, and directly related to the task.
