"""Test bench capabilities: what the bench must be able to do, checked at its boundary.

A loaded description proves only that a resource is *described*. Whether the active
bench can read, stimulate, send, switch a LIN schedule, call a method or subscribe to
an event is a separate question, answered here against the adapter boundary.

An operation declares the capabilities it needs; a bench declares what it offers. A
missing capability fails visibly before the test runs. There is deliberately no
substitute implementation that reports success without performing the interaction.
"""
from __future__ import annotations

from tcg.comm.model import Capability
from tcg.core.model import SpecError

#: Attribute a bench adapter may define to declare its capabilities explicitly.
BENCH_CAPABILITY_ATTRIBUTE = 'BENCH_CAPABILITIES'

#: Fallback: a bench that only implements methods is matched by method name.
METHOD_CAPABILITIES = {
    Capability.READ_SIGNAL: ('get_can_signal', 'get_signal', 'read_variable'),
    Capability.WRITE_SIGNAL: ('set_can_signal', 'set_signal', 'write_variable'),
    Capability.SEND_FRAME: ('send_frame',),
    Capability.SET_LIN_SCHEDULE: ('set_lin_schedule',),
    Capability.CALL_METHOD: ('call_method',),
    Capability.SUBSCRIBE_EVENT: ('subscribe_event',),
}


def known_capabilities():
    return frozenset(item.value for item in Capability)


def capability_problems(names, where):
    """Validate that `names` are declared capabilities."""
    unknown = sorted(set(map(str, names)) - known_capabilities())
    if unknown:
        return [f'{where}: unbekannte Testbench-Fähigkeit {", ".join(unknown)}; '
                f'bekannt: {", ".join(sorted(known_capabilities()))}']
    return []


def bench_capabilities(bench):
    """What `bench` declares it can do.

    An adapter may declare `BENCH_CAPABILITIES` explicitly. Otherwise the capabilities
    are derived from the methods it actually implements, so an adapter cannot claim a
    capability it has no implementation for.
    """
    declared = getattr(bench, BENCH_CAPABILITY_ATTRIBUTE, None)
    if declared is not None:
        return frozenset(str(item) for item in declared)
    offered = set()
    for capability, methods in METHOD_CAPABILITIES.items():
        if any(callable(getattr(bench, method, None)) for method in methods):
            offered.add(capability.value)
    return frozenset(offered)


def required_capabilities(cases):
    """Map each compiled test case id to the capabilities its steps need."""
    required = {}
    for case in cases:
        needed = set()
        for step in case.all_steps():
            contract = getattr(step, 'contract', None)
            needed.update(str(item) for item in getattr(contract, 'capabilities', ()) or ())
        required[case.id] = frozenset(needed)
    return required


def missing_for(required, available):
    return tuple(sorted(frozenset(required) - frozenset(available)))


def check_bench_capabilities(required, bench, where='Testbench'):
    """Raise unless `bench` offers every capability in `required`.

    `required` is either a set of capability names or the mapping that
    `required_capabilities` returns.
    """
    if isinstance(required, dict):
        needed = frozenset().union(*required.values()) if required else frozenset()
    else:
        needed = frozenset(str(item) for item in required)
    available = bench_capabilities(bench)
    missing = missing_for(needed, available)
    if missing:
        name = getattr(bench, 'BENCH_NAME', type(bench).__name__)
        raise SpecError(
            f'{where} {name!r} unterstützt die benötigten Fähigkeiten nicht: '
            f'{", ".join(missing)}; verfügbar: '
            f'{", ".join(sorted(available)) or "keine"}')


def capability_report(cases, bench):
    """Per test case: needed capabilities and the ones the bench is missing."""
    available = bench_capabilities(bench)
    report = {}
    for test_id, needed in required_capabilities(cases).items():
        report[test_id] = {
            'required': tuple(sorted(needed)),
            'missing': missing_for(needed, available),
        }
    return report
