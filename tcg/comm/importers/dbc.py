"""Importer for Vector CANdb (.dbc) descriptions.

The DBC text parser already shipped with this repository (``tools/dbc_to_json.py``)
is reused rather than duplicated: it produces the same structure as the JSON CAN
description, which `can_json` then maps onto the common model.

Supported: BO_ messages, SG_ signals with byte order, factor, offset, min/max and
unit, VAL_ value tables, CM_ comments and the cycle-time attribute. Not supported:
multiplexed signals beyond their plain definition, extended multiplexing, attribute
definitions other than cycle time, and environment variables -- these are carried as
plain attributes or dropped, and never silently change a signal's value semantics.
"""
from __future__ import annotations

from pathlib import Path

from tcg.comm.model import Technology
from tcg.core.model import SpecError

from . import can_json

TECHNOLOGY = Technology.CAN
FORMAT_ID = 'dbc'


def parse_dbc_text(text, where):
    # Imported lazily: the DBC text parser lives with the conversion CLI, and the
    # compiler must not depend on that tool at import time.
    from tools.dbc_to_json import dbc_to_dict
    try:
        return dbc_to_dict(text)
    except SpecError:
        raise
    except Exception as error:
        raise SpecError(f'{where}: DBC konnte nicht gelesen werden: {error}') from None


def load(path, *, network=None, technology=None):
    path = Path(path)
    try:
        # DBC files are conventionally written in cp1252; UTF-8 is also common.
        # Try UTF-8 first and fall back, so neither spelling of a unit like °C is lost.
        raw = path.read_bytes()
        try:
            text = raw.decode('utf-8-sig')
        except UnicodeDecodeError:
            text = raw.decode('cp1252')
    except FileNotFoundError:
        raise SpecError(f'{path.name}: Kommunikationsbeschreibung nicht gefunden: '
                        f'{path}') from None
    except OSError as error:
        raise SpecError(f'{path.name}: Beschreibung nicht lesbar '
                        f'({error.strerror})') from None

    data = parse_dbc_text(text, path.name)
    if not data.get('signals'):
        raise SpecError(f'{path.name}: DBC enthält keine Signale (SG_)')
    return can_json.resources_from_dict(
        data,
        network=network or can_json.default_network(data, path),
        source=path.name,
        technology=technology or TECHNOLOGY,
    )
