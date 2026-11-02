"""Execution support for generated tests: step protocol, FAIL/ERROR distinction, cleanup.

Bench-agnostic. Imports neither Excel, nor profiles, nor the dummy bench.
"""
from dataclasses import dataclass
from decimal import Decimal


class CheckFailed(Exception):
    """A check observed a different state than specified (result FAIL).

    Every other exception raised by an operation is a technical error (ERROR).
    """


@dataclass(frozen=True)
class StepInfo:
    execution_id: str
    phase: str
    test_step: int | None
    step_name: str | None
    expectation_order: int | None
    source: str  # human-readable source file and position
    mapping_id: str
    description: str


class TestFailure(ExceptionGroup):
    """Raised by TestLog.finish(); carries the complete log in `.log`."""

    def derive(self, excs):
        return ExceptionGroup(self.message, excs)


def _text(value):
    if isinstance(value, Decimal):
        return format(value.normalize(), 'f')
    return str(value)


class TestLog:
    """Executes steps in the order the generated code calls them and records results."""

    __test__ = False  # not a unittest/pytest test class

    def __init__(self, test_id, name, objective, profile_id, steps, bench):
        self.test_id = test_id
        self.name = name
        self.objective = objective
        self.profile_id = profile_id
        self.steps = {info.execution_id: info for info in steps}
        if len(self.steps) != len(steps):
            raise ValueError('duplicate execution IDs in STEPS')
        self.bench = bench
        self.records = []
        self.errors = []

    def step(self, execution_id, operation, **arguments):
        """Run a non-cleanup step; re-raises so that the remaining test steps are skipped."""
        self._execute(self._info(execution_id, cleanup=False), operation, arguments)

    def cleanup(self, execution_id, operation, **arguments):
        """Run a cleanup step; never raises an Exception so that later cleanup steps still run."""
        try:
            self._execute(self._info(execution_id, cleanup=True), operation, arguments)
        except Exception as error:
            self._remember(error)

    def abort(self, error):
        """Called by the generated `except` block after a step raised."""
        self._remember(error)

    def _info(self, execution_id, cleanup):
        info = self.steps.get(execution_id)
        if info is None or (info.phase == 'CLEANUP') != cleanup:
            raise RuntimeError(f'{execution_id} is not a {"cleanup" if cleanup else "test"} execution of {self.test_id}')
        if any(record['execution_id'] == execution_id for record in self.records):
            raise RuntimeError(f'{execution_id} executed twice')
        return info

    def _execute(self, info, operation, arguments):
        record = {
            'execution_id': info.execution_id,
            'phase': info.phase,
            'test_step': info.test_step,
            'step_name': info.step_name,
            'expectation_order': info.expectation_order,
            'source': info.source,
            'mapping': info.mapping_id,
            'operation': operation.__name__,
            'arguments': {name: _text(value) for name, value in arguments.items()},
        }
        try:
            operation(self.bench, **arguments)
        except CheckFailed as error:
            record.update(result='FAIL', detail=str(error))
            self._remember(error)
            raise
        except Exception as error:
            record.update(result='ERROR', detail=f'{type(error).__name__}: {error}')
            self._remember(error)
            raise
        else:
            record['result'] = 'PASS'
        finally:
            record['bench_time_s'] = _text(self.bench.now())
            self.records.append(record)

    def _remember(self, error):
        if not any(error is known for known in self.errors):
            self.errors.append(error)

    @property
    def not_run(self):
        done = {record['execution_id'] for record in self.records}
        return [execution_id for execution_id in self.steps if execution_id not in done]

    @property
    def result(self):
        if any(not isinstance(error, CheckFailed) for error in self.errors):
            return 'ERROR'
        if self.errors:
            return 'FAIL'
        return 'PASS'

    def report(self):
        return {
            'test_id': self.test_id,
            'name': self.name,
            'objective': self.objective,
            'profile_id': self.profile_id,
            'result': self.result,
            'steps': self.records,
            'not_run': self.not_run,
        }

    def finish(self):
        if not self.errors and self.not_run:
            self.errors.append(RuntimeError(f'steps never executed: {self.not_run}'))
        if self.errors:
            failure = TestFailure(f'{self.test_id}: {self.result}', self.errors)
            failure.log = self
            raise failure
        return self
