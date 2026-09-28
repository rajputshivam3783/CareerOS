# Skill Graph â€” V20.5

## Model

`skill_relationships(from_skill_id, to_skill_id, relationship_type)` â€”
a directed edge, read as *"from_skill â€”relationship_typeâ†’ to_skill"*.

| Type | Meaning | Example |
|---|---|---|
| `prerequisite` | `from` must be learned before `to` | python â†’ pandas |
| `related` | commonly learned together, no strict order | machine learning â†’ scikit-learn |
| `advanced_version` | `to` is a deeper/harder version of `from` | react â†’ next.js |
| `alternative` | interchangeable choice | aws â†” azure â†” gcp |
| `complementary` | pairs well but isn't required | git â†’ docker |

## Seeded graph (excerpt)

The spec's own worked example, seeded exactly as given:

```
python --prerequisite--> numpy --prerequisite--> pandas
       --prerequisite--> machine learning --prerequisite--> deep learning
```

Full seed set lives in `app/skill_intelligence/catalog.py:RELATIONSHIPS_SEED`
â€” covers web (javascript â†’ typescript/react â†’ next.js), backend/JVM
(java â†’ spring boot), cloud/DevOps (docker â†’ kubernetes â†’ terraform,
aws/azure/gcp as alternatives), databases (sql â†’ postgresql/mysql,
postgresql/mysql/mongodb as alternatives), cybersecurity (network
security â†’ penetration testing/cryptography), and soft skills
(communication â†” public speaking, leadership â†” team management,
problem solving â†” critical thinking).

## Traversal API

`app/skill_intelligence/graph.py`:

- `neighbors(db, skill)` â€” one-hop lookup in every direction:
  prerequisites (incoming), related/advanced/alternative/complementary
  (outgoing).
- `prerequisites_for(db, skill)` â€” full prerequisite chain, nearest-first,
  cycle-safe, depth-bounded (max 6 hops â€” the seeded graph never
  exceeds 4).
- `learning_order(db, skill)` â€” the same chain reversed (furthest
  prerequisite first) with the target skill appended last. This is
  what `app.skill_intelligence.learning_path` uses to sequence a
  learning plan.

All lookups are plain graph queries â€” no AI call, no inference beyond
what's explicitly stored as an edge.

## HTTP

`GET /api/v1/skills/{canonical_or_alias_name}/graph` returns the full
neighbor set plus `learning_order` for one skill. 404 if the name
doesn't resolve in the catalog (see `SKILL_INTELLIGENCE.md` on
normalization â€” no fuzzy matching, no invented skill).

## Extending the graph

Admins add edges via `POST /api/v1/admin/skills/{id}/relationships`
(admin-gated, same guard as every other admin route). There is no
candidate-facing way to add or edit graph edges.

