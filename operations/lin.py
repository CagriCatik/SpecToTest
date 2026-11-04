"""LIN operations.

Signal reading and writing share their semantics with CAN and therefore reuse the
generic signal operations in `operations.signals`. Only what is genuinely specific to
LIN lives here: schedule table control. There is deliberately no generic
``send_bus_data`` that would push these differences into untyped dictionaries.

Values are PHYSICAL unless the operation name says ``_raw``.
"""
from tcg.runtime import CheckFailed


def set_lin_schedule(bench, *, schedule):
    """Schaltet die LIN-Schedule-Tabelle des Masters um."""
    bench.set_lin_schedule(schedule)


def expect_lin_schedule(bench, *, schedule):
    """Prüft, welche LIN-Schedule-Tabelle aktiv ist."""
    actual = bench.get_lin_schedule()
    if actual != schedule:
        raise CheckFailed(f'LIN-Schedule: erwartet {schedule}, aktiv {actual}')
    if hasattr(bench, '_log'):
        bench._log('expect_lin_schedule', schedule=schedule, actual=str(actual),
                   verdict='PASS')


def send_lin_frame(bench, *, frame):
    """Sendet einen LIN-Frame einmalig (unconditional frame)."""
    bench.send_frame(frame)
