"""Hexagonal Architecture: Driven Port (Secondary Interface) for Test Benches."""
from decimal import Decimal
from typing import Protocol, runtime_checkable


@runtime_checkable
class BenchPort(Protocol):
    """The generic Port that every test bench adapter must satisfy.

    A test bench provides a clock (now) and time progression (wait).
    Domain-specific operations (e.g. ignition, supply, diagnostics)
    interact with specific bench fixtures or adapters without polluting
    the core compiler port.
    """

    def now(self) -> Decimal:
        """Current bench clock time in seconds."""
        ...

    def wait(self, seconds: Decimal | float | int) -> None:
        """Advance time or wait on physical bench."""
        ...


@runtime_checkable
class CanBenchPort(BenchPort, Protocol):
    """Optional extension Port for test benches supporting CAN / HiL signal communication."""

    def set_can_signal(self, signal: str, value: Decimal) -> None:
        """Transmit/set a CAN bus signal value (e.g. via Vector XL Driver or ControlDesk)."""
        ...

    def get_can_signal(self, signal: str) -> Decimal:
        """Receive/read a CAN bus signal value."""
        ...
