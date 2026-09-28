"""V20.3 — AI Career Copilot.

Built on the V20.1 AI Gateway (`app.ai`, reused as-is — conversation
storage, provider routing, usage logging all come from there, nothing
duplicated) and V20.2 Resume Intelligence (`app.resume_ai`, reused for
resume-grounded scoring/matching wherever a resume exists). Also reuses
the V6 deterministic job-matching engine (`app.services.career`) and
the V5 government eligibility engine (`app.services.eligibility`) —
this package does not implement a second matching or eligibility
engine anywhere.

Same hard boundary as `app.resume_ai`: **deterministic logic decides,
AI only narrates.** Job recommendations, the career roadmap, the
action plan, and government eligibility guidance are all composed by
plain Python from already-computed, already-authorized data — a model
is never asked "is this candidate eligible" or "what jobs should this
person get." The only genuinely generative surface is the chat itself
(`assistant.py`), and every chat turn is grounded in a context block
built by `context_engine.py` that explicitly separates known,
inferred, recommended, and unknown information — see
CAREER_CONTEXT_ENGINE.md and AI_SAFETY.md.

Layout:
    context_engine.py       Assembles a user's authorized CareerOS data
                            into a structured, privacy-scoped context —
                            the single source of truth every other
                            module and the chat prompt read from.
    career_preferences.py   CRUD for the candidate-defined career
                            profile (target role, industry, etc.).
    job_recommendations.py  Thin wrapper around the existing V6
                            match_score engine — no new scoring logic.
    roadmap.py               Deterministic career roadmap builder.
    action_plan.py           Deterministic, persisted action items.
    government_guidance.py   Grounded government-job Q&A on top of the
                            existing V5 eligibility() engine.
    system_prompt.py         The grounding system prompt + prompt-
                            injection defense for untrusted content.
    assistant.py              Chat turn orchestrator: context ->
                            prompt -> app.ai.completion_service.

Out of scope for this pass (V20.4+, per ROADMAP.md): AI Interview
System, AI Learning Platform, AI Mock Interviews, Advanced Career
Assessment.
"""
