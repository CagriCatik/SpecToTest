"""Importer for a deliberately bounded AUTOSAR ARXML subset.

ARXML is a container format, **not a bus type**. This importer resolves one clearly
delimited use case and refuses everything else rather than guessing.

Supported
---------
* AUTOSAR schema 4.x (``http://autosar.org/schema/r4.0``) and AUTOSAR 3.x
  (``http://autosar.org/3.*``); the detected version is reported on the source.
* ``SERVICE-INTERFACE`` elements for service-oriented Ethernet communication:
  - the interface itself            -> `ObjectKind.SERVICE`
  - ``METHODS/CLIENT-SERVER-OPERATION``  -> `ObjectKind.METHOD`
  - ``EVENTS/VARIABLE-DATA-PROTOTYPE``   -> `ObjectKind.EVENT`
  - ``FIELDS/FIELD``                     -> `ObjectKind.FIELD`
* ``SOMEIP-SERVICE-INTERFACE-DEPLOYMENT`` is read **only** to attach service,
  method and event ids when it is present. Its absence is not an error: a service
  interface is not required to be SOME/IP.
* ``APPLICATION-PRIMITIVE-DATA-TYPE`` / ``IMPLEMENTATION-DATA-TYPE`` short names are
  carried as the declared data type of a field or event, without interpretation.

Not supported
-------------
ECU extracts, system/topology descriptions, CAN or LIN clusters expressed in ARXML,
frame and PDU mapping, signal-to-PDU packing, E2E and SecOC properties, data
transformation, compu-methods and unit resolution, and ``PORT-PROTOTYPE`` wiring.

A ``SERVICE-INTERFACE`` whose children include an element this importer does not
understand fails loudly with that element named: constructs needed by a resource are
never silently dropped. Unrelated parts of the file are ignored without error.
"""
from __future__ import annotations

from pathlib import Path
import re
from types import MappingProxyType
from xml.etree import ElementTree

from tcg.comm.model import CommunicationResource, ObjectKind, Technology
from tcg.core.model import SpecError

TECHNOLOGY = Technology.ETHERNET
FORMAT_ID = 'arxml'

#: Children of a SERVICE-INTERFACE this importer understands.
SUPPORTED_INTERFACE_CHILDREN = frozenset({
    'SHORT-NAME', 'LONG-NAME', 'DESC', 'CATEGORY', 'ADMIN-DATA', 'INTRODUCTION',
    'ANNOTATIONS', 'NAMESPACES',
    'METHODS', 'EVENTS', 'FIELDS',
})

#: Element types this importer can turn into resources, per container.
METHOD_ELEMENTS = frozenset({'CLIENT-SERVER-OPERATION'})
EVENT_ELEMENTS = frozenset({'VARIABLE-DATA-PROTOTYPE'})
FIELD_ELEMENTS = frozenset({'FIELD'})

_NAMESPACE = re.compile(r'^\{([^}]*)\}')
_DOCTYPE = re.compile(r'<!(DOCTYPE|ENTITY)\b', re.IGNORECASE)


def _local(tag):
    return tag.rsplit('}', 1)[-1] if '}' in tag else tag


def _short_name(element):
    for child in element:
        if _local(child.tag) == 'SHORT-NAME':
            return (child.text or '').strip()
    return ''


def _detect_version(root_tag, root):
    match = _NAMESPACE.match(root_tag)
    namespace = match.group(1) if match else ''
    if 'r4.0' in namespace or '/4.' in namespace:
        return '4.x', namespace
    if '/3.' in namespace or 'autosar.org/3' in namespace:
        return '3.x', namespace
    if namespace:
        return 'unbekannt', namespace
    return 'ohne Namensraum', ''


def parse_arxml(text, where='description.arxml'):
    """Parse an ARXML into an ElementTree root, refusing unsafe or alien documents."""
    if _DOCTYPE.search(text):
        raise SpecError(f'{where}: DOCTYPE- oder ENTITY-Deklarationen werden aus '
                        f'Sicherheitsgründen abgelehnt')
    try:
        root = ElementTree.fromstring(text)
    except ElementTree.ParseError as error:
        raise SpecError(f'{where}: ungültiges XML: {error}') from None
    if _local(root.tag) != 'AUTOSAR':
        raise SpecError(f'{where}: Wurzelelement ist {_local(root.tag)!r}, '
                        f'erwartet wird "AUTOSAR"')
    return root


