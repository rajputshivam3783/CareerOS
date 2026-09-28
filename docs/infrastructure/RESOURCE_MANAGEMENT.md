# Resource Management â€” V20.5 (Phase 2)

## Rule: never fabricate a resource

Every `LearningResource` row is entered by an admin. Nothing in this
codebase generates, infers, or invents a course/book/URL. This is the
same posture as `AI_SAFETY.md`'s "never fabricate resource URLs" rule
â€” `app.skill_intelligence.resources` only ever *reads* rows an admin
put there.

## Visibility gate

A candidate only ever sees a resource where **both**:
- `status == "published"` (not `draft` or `archived`)
- `is_verified == true`

`app.skill_intelligence.resources.published_for_skill()` /
`best_for_skill()` enforce this filter â€” there is no candidate-facing
path that bypasses it. A skill with zero verified resources returns an
empty list, never a placeholder.

## Fields

| Field | Notes |
|---|---|
| `title`, `provider`, `url` | `url` is optional â€” some resource types (e.g. an internal project brief) may not have one |
| `resource_type` | course / book / documentation / article / video / tutorial / practice_platform / project / certification |
| `skill_id` | which canonical skill this teaches |
| `difficulty` | beginner / intermediate / advanced / expert |
| `duration_minutes`, `language`, `is_free`, `rating` | metadata for candidate-facing sorting/filtering |
| `status` | draft â†’ published â†’ archived |
| `is_verified` | separate from `status` â€” a published-but-unverified resource still doesn't reach candidates |

## Admin API (all under `/api/v1`, admin-gated)

| Method | Path | Purpose |
|---|---|---|
| GET | `/admin/resources?skill_id=` | list (optionally filtered) |
| POST | `/admin/resources` | create â€” requires an existing skill (`skill_canonical_name`) |
| PUT | `/admin/resources/{id}` | partial update (any subset of fields) |

Candidate-facing read: `GET /api/v1/resources?skill=<name>` (resolves
aliases via the normalization layer â€” `js`, `javascript`, etc. all
work).

## Why `status` and `is_verified` are separate

An admin can stage a resource (`draft`) while still researching it, or
retire one (`archived`) that's gone stale, without losing the
verification signal. `is_verified` is the harm-prevention gate;
`status` is workflow. Both must be true for a resource to reach a
learning path.

