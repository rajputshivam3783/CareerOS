# AI Cost Report â€” V20.6

## Method

Code review of every cost-control mechanism already in the V20.1
gateway, plus confirmation nothing in V20.2 bypasses it. No live
provider spend data exists in this environment (no API keys
configured) â€” actual dollar costs are **NOT MEASURED**; this report
covers the control mechanisms that bound cost, which is what's
actually auditable without live billing data.

## Cost controls confirmed present and functioning

- **Token limits per request**: every `completion_service.generate()`
  call site passes an explicit `max_tokens` (700 for interview
  evaluation, 1024 default elsewhere per `ai_default_max_tokens`) â€”
  grepped every call site, none omits it or passes an unbounded value.
- **Context token budget enforced**, not just configured â€”
  `context_builder.build_context()` actually trims to
  `ai_max_context_tokens`, verified by reading the implementation (see
  `AI_PERFORMANCE_REPORT.md`).
- **Conversation history capped + summarized** â€” old messages are
  rolled into a summary past `ai_conversation_summary_trigger` (30)
  rather than being resent in full on every turn, which would grow
  per-conversation cost unboundedly over a long chat.
- **Rate limiting on every AI-triggering endpoint** â€” bounds the
  number of AI calls any single user can trigger per minute, across
  all four modules (resume suggestions, copilot messages, interview
  answers, etc.). This is the primary defense against "accidental
  infinite AI calls" (e.g., a buggy frontend retry loop, or a user
  rapidly clicking a generate button).
- **Retry is bounded and does not compound with fallback into an
  explosion**: `ai_max_retries` retries against the primary, then **one**
  fallback hop â€” never a retry loop against the fallback too, and
  never a cascade through every registered provider. Verified this
  release via `test_retry_count_matches_configured_max_retries` (exact
  call count) and `test_fallback_never_cascades_past_the_single_configured_fallback`.
- **A misconfigured/unavailable provider is never retried** â€”
  `ProviderNotConfiguredError` short-circuits immediately instead of
  wasting `ai_max_retries` attempts against a key that can't possibly
  succeed. Verified via `test_not_configured_provider_is_not_retried`.
- **Usage tracking is universal, not sampled** â€” `observability.record_event()`
  is called on every single `completion_service.generate()` invocation,
  success or failure, recording provider/model/tokens/cost estimate.
  Nothing bypasses this, since every module calls through
  `completion_service` rather than a provider directly (see
  `AI_PRODUCTION_ARCHITECTURE.md`).
- **Cost estimation exists per-call** (`token_counter.estimate_cost_usd`)
  and is stored on every usage log row, giving admins a real (if
  estimate-based, not billing-reconciled) cost signal via
  `GET /ai/usage`.

## Duplicate-request prevention

- **No duplicate AI provider logic** exists to accidentally double-bill
  a single logical operation â€” confirmed in this audit that every
  module routes through the one `completion_service`/`provider_router`
  pair (see `AI_PRODUCTION_ARCHITECTURE.md`'s "no duplication" table).
- **Resume analysis is cached, not recomputed per request** â€”
  `resume_ai.cache` / `ResumeAnalysis` (one row per user, replaced on
  recompute) means viewing your resume analysis repeatedly doesn't
  trigger repeated AI calls; `GET /resume-ai/analysis` only recomputes
  when `refresh=true` is explicitly passed.
- **Prompt reuse**: prompt templates are stored once in the Prompt
  Registry (`ai_prompt_templates`, V20.1) and referenced by key, not
  duplicated per call site.

## Not measured (honest gap)

- Actual $ spend against any real provider (no live credentials)
- Whether `token_counter`'s cost-per-token estimates are still
  accurate against current vendor pricing (estimates are static
  constants in code; vendor pricing changes over time and this audit
  did not cross-check current published rates)
- Real-world cache hit rate for resume analysis under production
  traffic patterns

## Recommendation before production launch

Cross-check `token_counter.py`'s per-model cost constants against each
vendor's currently published pricing before relying on
`GET /ai/usage`'s cost figures for budgeting â€” this audit confirmed
the estimation *mechanism* works, not that the current dollar
constants are up to date.