def _someip_deployment(root):
    """service short name -> {'service_id':..., 'methods': {...}, 'events': {...}}"""
    deployments = {}
    for element in root.iter():
        if _local(element.tag) != 'SOMEIP-SERVICE-INTERFACE-DEPLOYMENT':
            continue
        name = _short_name(element)
        entry = {'service_id': None, 'methods': {}, 'events': {}}
        for child in element:
            tag = _local(child.tag)
            if tag == 'SERVICE-INTERFACE-ID':
                entry['service_id'] = (child.text or '').strip()
            elif tag in ('METHOD-DEPLOYMENTS', 'EVENT-DEPLOYMENTS'):
                bucket = entry['methods'] if tag == 'METHOD-DEPLOYMENTS' else entry['events']
                for deployment in child:
                    target, identifier = None, None
                    for leaf in deployment:
                        leaf_tag = _local(leaf.tag)
                        if leaf_tag in ('METHOD-REF', 'EVENT-REF'):
                            target = (leaf.text or '').strip().rsplit('/', 1)[-1]
                        elif leaf_tag in ('METHOD-ID', 'EVENT-ID'):
                            identifier = (leaf.text or '').strip()
                    if target:
                        bucket[target] = identifier
        if name:
            deployments[name] = entry
    return deployments


def _data_type_of(element):
    for child in element:
        if _local(child.tag).endswith('TYPE-TREF'):
            return (child.text or '').strip().rsplit('/', 1)[-1]
    return None


def resources_from_arxml(root, network, source, technology=Technology.ETHERNET):
    version, namespace = _detect_version(root.tag, root)
    deployments = _someip_deployment(root)
    resources, problems = [], []
    interfaces = [element for element in root.iter()
                  if _local(element.tag) == 'SERVICE-INTERFACE']

    if not interfaces:
        raise SpecError(
            f'{source}: keine SERVICE-INTERFACE-Elemente gefunden. Dieser Import '
            f'unterstützt ausschließlich serviceorientierte Ethernet-Kommunikation '
            f'(SERVICE-INTERFACE); System-, ECU-Extract- sowie CAN-/LIN-Cluster-'
            f'Beschreibungen werden nicht unterstützt (erkannte AUTOSAR-Version: '
            f'{version})')

    for interface in interfaces:
        service = _short_name(interface)
        if not service:
            problems.append(f'{source}: SERVICE-INTERFACE ohne SHORT-NAME')
            continue
        unsupported = sorted({_local(child.tag) for child in interface
                              if _local(child.tag) not in SUPPORTED_INTERFACE_CHILDREN})
        if unsupported:
            problems.append(
                f'{source}: Service {service!r} enthält die nicht unterstützten '
                f'Elemente {", ".join(unsupported)}; dieser Import deckt nur '
                f'METHODS, EVENTS und FIELDS ab')
            continue

        deployment = deployments.get(service, {})
        resources.append(CommunicationResource(
            name=service, technology=technology, network=network,
            kind=ObjectKind.SERVICE, source=source,
            attributes=MappingProxyType({
                'autosar_version': version,
                'service_id': deployment.get('service_id'),
                'someip': bool(deployment),
            }),
        ))

        for child in interface:
            tag = _local(child.tag)
            if tag == 'METHODS':
                allowed, kind, bucket = METHOD_ELEMENTS, ObjectKind.METHOD, 'methods'
            elif tag == 'EVENTS':
                allowed, kind, bucket = EVENT_ELEMENTS, ObjectKind.EVENT, 'events'
            elif tag == 'FIELDS':
                allowed, kind, bucket = FIELD_ELEMENTS, ObjectKind.FIELD, None
            else:
                continue
            for member in child:
                member_tag = _local(member.tag)
                if member_tag not in allowed:
                    problems.append(
                        f'{source}: Service {service!r}: {member_tag!r} in {tag} wird '
                        f'nicht unterstützt (unterstützt: {", ".join(sorted(allowed))})')
                    continue
                member_name = _short_name(member)
                if not member_name:
                    problems.append(f'{source}: Service {service!r}: {member_tag} '
                                    f'ohne SHORT-NAME')
                    continue
                identifier = (deployment.get(bucket, {}).get(member_name)
                              if bucket else None)
                resources.append(CommunicationResource(
                    name=member_name, technology=technology, network=network,
                    kind=kind, source=source, container=service,
                    attributes=MappingProxyType({
                        'autosar_version': version,
                        'data_type': _data_type_of(member),
                        'id': identifier,
                        'service': service,
                    }),
                ))

    if problems:
        raise SpecError(problems)
    return tuple(resources), version


def load(path, *, network=None, technology=None):
    path = Path(path)
    try:
        text = path.read_text(encoding='utf-8-sig')
    except FileNotFoundError:
        raise SpecError(f'{path.name}: Kommunikationsbeschreibung nicht gefunden: '
                        f'{path}') from None
    except OSError as error:
        raise SpecError(f'{path.name}: Beschreibung nicht lesbar '
                        f'({error.strerror})') from None
    root = parse_arxml(text, path.name)
    resources, _version = resources_from_arxml(
        root, network=network or path.stem, source=path.name,
        technology=technology or TECHNOLOGY,
    )
    return resources
