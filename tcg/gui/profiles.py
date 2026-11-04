"""Project profile definitions, validation, and multi-file management for SpecToTest GUI."""
from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any

from tcg.comm.model import EMPTY_CATALOG
from tcg.comm.catalog import (
    COMM_CATALOG_KEY,
    descriptions_from_config,
    load_catalog,
    migrate_can_database,
)
from tcg.core.contracts import bind_registry
from tcg.core.mapping import load_mapping_files
from tcg.core.model import SpecError

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


@dataclass
class ProjectProfile:
    """A cohesive project configuration binding specs, mappings, registry, and bench.

    `communication` names this project's CAN, LIN and Ethernet descriptions.
    `can_database` is retained only as the legacy single-CAN setting. Relative paths
    are resolved against `base_dir`, the directory of the project configuration, so a
    project stays portable.
    """
    id: str
    name: str
    registry_target: str
    mapping_files: list[str]
    resources_file: str
    specs_dir: str
    description: str = ""
    output_dir: str = "generated"
    reports_dir: str = "reports"
    bench_type: str = "software"
    bench_config: str = ""
    can_database: str = ""
    #: Several communication descriptions, each bound to one network. Entries are
    #: dicts with path and optional network / format / technology. This supersedes
    #: the single `can_database`, which is still honoured for existing projects.
    communication: list = field(default_factory=list)
    #: Project-wide short names for qualified references.
    aliases: dict = field(default_factory=dict)
    base_dir: str = ""

    def resolve_path(self, value: str) -> Path:
        """Resolve one configured path against the project configuration's directory."""
        path = Path(value)
        if path.is_absolute() or not self.base_dir:
            return path
        return Path(self.base_dir) / path

    def can_database_path(self) -> Path | None:
        """The configured CAN signal catalog, or None when this project declares none."""
        return self.resolve_path(self.can_database) if self.can_database else None

    def description_configs(self) -> tuple:
        """Every communication description of this project, in configured order.

        A project that still uses the single `can_database` setting is migrated on
        the fly, so it keeps working without being rewritten.
        """
        if self.communication:
            return descriptions_from_config({'communication': self.communication},
                                            where=f'Projekt {self.id!r}')
        return migrate_can_database(self.can_database)

    def uses_communication(self) -> bool:
        return bool(self.communication or self.can_database)

    def to_dict(self) -> dict[str, Any]:
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'registry_target': self.registry_target,
            'mapping_files': self.mapping_files,
            'resources_file': self.resources_file,
            'specs_dir': self.specs_dir,
            'output_dir': self.output_dir,
            'reports_dir': self.reports_dir,
            'bench_type': self.bench_type,
            'bench_config': self.bench_config,
            'can_database': self.can_database,
            'communication': list(self.communication),
            'aliases': dict(self.aliases),
        }

    def to_dict_with_base(self) -> dict[str, Any]:
        return {**self.to_dict(), 'base_dir': self.base_dir}

    @classmethod
    def from_dict(cls, data: dict[str, Any], base_dir: str | Path | None = None) -> ProjectProfile:
        return cls(
            id=data['id'],
            name=data['name'],
            description=data.get('description', ''),
            registry_target=data['registry_target'],
            mapping_files=list(data.get('mapping_files', [])),
            resources_file=data.get('resources_file', ''),
            specs_dir=data.get('specs_dir', ''),
            output_dir=data.get('output_dir', ''),
            reports_dir=data.get('reports_dir', ''),
            bench_type=data.get('bench_type', 'dummy'),
            bench_config=data.get('bench_config', ''),
            can_database=data.get('can_database', ''),
            communication=list(data.get('communication', []) or []),
            aliases=dict(data.get('aliases', {}) or {}),
            base_dir=str(base_dir) if base_dir else data.get('base_dir', ''),
        )

    @classmethod
    def load(cls, path: str | Path) -> ProjectProfile:
        """Load a project configuration, resolving its relative paths against its own directory."""
        path = Path(path)
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
        except OSError as error:
            raise SpecError(f'{path.name}: cannot read project configuration '
                            f'({error.strerror})') from None
        except json.JSONDecodeError as error:
            raise SpecError(f'{path.name}: invalid JSON: {error}') from None
        if not isinstance(data, dict):
            raise SpecError(f'{path.name}: expected a JSON object')
        return cls.from_dict(data, base_dir=path.parent)


