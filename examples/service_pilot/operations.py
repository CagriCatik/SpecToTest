"""Integration Layer: Operations and Assertion Wrappers for RecordStoreService.

Translates domain operations into RecordStoreService calls and converts
deviations into standardized SpecToTest CheckFailed verdicts.
"""
from tcg.runtime import CheckFailed
from .service import ServiceError, ValidationError


def write_record(bench, *, key: str, value: str) -> None:
    """Sets a record key and value in the service."""
    bench.service.set_record(key, str(value))
    bench.log_step('write_record', status='SET', key=key, value=str(value))


def expect_record_value(bench, *, key: str, expected: str) -> None:
    """Asserts that a record exists and matches expected value."""
    actual = bench.service.get_record(key)
    expected_str = str(expected)
    if actual != expected_str:
        bench.log_step(
            'expect_record_value',
            status='FAIL',
            key=key,
            expected=expected_str,
            actual=str(actual),
        )
        raise CheckFailed(f"Datensatz '{key}': erwartet '{expected_str}', erhalten '{actual}'")
    bench.log_step(
        'expect_record_value',
        status='MATCH',
        key=key,
        expected=expected_str,
        actual=str(actual),
    )


def expect_record_missing(bench, *, key: str) -> None:
    """Asserts that a record does not exist in the service."""
    actual = bench.service.get_record(key)
    if actual is not None:
        bench.log_step(
            'expect_record_missing',
            status='FAIL',
            key=key,
            actual=str(actual),
        )
        raise CheckFailed(f"Datensatz '{key}' existiert unerwartet mit Wert '{actual}'")
    bench.log_step('expect_record_missing', status='MATCH', key=key, result='ABSENT')


def delete_record(bench, *, key: str) -> None:
    """Deletes a record from the service."""
    existed = bench.service.delete_record(key)
    bench.log_step('delete_record', status='DEL', key=key, existed=existed)


def restart_service(bench) -> None:
    """Restarts the service, reloading persisted state from disk."""
    bench.service.restart()
    bench.log_step('restart_service', status='RESTART', note="Reloaded from disk")


def inject_fault(bench, *, fault_type: str) -> None:
    """Injects a fault mode into the service."""
    bench.service.inject_fault(fault_type)
    bench.log_step('inject_fault', status='FAULT', fault=fault_type)


def clear_faults(bench) -> None:
    """Clears all active fault injections."""
    bench.service.clear_faults()
    bench.log_step('clear_faults', status='CLEAR')


def expect_service_health(bench, *, status: str) -> None:
    """Asserts that the service health status matches expectation."""
    is_healthy = bench.service.is_healthy()
    expected_healthy = status.lower() in ('ok', 'aktiv', 'healthy', 'up')
    if is_healthy != expected_healthy:
        bench.log_step('expect_service_health', status='FAIL', expected=status, healthy=is_healthy)
        raise CheckFailed(f"Dienst-Zustand: erwartet '{status}', tatsächlich gesund={is_healthy}")
    bench.log_step('expect_service_health', status='MATCH', expected=status, healthy=is_healthy)
