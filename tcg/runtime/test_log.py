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
        text = format(value, 'f')
        if '.' in text:
            text = text.rstrip('0').rstrip('.')
        return '0' if text in {'', '-0'} else text
    return str(value)


class TestLog:
    """Executes steps in the order the generated code calls them and records results."""

    __test__ = False  # not a unittest/pytest test class

    def __init__(self, test_id, *args, **kwargs):
        if len(args) == 5:
            # Legacy: TestLog(test_id, name, objective, profile_id, steps, bench)
            name, objective, profile_id, steps, bench = args
            self.test_id = test_id
            self.name = name
            self.objective = objective
            self.profile_id = profile_id
            self.steps = {info.execution_id: info for info in steps} if steps else None
            self.planned = [info.execution_id for info in steps] if steps else []
            self.bench = bench
        elif len(args) == 1:
            # Clean: TestLog(test_id, bench, planned=[...])
            self.test_id = test_id
            self.bench = args[0]
            self.name = kwargs.get('name', test_id)
            self.objective = kwargs.get('objective')
            self.profile_id = kwargs.get('profile_id')
            self.steps = kwargs.get('steps')
            if self.steps:
                self.planned = [info.execution_id for info in self.steps]
            else:
                self.planned = list(kwargs.get('planned', kwargs.get('planned_steps', [])))
        else:
            self.test_id = test_id
            self.bench = kwargs.get('bench')
            self.name = kwargs.get('name', test_id)
            self.objective = kwargs.get('objective')
            self.profile_id = kwargs.get('profile_id')
            self.steps = kwargs.get('steps')
            self.planned = list(kwargs.get('planned', kwargs.get('planned_steps', [])))

        self.records = []
        self.errors = []

    def step(self, execution_id, operation, **arguments):
        """Run a non-cleanup step; re-raises so that the remaining test steps are skipped."""
        self._execute(execution_id, False, operation, arguments)

    def cleanup(self, execution_id, operation, **arguments):
        """Run a cleanup step; never raises an Exception so that later cleanup steps still run."""
        try:
            self._execute(execution_id, True, operation, arguments)
        except Exception as error:
            self._remember(error)

    def abort(self, error):
        """Called by the generated `except` block after a step raised."""
        self._remember(error)

    def _execute(self, execution_id, cleanup, operation, arguments):
        if any(record['execution_id'] == execution_id for record in self.records):
            raise RuntimeError(f'{execution_id} executed twice')

        phase = 'CLEANUP' if cleanup else 'ACTION'
        record = {
            'execution_id': execution_id,
            'phase': phase,
            'operation': operation.__name__,
            'arguments': {name: _text(value) for name, value in arguments.items()},
        }
        if self.steps:
            base_id = execution_id.split('[')[0]
            info = self.steps.get(execution_id) or self.steps.get(base_id)
            if info:
                record.update({
                    'phase': info.phase,
                    'test_step': info.test_step,
                    'step_name': info.step_name,
                    'expectation_order': info.expectation_order,
                    'source': info.source,
                    'mapping': info.mapping_id,
                })
        caught = None
        traceback = None
        try:
            operation(self.bench, **arguments)
        except CheckFailed as error:
            record.update(result='FAIL', detail=str(error))
            self._remember(error)
            caught, traceback = error, error.__traceback__
        except Exception as error:
            record.update(result='ERROR', detail=f'{type(error).__name__}: {error}')
            self._remember(error)
            caught, traceback = error, error.__traceback__
        else:
            record['result'] = 'PASS'
        try:
            record['bench_time_s'] = _text(self.bench.now())
        except Exception as clock_error:
            record['bench_time_s'] = None
            record['logging_error'] = f'{type(clock_error).__name__}: {clock_error}'
            self._remember(clock_error)
            if caught is None:
                record.update(result='ERROR', detail=record['logging_error'])
                caught, traceback = clock_error, clock_error.__traceback__
        self.records.append(record)
        if caught is not None:
            raise caught.with_traceback(traceback)

    def _remember(self, error):
        if not any(error is known for known in self.errors):
            self.errors.append(error)

    @property
    def not_run(self):
        candidates = self.planned if self.planned else (list(self.steps.keys()) if self.steps else [])
        if not candidates:
            return []
        def _base(eid):
            return eid.split('[')[0]
        done_bases = {_base(record['execution_id']) for record in self.records}
        return [execution_id for execution_id in candidates if _base(execution_id) not in done_bases]

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
