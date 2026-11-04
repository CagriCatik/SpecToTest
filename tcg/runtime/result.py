"""Lightweight result object returned by generated test functions."""
from dataclasses import dataclass, field


@dataclass
class TestResult:
    test_id: str
    result: str = 'PASS'
    error: Exception | None = None
    cleanup_errors: list = field(default_factory=list)
    records: list = field(default_factory=list)
    duration: float = 0.0
    specification: str = ''

    def report(self) -> dict:
        data = {
            'test_id': self.test_id,
            'result': self.result,
            'duration_s': round(self.duration, 4),
        }
        if self.specification:
            data['specification'] = self.specification
        if self.records:
            data['steps'] = self.records
        if self.error is not None:
            data['error'] = str(self.error)
        if self.cleanup_errors:
            data['cleanup_errors'] = [str(err) for err in self.cleanup_errors]
        return data

