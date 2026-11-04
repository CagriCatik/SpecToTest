"""Project profile definitions and management for SpecToTest GUI."""
from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any


@dataclass
class ProjectProfile:
    """A cohesive project configuration binding specs, mappings, registry, and bench."""
    id: str
    name: str
    description: str
    registry_target: str
    mapping_files: list[str]
    resources_file: str
    specs_dir: str
    output_dir: str
    reports_dir: str
    bench_type: str
    bench_config: str

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
