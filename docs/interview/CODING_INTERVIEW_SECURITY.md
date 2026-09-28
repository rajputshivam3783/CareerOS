# CODING_INTERVIEW_SECURITY.md â€” V20.4

## The rule

> "Do not execute untrusted candidate code directly inside the main
> application process. Use a secure sandbox abstraction. If a real
> sandbox is not available, implement the interface and clearly mark
> execution as unavailable rather than executing unsafe code."

## What this version ships

`app/interview_ai/sandbox.py` defines `CodeSandbox` (abstract:
`run(language, code, test_cases) -> SandboxRunResult`) and exactly one
concrete implementation, `UnavailableSandbox`.

**`UnavailableSandbox.run` never calls `exec`, `eval`, `subprocess`, or
any interpreter/compiler on the candidate's code.** It accepts
`language`/`code` only to match the interface shape a real sandbox
would need, and always returns:

```python
SandboxRunResult(status="unavailable", message="Code execution isn't available in this environment...")
```

This is a deliberate, honest choice, not a placeholder someone forgot
to fill in: this repository has no isolated execution environment
(no gVisor/Firecracker, no separate untrusted-code worker service, no
Docker-in-Docker) to run arbitrary candidate-submitted code in.
Approximating one with `subprocess`/`exec` inside the FastAPI process
would be exactly the unsafe execution the spec prohibits â€” so this
version doesn't attempt it.

## What the candidate actually gets

A coding-interview submission (`POST /interview/sessions/{id}/coding-
submit`) is stored (`MockInterviewCodingSubmission`, `sandbox_status=
"unavailable"`) and then evaluated the same way every other answer is
â€” as text, through `evaluation_engine.evaluate_answer` (correctness,
technical depth, complexity discussion, structure) â€” when submitted as
the answer to the current question via `POST .../answer`. No test
cases are actually run against it; the evaluation is a static/AI
review, honestly labeled as such in the sandbox's own `message`.

## Wiring in a real sandbox later

`get_sandbox()` is the single call site everything else in the engine
uses (`app/api/interview_ai.py`'s `submit_code`). Adding real
execution means:

1. Writing a new class implementing `CodeSandbox.run` that talks to an
   actually-isolated executor (e.g. a separate worker process/container
   reached over a queue or internal API â€” not in-process).
2. Pointing `get_sandbox()` at it.

Nothing in `question_engine.py`, `evaluation_engine.py`, or the API
layer needs to change â€” they only branch on `SandboxRunResult.status`
("unavailable" / "executed" / "error"), never on which class produced it.

## Coding sandbox security tests

`tests/test_v20_4_ai_interview.py::test_sandbox_is_always_unavailable_and_runs_nothing`
submits code containing `os.system('rm -rf /')` directly to
`get_sandbox().run(...)` and asserts: status is `"unavailable"`, no
`stdout`/`stderr` are populated (nothing ran), and the message is
honest about unavailability.
`test_coding_interview_submission_reports_sandbox_unavailable` and
`test_coding_submit_rejected_for_non_coding_session` cover the same
via the real HTTP API.

