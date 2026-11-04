"""Loading a project's communication catalog from its configured descriptions.

One project may load several descriptions, each bound to exactly one network:

    PowertrainCAN  <- powertrain.dbc     (CAN,      format dbc)
    BodyLIN        <- body.ldf           (LIN,      format ldf)
    BackboneEth    <- services.arxml     (Ethernet, format arxml)

Loading is strict. A missing, unreadable or contradictory description raises
`SpecError`; nothing falls back to a previously loaded catalog or to built-in values.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from types import MappingProxyType

from tcg.comm.importers import load_description
from tcg.comm.model import (
    CommunicationCatalog,
    DescriptionSource,
    EMPTY_CATALOG,
    Technology,
    check_unique_identities,
)
from tcg.core.model import SpecError

#: Key under which the catalog travels in the generic project-data mapping.
COMM_CATALOG_KEY = 'communication_catalog'


ADAPTER_NAMING_POLICIES = ('local', 'qualified', 'prefixed')


@dataclass(frozen=True)
class DescriptionConfig:
    """One configured communication description of a project.

    `adapter_naming` fixes how this description's resources are addressed on the test
    bench: ``local`` (default, the bare name), ``qualified`` or ``prefixed``.
    `adapter_names` overrides individual resources by name. Both belong to this
    description alone, so loading another network never changes these addresses.
    """
    path: str
    network: str = ''
    format: str = ''
    technology: str = ''
    adapter_naming: str = 'local'
    adapter_names: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data, where='communication'):
        if not isinstance(data, dict):
            raise SpecError(f'{where}: jede Beschreibung muss ein Objekt sein, '
                            f'nicht {type(data).__name__}')
        unknown = sorted(set(data) - {'path', 'network', 'format', 'technology',
                                      'adapter_naming', 'adapter_names'})
        if unknown:
            raise SpecError(f'{where}: unbekannte Felder {", ".join(unknown)}; '
                            f'erlaubt sind path, network, format, technology, '
                            f'adapter_naming, adapter_names')
        naming = str(data.get('adapter_naming', 'local') or 'local')
        if naming not in ADAPTER_NAMING_POLICIES:
            raise SpecError(f'{where}: adapter_naming {naming!r} ist unbekannt; '
                            f'erlaubt: {", ".join(ADAPTER_NAMING_POLICIES)}')
        names = data.get('adapter_names') or {}
        if not isinstance(names, dict):
            raise SpecError(f'{where}: adapter_names muss ein Objekt sein')
        path = data.get('path')
        if not isinstance(path, str) or not path.strip():
            raise SpecError(f'{where}: "path" fehlt oder ist leer')
        return cls(path=path, network=str(data.get('network', '') or ''),
                   format=str(data.get('format', '') or ''),
                   technology=str(data.get('technology', '') or ''),
                   adapter_naming=naming, adapter_names=dict(names))

    def to_dict(self):
        data = {'path': self.path}
        for key in ('network', 'format', 'technology'):
            value = getattr(self, key)
            if value:
                data[key] = value
        if self.adapter_naming != 'local':
            data['adapter_naming'] = self.adapter_naming
        if self.adapter_names:
            data['adapter_names'] = dict(self.adapter_names)
        return data

    def resolved_technology(self, where):
        if not self.technology:
            return None
        try:
            return Technology(self.technology.lower())
        except ValueError:
            allowed = ', '.join(item.value for item in Technology)
            raise SpecError(f'{where}: unbekannte Technologie {self.technology!r}; '
                            f'bekannt: {allowed}') from None


def _resolve(path, base_dir):
    path = Path(path)
    if path.is_absolute() or not base_dir:
        return path
    return Path(base_dir) / path


def load_catalog(descriptions, base_dir=None, aliases=None, strict=True):
    """Load every configured description into one catalog.

    Returns a `CommunicationCatalog`. With `strict` (the default) any problem raises
    `SpecError` listing every finding; the per-description status is also available on
    `catalog.sources` so a UI can show which file failed.
    """
    descriptions = tuple(descriptions or ())
    if not descriptions:
        return EMPTY_CATALOG

    sources, resources, problems = [], [], []
    for index, config in enumerate(descriptions, 1):
        where = f'communication[{index}] ({Path(config.path).name})'
        path = _resolve(config.path, base_dir)
        # Without an explicit network the importer names it, e.g. from the DBC/JSON
        # database name; only then does the file stem serve as a last resort.
        network = config.network or Path(config.path).stem
        try:
            technology = config.resolved_technology(where)
            format_id, imported = load_description(
                path, network=config.network or None,
                declared_format=config.format or None, technology=technology)
            if imported:
                network = imported[0].network
        except SpecError as error:
            problems.extend(error.problems)
            sources.append(DescriptionSource(
                name=Path(config.path).name, path=str(path),
                format=config.format or 'unbekannt', network=network,
                error='; '.join(error.problems)))
            continue
        except Exception as error:  # an importer must not crash the whole load
            problems.append(f'{where}: {error}')
            sources.append(DescriptionSource(
                name=Path(config.path).name, path=str(path),
                format=config.format or 'unbekannt', network=network,
                error=str(error)))
            continue

        imported = tuple(
            replace(resource, attributes=MappingProxyType({
                **dict(resource.attributes),
                'adapter_naming': config.adapter_naming,
                'adapter_address': config.adapter_names.get(resource.name),
            }))
            for resource in imported)

        technologies = {resource.technology for resource in imported}
        sources.append(DescriptionSource(
            name=Path(config.path).name, path=str(path), format=format_id,
            network=network,
            technology=next(iter(technologies)) if len(technologies) == 1 else None,
            resource_count=len(imported)))
        resources.extend(imported)

    if not problems:
        try:
            check_unique_identities(resources, where='Kommunikationskatalog')
        except SpecError as error:
            problems.extend(error.problems)

    catalog = CommunicationCatalog(resources=resources, sources=sources,
                                   aliases=aliases or {}, configured=True)

    if not problems:
        problems.extend(_alias_problems(catalog))
        # A second network must never silently re-address an existing resource; if two
        # descriptions claim the same adapter address, say so instead.
        problems.extend(catalog.address_collisions)

    if problems and strict:
        raise SpecError(problems)
    return catalog


def _alias_problems(catalog):
    problems = []
    for alias, target in catalog.aliases.items():
        matches = catalog._index.get(target, ())
        if not matches:
            problems.append(f'Alias {alias!r} verweist auf {target!r}, das in keiner '
                            f'geladenen Beschreibung existiert')
        elif len(matches) > 1:
            alternatives = ', '.join(sorted(r.qualified_name for r in matches))
            problems.append(f'Alias {alias!r} verweist mehrdeutig auf {target!r}: '
                            f'{alternatives}')
    return problems


def catalog_from_mapping(data, network=None, name='<inline>', declared_format=None):
    """Build a catalog from an already parsed description, for any technology.

    The in-memory sibling of `load_catalog`. The format is taken from the object's
    own ``protocol`` marker (or its structure), exactly as for a file on disk, so an
    inline LIN description is never read as CAN.
    """
    from tcg.comm.importers import IMPORTERS, sniff_mapping_format

    format_id = declared_format or sniff_mapping_format(data)
    if format_id is None:
        raise SpecError(f'{name}: Beschreibung deklariert kein "protocol" und lässt '
                        f'sich nicht zuordnen; gib das Format ausdrücklich an '
                        f'(can_json, lin_json, service_json)')
    module = IMPORTERS.get(format_id)
    if module is None or not hasattr(module, 'resources_from_dict'):
        raise SpecError(f'{name}: Format {format_id!r} kann nicht aus einem Objekt '
                        f'geladen werden; verwende eine Datei')

    resolved_network = network or (
        data.get('database') if isinstance(data.get('database'), str) else None) or name
    resources = module.resources_from_dict(
        data, network=resolved_network, source=name, technology=module.TECHNOLOGY)
    source = DescriptionSource(name=name, path=name, format=format_id,
                               network=resolved_network, technology=module.TECHNOLOGY,
                               resource_count=len(resources))
    catalog = CommunicationCatalog(resources=resources, sources=(source,),
                                   configured=True)
    if catalog.address_collisions:
        raise SpecError(list(catalog.address_collisions))
    return catalog


def migrate_can_database(can_database):
    """Compatibility path for the previous single `can_database` setting.

    A project that still configures one CAN JSON database keeps working: it is read as
    a single description whose network name comes from the database itself.
    """
    if not can_database:
        return ()
    return (DescriptionConfig(path=str(can_database), format='can_json',
                              technology=Technology.CAN.value),)


def descriptions_from_config(data, where='Projektkonfiguration'):
    """Read the `communication` list of a project configuration."""
    entries = data.get('communication')
    if entries is None:
        return ()
    if not isinstance(entries, list):
        raise SpecError(f'{where}: "communication" muss eine Liste sein, '
                        f'nicht {type(entries).__name__}')
    return tuple(DescriptionConfig.from_dict(entry, f'{where}.communication[{index}]')
                 for index, entry in enumerate(entries, 1))
