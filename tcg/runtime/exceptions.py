"""Domain-specific runtime exceptions for test bench operations."""
from tcg.ports.bench import (
    BenchConnectionError,
    BenchError,
    BenchLimitViolationError,
    BenchResourceNotFoundError,
    BenchWriteError,
)

__all__ = [
    'BenchConnectionError',
    'BenchError',
    'BenchLimitViolationError',
    'BenchResourceNotFoundError',
    'BenchWriteError',
]
