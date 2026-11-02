"""Spannungsversorgungs- und Batterie-Operationen."""
from decimal import Decimal


def set_battery_voltage(bench, *, value: Decimal):
    """Setzt die Batteriespannung auf den angegebenen Wert (z.B. 7 V oder 13.8 V)."""
    bench.set_battery_voltage(value)


def set_supply(bench, *, value: Decimal):
    """Setzt die Versorgungsspannung auf den angegebenen Wert."""
    bench.set_supply(value)

