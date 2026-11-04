"""Importer for SpecToTest's own JSON CAN description (``can_signals.json``).

This is the format produced by ``tools/dbc_to_json.py`` and shipped with the demo
project. It yields CAN frames (from ``messages``) and CAN signals (from ``signals``).
"""
from __future__ import annotations

import json
from pathlib import Path
from types import MappingProxyType

from tcg.comm.model import (
    CommunicationResource,
    ObjectKind,
    Technology,
    build_encoding,
)
from tcg.core.model import SpecError

TECHNOLOGY = Technology.CAN
FORMAT_ID = 'can_json'


def _object_pairs(where):
    """Reject duplicate JSON keys before one silently overwrites another."""
    def hook(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise SpecError(f'{where}: duplicate key {key!r}')
            result[key] = value
        return result
    return hook


def read_json(path, where=None):
    """Read one JSON description, rejecting duplicate keys and unreadable files."""
    path = Path(path)
    where = where or path.name
    try:
        text = path.read_text(encoding='utf-8-sig')
    except FileNotFoundError:
        raise SpecError(f'{where}: Kommunikationsbeschreibung nicht gefunden: {path}') from None
    except OSError as error:
        raise SpecError(f'{where}: Beschreibung nicht lesbar ({error.strerror})') from None
    try:
        return json.loads(text, object_pairs_hook=_object_pairs(where))
    except json.JSONDecodeError as error:
        raise SpecError(f'{where}: ungültiges JSON: {error}') from None


def resources_from_dict(data, network, source, technology=Technology.CAN):
    """Map an already parsed CAN description dict onto the common model."""
    if not isinstance(data, dict):
        raise SpecError(f'{source}: erwartet ein JSON-Objekt, '
                        f'nicht {type(data).__name__}')
    signals = data.get('signals')
    if 'signals' not in data or not isinstance(signals, dict):
        raise SpecError(f"{source}: Schlüssel 'signals' fehlt oder ist kein Objekt")
    messages = data.get('messages') or {}
    if not isinstance(messages, dict):
        raise SpecError(f"{source}: Schlüssel 'messages' muss ein Objekt sein")

    resources, problems = [], []

    for frame_name, frame in messages.items():
        if not isinstance(frame_name, str) or not frame_name.strip():
            problems.append(f'{source}: Botschaftsname {frame_name!r} muss ein '
                            f'nicht-leerer Text sein')
            continue
        if not isinstance(frame, dict):
            problems.append(f'{source}: Botschaft {frame_name!r} muss ein Objekt sein')
            continue
        resources.append(CommunicationResource(
            name=frame_name, technology=technology, network=network,
            kind=ObjectKind.FRAME, source=source,
            attributes=MappingProxyType({
                'id': frame.get('id'), 'dlc': frame.get('dlc'),
                'cycle_time_ms': frame.get('cycle_time_ms'),
                'comment': frame.get('comment'),
            }),
        ))

    for signal_name, definition in signals.items():
        if not isinstance(signal_name, str) or not signal_name.strip():
            problems.append(f'{source}: Signalname {signal_name!r} muss ein '
                            f'nicht-leerer Text sein')
            continue
        if not isinstance(definition, dict):
            problems.append(f'{source}: Signal {signal_name!r} muss ein Objekt sein, '
                            f'nicht {type(definition).__name__}')
            continue
        values = definition.get('values')
        if values is not None and not isinstance(values, dict):
            problems.append(f"{source}: Signal {signal_name!r}: 'values' muss ein "
                            f'Objekt sein, nicht {type(values).__name__}')
            continue
        where = f'{source}: Signal {signal_name!r}'
        try:
            encoding = build_encoding(
                where,
                unit=definition.get('unit'),
                factor=definition.get('factor', 1),
                offset=definition.get('offset', 0),
                minimum=definition.get('min'),
                maximum=definition.get('max'),
                values=values,
            )
        except SpecError as error:
            problems.extend(error.problems)
            continue
        container = definition.get('message')
        resources.append(CommunicationResource(
            name=signal_name, technology=technology, network=network,
            kind=ObjectKind.SIGNAL, source=source,
            container=container if isinstance(container, str) and container else None,
            encoding=encoding,
            attributes=MappingProxyType({
                'start_bit': definition.get('start_bit'),
                'length': definition.get('length'),
                'default': definition.get('default'),
                'comment': definition.get('comment'),
            }),
        ))

    if problems:
        raise SpecError(problems)
    return tuple(resources)


def default_network(data, path):
    """The network name a description suggests for itself."""
    name = data.get('database') if isinstance(data, dict) else None
    return name if isinstance(name, str) and name.strip() else Path(path).stem


def load(path, *, network=None, technology=None):
    path = Path(path)
    data = read_json(path)
    return resources_from_dict(
        data,
        network=network or default_network(data, path),
        source=path.name,
        technology=technology or TECHNOLOGY,
    )
