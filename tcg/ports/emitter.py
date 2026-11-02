"""Hexagonal Architecture: Driven Port (Secondary Interface) for Test Code Emitters."""
from typing import Any, Protocol, Sequence, runtime_checkable


@runtime_checkable
class CodeEmitterPort(Protocol):
    """Driven port for emitting executable test scripts from compiled test case models."""

    def emit(
        self,
        cases: Sequence[Any],
        registry: dict[str, Any],
        runner_module: str = 'tcg.runtime.runner',
    ) -> str:
        """Render compiled test cases into executable script source code."""
        ...

