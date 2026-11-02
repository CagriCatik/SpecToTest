"""Zündungs-Operationen (z.B. Zündung an, Zündung aus)."""


def set_ignition(bench, *, state: bool):
    """Schaltet die Zündung ein (state=True) oder aus (state=False)."""
    bench.set_ignition(state)

