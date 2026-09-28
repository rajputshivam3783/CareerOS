"""V20.4 — Coding interview sandbox abstraction.

Per the spec: "Do not execute untrusted candidate code directly inside
the main application process. Use a secure sandbox abstraction. If a
real sandbox is not available, implement the interface and clearly
mark execution as unavailable rather than executing unsafe code."

This repository has no sandboxed execution environment (no
gVisor/Firecracker/Docker-in-Docker isolation, no separate untrusted-
code worker service — see DEPLOYMENT_GUIDE.md's infrastructure list).
Rather than approximate one with `subprocess`/`exec` in-process (which
would be exactly the unsafe execution the spec prohibits), this module
defines the interface a real sandbox would implement and ships exactly
one concrete implementation: `UnavailableSandbox`, which always
returns a clear "execution unavailable" result and runs nothing.

Wiring in a real sandboxed executor later (e.g. an isolated worker
process/container reached over a queue or internal API) means adding
one new class here that implements `CodeSandbox.run` and pointing
`get_sandbox()` at it — nothing in `question_engine.py`,
`evaluation_engine.py`, or `app/api/interview_ai.py` needs to change,
since they only ever call `get_sandbox().run(...)` and branch on
`SandboxRunResult.status`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class SandboxRunResult:
    status: str  # "unavailable" | "executed" | "error"
    message: str
    stdout: str | None = None
    stderr: str | None = None
    test_results: list[dict] = field(default_factory=list)


class CodeSandbox(ABC):
    @abstractmethod
    def run(self, *, language: str, code: str, test_cases: list[dict] | None = None) -> SandboxRunResult:
        ...


class UnavailableSandbox(CodeSandbox):
    """The only sandbox this version ships. Never executes anything —
    `code` and `language` are accepted only so the interface shape
    matches what a real sandbox would need, and are never passed to
    `exec`, `eval`, `subprocess`, or any interpreter."""

    def run(self, *, language: str, code: str, test_cases: list[dict] | None = None) -> SandboxRunResult:
        return SandboxRunResult(
            status="unavailable",
            message=(
                "Code execution isn't available in this environment. Your solution is still reviewed for "
                "correctness, complexity, and structure by the interview evaluator, exactly like every other "
                "answer, but no test cases were actually run against it."
            ),
        )


def get_sandbox() -> CodeSandbox:
    return UnavailableSandbox()
