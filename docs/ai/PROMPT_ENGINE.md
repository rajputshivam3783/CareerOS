# CareerOS â€” Prompt Engine

`app/ai/prompt_service.py` â€” a versioned, admin-editable registry of
prompt templates, backed by the `ai_prompt_templates` table.

## Concepts

- **Key** â€” a stable identifier a caller looks up by, e.g.
  `"conversation.summarize"`. Convention: `<area>.<purpose>`, lowercase,
  dot-separated (matches the `operation` label convention used in
  `AIUsageLog`).
- **Version** â€” templates are never edited in place. Registering a new
  template for an existing key creates a new row at `version = previous + 1`
  and deactivates the previous version (`active = false`) â€” the old
  version stays in the table for history/audit, it's just no longer
  looked up by `render()`.
- **Variables** â€” `{name}`-style placeholders, substituted with
  `str.format`. Declared explicitly (a JSON list stored in the
  `variables` column) or, if omitted, inferred from the template text
  itself.
- **Active template** â€” for a given key, the highest-`version` row with
  `active = true`. This is what `render()` and `get_active_template()`
  return.

## Usage

```python
from app.ai import prompt_service

prompt = prompt_service.render(
    db, "conversation.summarize",
    {"conversation_text": "..."},
)
```

`render()` raises:
- `PromptNotFoundError` â€” no active template exists for that key.
- `PromptValidationError` â€” a variable the template declares (or, if
  undeclared, that appears in the template text as a `{placeholder}`)
  wasn't supplied.

Validation happens **before** substitution, so a missing variable
fails with a clear message rather than sending a model a prompt with a
literal, un-substituted `{variable_name}` still in it.

## Default templates

Seeded once, at process startup (`app/main.py`'s lifespan, right after
`seed_default_templates` for notifications), idempotently â€” a key that
already has any row (even an admin-edited one) is never overwritten:

| Key | Purpose |
|---|---|
| `system.default_assistant` | Fallback system prompt when a caller doesn't supply its own. |
| `conversation.summarize` | Used by `conversation_manager.maybe_summarize` to compress old turns. |

Add a new built-in default by adding an entry to
`prompt_service.DEFAULT_PROMPTS` â€” it will be seeded on the next
process start for any deployment that doesn't already have a row for
that key.

## Registering / editing templates

Via the admin API (`POST /api/v1/ai/prompts`, admin-only) or directly:

```python
prompt_service.register_template(
    db, key="resume_ai.rewrite_bullet",
    template="Rewrite this resume bullet to be more impact-oriented: {bullet}",
    variables=["bullet"],
    description="Used by Resume AI's bullet rewrite feature.",
)
```

This is the same function the admin API endpoint calls â€” the AI Admin
dashboard's "Prompt registry" tab is a thin UI over
`list_templates` / `register_template`.

## Design notes

- **Why DB-backed, not just Python constants?** So a prompt can be
  tuned (tone, phrasing, added guardrail language) without a deploy â€”
  the same reasoning as
  `app/services/notification_templates.py` for notification copy.
- **Why version instead of overwrite?** So a bad edit is a one-click
  rollback (register the previous text again as a new version) with a
  full audit trail of what a prompt said at any point in time, rather
  than a silent, unrecoverable overwrite.
- **Why `str.format` instead of a templating engine (Jinja, etc.)?**
  Prompt templates here are flat variable substitution, not control
  flow â€” pulling in a templating engine for `{variable}` substitution
  would be a dependency without a matching need. If a future feature
  needs loops/conditionals in prompts, that's a deliberate, scoped
  addition to make then, not something to build speculatively now.

