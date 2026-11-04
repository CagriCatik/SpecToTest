"""Importer for the JSON LIN description produced by ``tools/ldf_to_json.py``.

This is the LIN counterpart of `can_json`: the converter writes it, and a project
may reference it directly instead of the original ``.ldf``. The schema is the one
`ldf_to_json.ldf_to_dict` emits, identified by ``"protocol": "LIN"``.
"""
from __future__ import annotations

from pathlib import Path
from types import MappingProxyType

from tcg.comm.model import (
    CommunicationResource,
    ObjectKind,
    Technology,
    build_encoding,
)
from tcg.core.model import SpecError

from .can_json import read_json

TECHNOLOGY = Technology.LIN
FORMAT_ID = 'lin_json'


def resources_from_dict(data, network, source, technology=Technology.LIN):
    """Map a parsed LIN JSON description onto the common model."""
    if not isinstance(data, dict):
        raise SpecError(f'{source}: erwartet ein JSON-Objekt, '
                        f'nicht {type(data).__name__}')
    signals = data.get('signals')
    if 'signals' not in data or not isinstance(signals, dict):
        raise SpecError(f"{source}: Schlüssel 'signals' fehlt oder ist kein Objekt")
    frames = data.get('frames') or {}
    schedules = data.get('schedules') or {}
    if not isinstance(frames, dict) or not isinstance(schedules, dict):
        raise SpecError(f"{source}: 'frames' und 'schedules' müssen Objekte sein")

    resources, problems = [], []

    for table, entries in schedules.items():
        if not isinstance(entries, list):
            problems.append(f'{source}: Schedule {table!r} muss eine Liste sein')
            continue
        pairs = tuple((entry.get('frame'), entry.get('delay_ms'))
                      for entry in entries if isinstance(entry, dict))
        resources.append(CommunicationResource(
            name=table, technology=technology, network=network,
            kind=ObjectKind.SCHEDULE, source=source,
            attributes=MappingProxyType({
                'frames': tuple(frame for frame, _ in pairs if frame),
                'entries': tuple((frame, delay) for frame, delay in pairs if frame),
                'commands': (),
            }),
        ))

    for frame_name, frame in frames.items():
        if not isinstance(frame, dict):
            problems.append(f'{source}: Frame {frame_name!r} muss ein Objekt sein')
            continue
        resources.append(CommunicationResource(
            name=frame_name, technology=technology, network=network,
            kind=ObjectKind.FRAME, source=source,
            attributes=MappingProxyType({
                'id': frame.get('id'), 'publisher': frame.get('publisher'),
                'length': frame.get('length'),
                'diagnostic': bool(frame.get('diagnostic')),
                'aggregate': frame.get('aggregate'),
                'members': tuple(frame.get('members', ())),
            }),
        ))

    for signal_name, definition in signals.items():
        if not isinstance(definition, dict):
            problems.append(f'{source}: Signal {signal_name!r} muss ein Objekt sein')
            continue
        values = definition.get('values')
        if values is not None and not isinstance(values, dict):
            problems.append(f"{source}: Signal {signal_name!r}: 'values' muss ein "
                            f'Objekt sein')
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
        container = definition.get('frame')
        resources.append(CommunicationResource(
            name=signal_name, technology=technology, network=network,
            kind=ObjectKind.SIGNAL, source=source,
            container=container if isinstance(container, str) and container else None,
            encoding=encoding,
            attributes=MappingProxyType({
                'size': definition.get('size'),
                'init': definition.get('init'),
                'publisher': definition.get('publisher'),
                'subscribers': tuple(definition.get('subscribers', ())),
                'encoding_type': definition.get('encoding_type'),
            }),
        ))

    if problems:
        raise SpecError(problems)
    return tuple(resources)


def load(path, *, network=None, technology=None):
    path = Path(path)
    data = read_json(path)
    name = data.get('database') if isinstance(data, dict) else None
    return resources_from_dict(
        data,
        network=network or (name if isinstance(name, str) and name else path.stem),
        source=path.name,
        technology=technology or TECHNOLOGY,
    )
