"""CAN-Bus und Signal-Operationen für Vector CANoe und dSPACE ControlDesk."""
from decimal import Decimal

from tcg.runtime import CheckFailed


def set_can_signal(bench, *, signal: str, value):
    """Setzt ein CAN-Signal auf dem Prüfstand (Vector CANoe / dSPACE ControlDesk)."""
    bench.set_can_signal(signal, value)


def expect_can_signal(bench, *, signal: str, value):
    """Prüft den aktuellen Wert eines CAN-Signals."""
    actual = bench.get_can_signal(signal)
    if actual != value:
        raise CheckFailed(f'CAN-Signal {signal}: erwartet {value}, aktuell {actual}')
    if hasattr(bench, '_log'):
        bench._log('expect_can_signal', signal=signal, expected=str(value), actual=str(actual), verdict='PASS')


def expect_can_signal_tolerance(bench, *, signal: str, value, tolerance):
    """Prüft, ob ein CAN-Signal innerhalb des Toleranzbands [value - tolerance, value + tolerance] liegt."""
    actual = bench.get_can_signal(signal)
    lower = value - tolerance
    upper = value + tolerance
    if not (lower <= actual <= upper):
        raise CheckFailed(f'CAN-Signal {signal}: erwartet {value} ± {tolerance} [{lower} .. {upper}], aktuell {actual}')
    if hasattr(bench, '_log'):
        bench._log('expect_can_signal_tolerance', signal=signal, expected=f'{value} ± {tolerance}', actual=str(actual), verdict='PASS')


def expect_can_signal_range(bench, *, signal: str, min_value, max_value):
    """Prüft, ob ein CAN-Signal im geschlossenen Wertebereich [min_value, max_value] liegt."""
    actual = bench.get_can_signal(signal)
    if not (min_value <= actual <= max_value):
        raise CheckFailed(f'CAN-Signal {signal}: erwartet im Bereich [{min_value} .. {max_value}], aktuell {actual}')
    if hasattr(bench, '_log'):
        bench._log('expect_can_signal_range', signal=signal, expected=f'[{min_value} .. {max_value}]', actual=str(actual), verdict='PASS')


def expect_can_signal_min(bench, *, signal: str, min_value):
    """Prüft, ob ein CAN-Signal mindestens den Mindestwert erreicht (>= min_value)."""
    actual = bench.get_can_signal(signal)
    if actual < min_value:
        raise CheckFailed(f'CAN-Signal {signal}: erwartet >= {min_value}, aktuell {actual}')
    if hasattr(bench, '_log'):
        bench._log('expect_can_signal_min', signal=signal, expected=f'>= {min_value}', actual=str(actual), verdict='PASS')


def expect_can_signal_max(bench, *, signal: str, max_value):
    """Prüft, ob ein CAN-Signal den Höchstwert nicht überschreitet (<= max_value)."""
    actual = bench.get_can_signal(signal)
    if actual > max_value:
        raise CheckFailed(f'CAN-Signal {signal}: erwartet <= {max_value}, aktuell {actual}')
    if hasattr(bench, '_log'):
        bench._log('expect_can_signal_max', signal=signal, expected=f'<= {max_value}', actual=str(actual), verdict='PASS')


def expect_can_signal_greater(bench, *, signal: str, value):
    """Prüft, ob ein CAN-Signal strikt größer als der Vergleichswert ist (> value)."""
    actual = bench.get_can_signal(signal)
    if actual <= value:
        raise CheckFailed(f'CAN-Signal {signal}: erwartet > {value}, aktuell {actual}')
    if hasattr(bench, '_log'):
        bench._log('expect_can_signal_greater', signal=signal, expected=f'> {value}', actual=str(actual), verdict='PASS')


def expect_can_signal_less(bench, *, signal: str, value):
    """Prüft, ob ein CAN-Signal strikt kleiner als der Vergleichswert ist (< value)."""
    actual = bench.get_can_signal(signal)
    if actual >= value:
        raise CheckFailed(f'CAN-Signal {signal}: erwartet < {value}, aktuell {actual}')
    if hasattr(bench, '_log'):
        bench._log('expect_can_signal_less', signal=signal, expected=f'< {value}', actual=str(actual), verdict='PASS')


def wait_can_signal(bench, *, signal: str, value, timeout, interval):
    """Wartet bis ein CAN-Signal den gewünschten Wert annimmt oder Timeout abläuft."""
    deadline = bench.now() + timeout
    while True:
        actual = bench.get_can_signal(signal)
        observed_at = bench.now()
        if observed_at > deadline:
            raise CheckFailed(
                f'CAN-Signal {signal} observation completed after timeout {timeout} s at {observed_at} s (value {actual})'
            )
        if actual == value:
            if hasattr(bench, '_log'):
                bench._log('wait_can_signal', signal=signal, expected=str(value), actual=str(actual), verdict='PASS')
            return
        if observed_at >= deadline:
            raise CheckFailed(
                f'CAN-Signal {signal}: erreichte {value} nicht innerhalb von {timeout}s (aktuell: {actual})'
            )
        bench.wait(min(interval, deadline - observed_at))
