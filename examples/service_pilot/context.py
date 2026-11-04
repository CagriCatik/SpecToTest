"""Execution Context for the RecordStore Software Target System.

Functions as the test bench fixture / execution context providing access to the
RecordStoreService, tracking step logs, and guaranteeing clean isolation between tests.
"""
from decimal import Decimal
from pathlib import Path
import tempfile
import time
from typing import Any

from .service import RecordStoreService


class ServiceExecutionContext:
    """Execution Context providing target service access and execution step recording."""

    BENCH_NAME = "RecordStore Service Bench"

    def __init__(self, config: dict[str, Any] | None = None):
        self.config = config or {}
        self._temp_dir = tempfile.TemporaryDirectory()
        self.storage_path = Path(self._temp_dir.name)
        self.service = RecordStoreService(self.storage_path)
        self.log_entries: list[dict[str, Any]] = []
        self._start_time = time.perf_counter()

    def log_step(self, operation: str, **details: Any) -> None:
        elapsed = time.perf_counter() - self._start_time
        self.log_entries.append({
            'time': f"{elapsed:.3f} s",
            'operation': operation,
            'details': {k: str(v) for k, v in details.items()},
        })

    def now(self) -> Decimal:
        elapsed = time.perf_counter() - self._start_time
        return Decimal(str(round(elapsed, 3)))

    def wait(self, seconds: Decimal) -> None:
        """Simulates or pauses for elapsed time."""
        time.sleep(float(seconds))

    def reset_state(self) -> None:
        """Purges service storage and clears log entries for isolated test execution."""
        self.service.purge_storage()
        self.log_entries.clear()

    def close(self) -> None:
        """Cleans up temporary directory resources."""
        try:
            self._temp_dir.cleanup()
        except OSError:
            pass
