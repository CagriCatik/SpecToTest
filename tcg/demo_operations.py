"""Reusable technical operations for the deterministic demonstration adapter.

These functions are deliberately outside the generator core. A different project can
register a different library without changing specification parsing or rendering.
"""
from .runtime import CheckFailed


def set_supply(bench, *, value):
    bench.set_supply(value)


def wait(bench, *, seconds):
    bench.wait(seconds)


def _diagnostic(bench, controller, code):
    actual = bench.diagnostic_active(controller, code)
    if type(actual) is not bool:
        raise TypeError(f'bench returned {type(actual).__name__} for diagnostic, expected bool')
    return actual


def expect_diagnostic(bench, *, controller, code, active):
    """Check one observation at the current bench time."""
    actual = _diagnostic(bench, controller, code)
    if actual is not active:
        raise CheckFailed(f'diagnostic {controller}/{code}: expected {active}, actual {actual}')


def expect_diagnostic_within(bench, *, controller, code, active, timeout, interval):
    """Poll until the state matches or the explicit timeout is reached."""
    deadline = bench.now() + timeout
    while True:
        actual = _diagnostic(bench, controller, code)
        if actual is active:
            return
        if bench.now() >= deadline:
            raise CheckFailed(f'diagnostic {controller}/{code} did not become {active} within {timeout} s')
        bench.wait(min(interval, deadline - bench.now()))


def monitor_diagnostic(bench, *, controller, code, active, duration, interval):
    """Sample the state from now through the explicit duration, including both ends."""
    deadline = bench.now() + duration
    while True:
        actual = _diagnostic(bench, controller, code)
        if actual is not active:
            raise CheckFailed(f'diagnostic {controller}/{code} changed during monitoring: '
                              f'expected {active}, actual {actual} at {bench.now()} s')
        if bench.now() >= deadline:
            return
        bench.wait(min(interval, deadline - bench.now()))


def select_screen(bench, *, screen):
    bench.select_screen(screen)


def expect_screen_text(bench, *, text):
    actual = bench.screen_text()
    if actual != text:
        raise CheckFailed(f'screen text: expected {text!r}, actual {actual!r}')


def write_parameter(bench, *, parameter, value):
    bench.write_parameter(parameter, value)


def expect_parameter(bench, *, parameter, value):
    actual = bench.read_parameter(parameter)
    if actual != value:
        raise CheckFailed(f'parameter {parameter}: expected {value}, actual {actual}')
