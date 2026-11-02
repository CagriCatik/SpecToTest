"""Diagnose- und Fehlerspeicher-Operationen."""
from tcg.runtime import CheckFailed


def clear_fault_memory(bench, *, ecu: str):
    """Löscht den Fehlerspeicher des angegebenen Steuergeräts (z.B. BCM1)."""
    bench.clear_fault_memory(ecu)


def read_fault_memory(bench, *, ecu: str):
    """Liest den Fehlerspeicher des angegebenen Steuergeräts."""
    bench.read_fault_memory(ecu)


def expect_fault_memory_entry(bench, *, code: str, ecu: str = 'BCM1'):
    """Prüft, ob ein bestimmter Fehlercode im Fehlerspeicher eingetragen ist."""
    entries = bench.read_fault_memory(ecu)
    if code not in entries:
        raise CheckFailed(f'Fehlerspeicher {ecu}: Fehlercode {code!r} nicht gefunden (aktuelle Einträge: {entries})')


def expect_fault_memory_empty(bench, *, ecu: str):
    """Prüft, ob der Fehlerspeicher des angegebenen Steuergeräts leer ist."""
    entries = bench.read_fault_memory(ecu)
    if entries:
        raise CheckFailed(f'Fehlerspeicher {ecu} ist nicht leer: {entries}')


def expect_diagnostic(bench, *, controller: str, code: str, active: bool):
    """Prüft den Status eines Diagnoseeintrags zum aktuellen Zeitpunkt."""
    actual = bench.diagnostic_active(controller, code)
    if actual is not active:
        raise CheckFailed(f'Diagnose {controller}/{code}: erwartet {active}, aktuell {actual}')


def expect_diagnostic_within(bench, *, controller: str, code: str, active: bool, timeout, interval):
    """Wartet pollegend bis der Zustand eintritt oder das Timeout abläuft."""
    deadline = bench.now() + timeout
    while True:
        actual = bench.diagnostic_active(controller, code)
        observed_at = bench.now()
        if observed_at > deadline:
            raise CheckFailed(f'Diagnose {controller}/{code} observation completed after timeout {timeout} s at {observed_at} s')
        if actual is active:
            return
        if observed_at >= deadline:
            raise CheckFailed(f'Diagnose {controller}/{code} wurde nicht innerhalb von {timeout}s {active}')
        bench.wait(min(interval, deadline - observed_at))


def monitor_diagnostic(bench, *, controller: str, code: str, active: bool, duration, interval):
    """Überwacht, dass der Zustand über die gesamte Dauer stabil bleibt."""
    deadline = bench.now() + duration
    while True:
        actual = bench.diagnostic_active(controller, code)
        if actual is not active:
            raise CheckFailed(f'Diagnose {controller}/{code} änderte Status: erwartet {active}, aktuell {actual}')
        if bench.now() >= deadline:
            return
        bench.wait(min(interval, deadline - bench.now()))

