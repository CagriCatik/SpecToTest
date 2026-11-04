"""Format importers: description files in, common model out.

Every supported description format has exactly one importer here. An importer reads
one file and returns `CommunicationResource` objects; the compiler never sees DBC,
LDF or ARXML structures. Importers are registered by id, so a project may gain a new
format (or a library-backed replacement for one of these) without the core changing.

Library evaluation (2026-11): `cantools` was checked as a ready-made parser. It
covers DBC and AUTOSAR ARXML well, but it has **no LDF/LIN support** and it requires
`python-can`, a hardware transport stack that must stay out of the compiler (see the
"Testbench-Grenze" rule). `canmatrix` offers LDF only partially. The project therefore
keeps its stdlib-only importers, which fail loudly on constructs they do not support
rather than approximating them. `register_importer` exists so a cantools-backed
importer can be added later without touching the core.
"""
from __future__ import annotations

from pathlib import Path

from tcg.core.model import SpecError

from . import arxml, can_json, dbc, ldf, lin_json, service_json

#: importer id -> module exposing load(path, *, network, technology) and TECHNOLOGY
IMPORTERS = {
    'can_json': can_json,
    'lin_json': lin_json,
    'service_json': service_json,
    'dbc': dbc,
    'ldf': ldf,
    'arxml': arxml,
}

#: file suffix -> importer id, used when a description names no explicit format
SUFFIX_FORMATS = {
    '.json': 'can_json',
    '.dbc': 'dbc',
    '.ldf': 'ldf',
    '.arxml': 'arxml',
    '.xml': 'arxml',
}

#: JSON "protocol" marker -> importer id. The three JSON descriptions share an
#: extension, so the file's own declaration decides; guessing CAN would silently
#: turn LIN signals into CAN signals.
JSON_PROTOCOL_FORMATS = {
    'can': 'can_json',
    'lin': 'lin_json',
    'ethernet': 'service_json',
}


def sniff_mapping_format(data):
    """Decide which JSON description `data` holds, by its own declaration.

    One rule for files and for already parsed objects, so an in-memory description
    is never classified differently from the same description on disk.
    """
    if not isinstance(data, dict):
        return None
    protocol = str(data.get('protocol', '')).strip().lower()
    if protocol in JSON_PROTOCOL_FORMATS:
        return JSON_PROTOCOL_FORMATS[protocol]
    # Older CAN databases predate the marker; recognise them by their structure.
    if 'services' in data:
        return 'service_json'
    if 'schedules' in data or 'nodes' in data:
        return 'lin_json'
    if 'signals' in data or 'messages' in data:
        return 'can_json'
    return None


def sniff_json_format(path):
    """Decide which JSON description the file at `path` holds.

    Returns an importer id, or None when the file cannot be read or declares
    nothing. The importer then produces the proper error.
    """
    try:
        import json
        data = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        return None
    return sniff_mapping_format(data)


def register_importer(format_id, module, suffixes=()):
    """Register an additional description format."""
    IMPORTERS[format_id] = module
    for suffix in suffixes:
        SUFFIX_FORMATS[suffix.lower()] = format_id


def format_for(path, declared=None):
    """Decide which importer handles `path`."""
    if declared:
        if declared not in IMPORTERS:
            raise SpecError(f'{Path(path).name}: unbekanntes Beschreibungsformat '
                            f'{declared!r}; bekannt: {", ".join(sorted(IMPORTERS))}')
        return declared
    suffix = Path(path).suffix.lower()
    if suffix not in SUFFIX_FORMATS:
        raise SpecError(
            f'{Path(path).name}: Beschreibungsformat kann aus der Dateiendung '
            f'{suffix!r} nicht abgeleitet werden; gib "format" ausdrücklich an '
            f'({", ".join(sorted(IMPORTERS))})')
    if suffix == '.json':
        sniffed = sniff_json_format(path)
        if sniffed is None:
            raise SpecError(
                f'{Path(path).name}: JSON-Beschreibung deklariert kein "protocol" '
                f'und lässt sich nicht zuordnen; gib "format" ausdrücklich an '
                f'(can_json, lin_json, service_json)')
        return sniffed
    return SUFFIX_FORMATS[suffix]


def load_description(path, network, declared_format=None, technology=None):
    """Import one description file into resources of exactly one network."""
    format_id = format_for(path, declared_format)
    module = IMPORTERS[format_id]
    resources = module.load(Path(path), network=network, technology=technology)
    return format_id, tuple(resources)
