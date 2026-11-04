"""Service-oriented Ethernet operations.

Ethernet communication here is service-oriented: methods are called, events are
subscribed to and received, fields are read and written. These are genuinely
different interactions from setting a CAN signal, so they get their own operations
with their own contracts instead of being flattened into a generic bus-write.

Nothing in this module assumes SOME/IP. A SOME/IP deployment in the description only
adds service and method ids as attributes; an interface without one is served the
same way. The concrete transport belongs to the bench adapter, never here.
"""
from tcg.runtime import CheckFailed


def call_service_method(bench, *, method, argument='', result_variable=''):
    """Ruft eine Service-Methode auf (Request/Response)."""
    bench.call_method(method, argument)


def expect_method_result(bench, *, method, argument='', expected=''):
    """Ruft eine Service-Methode auf und prüft deren Antwort."""
    actual = bench.call_method(method, argument)
    if str(actual) != str(expected):
        raise CheckFailed(f'Service-Methode {method}: erwartet {expected!r}, '
                          f'erhalten {actual!r}')
    if hasattr(bench, '_log'):
        bench._log('expect_method_result', method=method, expected=str(expected),
                   actual=str(actual), verdict='PASS')


def subscribe_event(bench, *, event):
    """Abonniert ein Service-Event."""
    bench.subscribe_event(event)


def expect_event_received(bench, *, event, count=1):
    """Prüft, wie oft ein abonniertes Event empfangen wurde."""
    actual = bench.received_event_count(event)
    if actual < count:
        raise CheckFailed(f'Service-Event {event}: erwartet mindestens {count} '
                          f'Empfänge, gezählt {actual}')
    if hasattr(bench, '_log'):
        bench._log('expect_event_received', event=event, expected=str(count),
                   actual=str(actual), verdict='PASS')
