#!/usr/bin/env python3
"""SpecToTest — Interaktives Studio (PySide6 / Qt).

Erlaubt das Schreiben und Untersuchen von Spezifikationen, die Verwaltung von Mappings
und Operationen, die Satzprüfung sowie Projektprofile.

Verwendung:
    python3 gui.py
    python3 gui.py --profile service
    python3 gui.py --mapping inputs/operation_mapping.toml --registry operations.registry:REGISTRY
"""
import argparse
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(
        description="SpecToTest Studio (PySide6)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--profile",
        type=str,
        choices=["automotive", "service"],
        default="automotive",
        help="Projektprofil wählen ('automotive' oder 'service')",
    )
    parser.add_argument(
        "--mapping",
        type=str,
        default=None,
        help="Pfad zur TOML-Mappingdatei (überschreibt Profil)",
    )
    parser.add_argument(
        "--registry",
        type=str,
        default=None,
        help="Python-Ziel der Operations-Registry (überschreibt Profil)",
    )
    parser.add_argument(
        "--resources",
        type=str,
        default=None,
        help="Pfad zum Ressourcenprofil JSON (überschreibt Profil)",
    )
    parser.add_argument(
        "--light",
        action="store_true",
        help="Helles Farbschema (Standard: Dunkel)",
    )

    args = parser.parse_args()

    try:
        from tcg.gui.app import run_gui
        from tcg.gui.profiles import get_builtin_profiles
    except ImportError as e:
        print(f"\nFEHLER beim Starten der GUI: {e}")
        print("Hinweis: Für die grafische Oberfläche wird PySide6 benötigt:")
        print("    pip install PySide6-Essentials\n")
        sys.exit(1)

    builtins = {p.id: p for p in get_builtin_profiles()}
    selected_prof = builtins.get('service_pilot' if args.profile == 'service' else 'automotive_hil')

    # Allow CLI overrides
    mapping_f = args.mapping or (selected_prof.mapping_files[0] if selected_prof else "inputs/operation_mapping.toml")
    registry_t = args.registry or (selected_prof.registry_target if selected_prof else "operations.registry:REGISTRY")
    resources_f = args.resources or (selected_prof.resources_file if selected_prof else "inputs/resources.json")

    sys.exit(
        run_gui(
            project_profile=selected_prof,
            registry_target=registry_t,
            mapping_file=mapping_f,
            resources_file=resources_f,
            dark_theme=not args.light,
        )
    )


if __name__ == "__main__":
    main()
