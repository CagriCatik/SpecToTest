"""Project profile definitions, validation, and multi-file management for SpecToTest GUI."""
from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any

from tcg.core.mapping import load_mapping_files
from tcg.core.model import SpecError


@dataclass
class ProjectProfile:
    """A cohesive project configuration binding specs, mappings, registry, and bench."""
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
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProjectProfile:
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
        )


def get_builtin_profiles(root_dir: Path | None = None) -> list[ProjectProfile]:
    """Default profiles for Automotive HIL and Software Service Pilot."""
    return [
        ProjectProfile(
            id='automotive_hil',
            name='Automotive HIL (CANoe / dSPACE)',
            description='Fahrzeug-Prüfstand mit CAN-Bus, BCM-Diagnose und Spannungssteuerung',
            registry_target='operations.registry:REGISTRY',
            mapping_files=['inputs/operation_mapping.toml'],
            resources_file='inputs/resources.json',
            specs_dir='inputs',
            output_dir='generated',
            reports_dir='reports',
            bench_type='dummy',
            bench_config='inputs/demo_bench.json',
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
        ),
    ]


def test_validate_profile(profile: ProjectProfile) -> tuple[bool, str | None, dict[str, Any]]:
    """Strictly validate loading of all components of a profile before activating it.
    
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

    return True, None, {
        'registry': registry,
        'profile': res_profile,
        'raw_mappings': all_raw_mappings,
    }
