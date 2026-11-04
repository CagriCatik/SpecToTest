"""CAN compatibility layer over the technology-neutral communication catalog.

The CAN signal catalog was the first use case of what is now
`tcg.comm` (model, importers, capabilities). This module keeps the previous
CAN-only entry points working so existing projects, project configurations and
tooling do not have to change in one step:

* `load_can_signal_catalog(path)` reads one CAN JSON description and returns a
  `CommunicationCatalog` holding exactly that network.
* `CAN_CATALOG_KEY` still addresses the catalog in the project-data mapping; it is
  the same key the generic layer uses.
* `CanSignalValue` is the CAN-flavoured `SignalValue` with PHYSICAL semantics.

New projects should configure `communication` (several networks, several formats)
instead of a single `can_database`; see `tcg.comm.catalog.migrate_can_database`.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from tcg.comm.catalog import COMM_CATALOG_KEY
from tcg.comm.importers import can_json
from tcg.comm.model import (
    CommunicationCatalog,
    DescriptionSource,
    EMPTY_CATALOG,
    ObjectKind,
    Technology,
    normalise_state,
)
from tcg.core.model import SpecError

from .comm_types import PHYSICAL, RAW, ResourceReference, SignalValue

#: Retained name; identical to tcg.comm.catalog.COMM_CATALOG_KEY.
CAN_CATALOG_KEY = COMM_CATALOG_KEY

#: Retained name; an unconfigured catalog knows no resource at all.
UNCONFIGURED_CATALOG = EMPTY_CATALOG


def load_can_signal_catalog(source, name=None):
    """Load and validate one CAN signal description (JSON or DBC).

    Returns a `CommunicationCatalog` containing a single CAN network. Raises
    `SpecError` naming the file, the signal and the offending state for a missing
    file, invalid JSON, duplicate JSON keys, a malformed schema, a non-finite raw
    value, or state names that collide under `normalise_state`. There is no silent
    fallback.
    """
    if isinstance(source, dict):
        where = name or '<inline>'
        network = can_json.default_network(source, where)
        resources = can_json.resources_from_dict(
            source, network=network, source=where, technology=Technology.CAN)
        sources = (DescriptionSource(name=where, path=where, format='can_json',
                                     network=network, technology=Technology.CAN,
                                     resource_count=len(resources)),)
        return CommunicationCatalog(resources=resources, sources=sources, configured=True)

    if not isinstance(source, (str, Path)):
        raise SpecError(f'{name or "CAN-Signaldatenbank"}: erwartet einen Dateipfad '
                        f'oder ein Objekt, nicht {type(source).__name__}')

    path = Path(source)
    where = name or path.name
    suffix = path.suffix.lower()
    if suffix == '.dbc':
        from tcg.comm.importers import dbc as dbc_importer
        resources = dbc_importer.load(path, network=None, technology=Technology.CAN)
        format_id = 'dbc'
        network = resources[0].network if resources else path.stem
    else:
        data = can_json.read_json(path, where)
        network = can_json.default_network(data, path)
        resources = can_json.resources_from_dict(
            data, network=network, source=where, technology=Technology.CAN)
        format_id = 'can_json'

    sources = (DescriptionSource(name=where, path=str(path), format=format_id,
                                 network=network, technology=Technology.CAN,
                                 resource_count=len(resources)),)
    return CommunicationCatalog(resources=resources, sources=sources, configured=True)


@dataclass(frozen=True)
class CanSignalValue(SignalValue):
    """A CAN signal value in PHYSICAL units, resolved against the referenced signal."""
    technology: object = Technology.CAN


def can_signal_reference():
    """A reference parameter restricted to CAN signals."""
    return ResourceReference(technology=Technology.CAN, kinds=ObjectKind.SIGNAL,
                             label='CAN-Signal')


__all__ = [
    'CAN_CATALOG_KEY', 'CanSignalValue', 'PHYSICAL', 'RAW', 'UNCONFIGURED_CATALOG',
    'can_signal_reference', 'load_can_signal_catalog', 'normalise_state',
]