def get_builtin_profiles(root_dir: Path | None = None) -> list[ProjectProfile]:
    """Default profiles for Automotive HIL and Software Service Pilot.

    Their relative paths are resolved against the repository root, so the demo
    projects reference their own files explicitly rather than relying on the
    process working directory.
    """
    base = str(root_dir) if root_dir is not None else str(REPOSITORY_ROOT)
    return [
        ProjectProfile(
            id='automotive_hil',
            name='Automotive HIL (CANoe / dSPACE)',
            description='Fahrzeug-Prüfstand mit CAN-Bus, BCM-Diagnose und Spannungssteuerung',
            registry_target='operations.registry:REGISTRY',
            mapping_files=[
                'inputs/operation_mapping.toml',
                'inputs/multibus_mapping.toml',
            ],
            resources_file='inputs/resources.json',
            specs_dir='inputs',
            output_dir='generated',
            reports_dir='reports',
            bench_type='dummy',
            bench_config='inputs/demo_bench.json',
            # Load the complete demo communication topology in the GUI.  The
            # legacy ``can_database`` setting intentionally remains empty here:
            # it describes only one CAN JSON file and would hide LIN and Ethernet
            # from the default project.
            communication=[
                {
                    'path': 'inputs/can_signals.json',
                    'network': 'PowertrainCAN',
                    'format': 'can_json',
                    'technology': 'can',
                },
                {
                    'path': 'inputs/lin_signals.json',
                    'network': 'BodyComfortLIN',
                    'format': 'lin_json',
                    'technology': 'lin',
                },
                {
                    'path': 'tools/vehicle_services.arxml',
                    'network': 'BackboneEth',
                    'format': 'arxml',
                    'technology': 'ethernet',
                },
            ],
            base_dir=base,
        ),
        ProjectProfile(
            id='service_pilot',
            name='Software Service Pilot (RecordStore)',
            description='Reiner Softwarespeicher-Dienst für Persistenz-, Korruptions- und Crash-Tests',
            registry_target='examples.service_pilot.registry:SERVICE_REGISTRY',
            mapping_files=['examples/service_pilot/inputs/mapping.toml'],
            resources_file='examples/service_pilot/inputs/resources.json',
            specs_dir='examples/service_pilot/inputs/specs',
            output_dir='examples/service_pilot/generated',
            reports_dir='reports',
            bench_type='service',
            bench_config='examples/service_pilot/inputs/bench_config.json',
            # A pure software project needs no CAN signal catalog.
            can_database='',
            base_dir=base,
        ),
    ]


def test_validate_profile(profile: ProjectProfile) -> tuple[bool, str | None, dict[str, Any]]:
    """Strictly validate loading of all components of a profile before activating it.

    The complete communication catalog is loaded here, before anything is committed,
    and the returned registry is already bound to it. A profile whose catalog cannot
    be loaded is rejected outright, so the caller never activates a project that would
    silently keep using the previous project's catalog.

    Returns (success, error_message, loaded_artifacts).
    """
    from tcg.gui.models import load_profile_from_file, load_registry_from_target
    from tcg.gui.toml_io import load_mapping_file

    # 1. Test Registry loading
    try:
        registry = load_registry_from_target(profile.registry_target)
    except Exception as e:
        return False, f"Registry '{profile.registry_target}' konnte nicht geladen werden: {e}", {}

    # 2. Test ResourceProfile loading
    try:
        res_profile = load_profile_from_file(profile.resources_file)
    except Exception as e:
        return False, f"Ressourcenprofil '{profile.resources_file}' ist ungültig: {e}", {}

    # 3. Test Loading of ALL mapping files and ensure unique IDs
    all_raw_mappings = []
    seen_ids: dict[str, str] = {}

    for mf in profile.mapping_files:
        p = Path(mf)
        if not p.is_file():
            return False, f"Mapping-Datei '{mf}' existiert nicht.", {}
        raw_list, err = load_mapping_file(p)
        if err:
            return False, f"Fehler in Mapping-Datei '{mf}': {err}", {}
        for entry in raw_list:
            entry_id = entry.get('id', '').strip()
            if entry_id in seen_ids:
                return False, f"Doppelte Mapping-ID '{entry_id}' in '{mf}' (bereits definiert in '{seen_ids[entry_id]}')", {}
            seen_ids[entry_id] = mf
            entry['_source_file'] = mf
            all_raw_mappings.append(entry)

    # 4. Check specifications directory
    specs_p = Path(profile.specs_dir)
    if not specs_p.is_dir():
        return False, f"Spezifikationsverzeichnis '{profile.specs_dir}' existiert nicht.", {}

    # 5. Load every communication description and bind it to this project's registry
    can_catalog = None
    try:
        descriptions = profile.description_configs()
    except SpecError as e:
        return False, f"Kommunikationskonfiguration ist ungültig: {e}", {}

    if descriptions:
        for config in descriptions:
            path = profile.resolve_path(config.path)
            if not path.is_file():
                return False, (f"Kommunikationsbeschreibung '{path}' existiert nicht."), {}
        try:
            can_catalog = load_catalog(descriptions, base_dir=profile.base_dir or None,
                                       aliases=profile.aliases)
        except SpecError as e:
            return False, f"Fehler in der Kommunikationsbeschreibung: {e}", {}
        except Exception as e:  # unexpected, but must never activate the project
            return False, f"Fehler in der Kommunikationsbeschreibung: {e}", {}

    try:
        registry = bind_registry(registry, {COMM_CATALOG_KEY: can_catalog or EMPTY_CATALOG})
    except Exception as e:
        return False, f"Operationen konnten nicht an die Projektkonfiguration gebunden werden: {e}", {}

    return True, None, {
        'registry': registry,
        'profile': res_profile,
        'raw_mappings': all_raw_mappings,
        'catalog': can_catalog,
    }
