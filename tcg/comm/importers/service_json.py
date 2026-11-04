"""Importer for the JSON service description produced by ``tools/arxml_to_json.py``.

The service-oriented Ethernet counterpart of `can_json`: the converter writes it,
and a project may reference it directly instead of the original ``.arxml``. The
schema is the one `arxml_to_json.arxml_to_dict` emits, identified by
``"protocol": "Ethernet"``.

Services carry no `ValueEncoding`: a method or an event is not a numeric signal.
"""
from __future__ import annotations

from pathlib import Path
from types import MappingProxyType

from tcg.comm.model import CommunicationResource, ObjectKind, Technology
from tcg.core.model import SpecError

from .can_json import read_json

TECHNOLOGY = Technology.ETHERNET
FORMAT_ID = 'service_json'

MEMBER_KINDS = (
    ('methods', ObjectKind.METHOD),
    ('events', ObjectKind.EVENT),
    ('fields', ObjectKind.FIELD),
)


def resources_from_dict(data, network, source, technology=Technology.ETHERNET):
    """Map a parsed service JSON description onto the common model."""
    if not isinstance(data, dict):
        raise SpecError(f'{source}: erwartet ein JSON-Objekt, '
                        f'nicht {type(data).__name__}')
    services = data.get('services')
    if 'services' not in data or not isinstance(services, dict):
        raise SpecError(f"{source}: Schlüssel 'services' fehlt oder ist kein Objekt")

    version = data.get('autosar_version')
    resources, problems = [], []

    for service_name, service in services.items():
        if not isinstance(service_name, str) or not service_name.strip():
            problems.append(f'{source}: Servicename {service_name!r} muss ein '
                            f'nicht-leerer Text sein')
            continue
        if not isinstance(service, dict):
            problems.append(f'{source}: Service {service_name!r} muss ein Objekt sein')
            continue

        resources.append(CommunicationResource(
            name=service_name, technology=technology, network=network,
            kind=ObjectKind.SERVICE, source=source,
            attributes=MappingProxyType({
                'autosar_version': version,
                'service_id': service.get('service_id'),
                'someip': bool(service.get('someip')),
            }),
        ))

        for key, kind in MEMBER_KINDS:
            members = service.get(key) or {}
            if not isinstance(members, dict):
                problems.append(f'{source}: Service {service_name!r}: {key!r} muss '
                                f'ein Objekt sein')
                continue
            for member_name, member in members.items():
                if not isinstance(member_name, str) or not member_name.strip():
                    problems.append(f'{source}: Service {service_name!r}: '
                                    f'{key} enthält einen ungültigen Namen '
                                    f'{member_name!r}')
                    continue
                member = member if isinstance(member, dict) else {}
                identifier = member.get('id')
                resources.append(CommunicationResource(
                    name=member_name, technology=technology, network=network,
                    kind=kind, source=source, container=service_name,
                    attributes=MappingProxyType({
                        'autosar_version': version,
                        'data_type': member.get('data_type'),
                        'id': None if identifier is None else str(identifier),
                        'service': service_name,
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
