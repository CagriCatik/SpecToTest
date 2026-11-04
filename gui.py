#!/usr/bin/env python3
"""SpecToTest — Interaktives Mapping Studio (PySide6 / Qt).

Erlaubt das interaktive Verknüpfen von natürlichen Spezifikationssätzen mit Python-Operationen
und umgekehrt (Vice Versa).

Verwendung:
    python3 gui.py
    python3 gui.py --mapping inputs/operation_mapping.toml --registry operations.registry:REGISTRY
    python3 gui.py --mapping examples/service_pilot/inputs/mapping.toml --registry examples.service_pilot.registry:SERVICE_REGISTRY
"""
import argparse
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(
        description="SpecToTest Interaktives Mapping Studio (PySide6)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--mapping",
        type=str,
        default="inputs/operation_mapping.toml",
        help="Pfad zur TOML-Mappingdatei",
    )
    parser.add_argument(
        "--registry",
        type=str,
        default="operations.registry:REGISTRY",
        help="Python-Ziel der Operations-Registry (z.B. 'operations.registry:REGISTRY')",
    )
    parser.add_argument(
        "--resources",
        type=str,
        default="inputs/resources.json",
        help="Pfad zum Ressourcenprofil (JSON)",
    )
    parser.add_argument(
        "--light",
        action="store_true",
        help="Helles Farbschema (Standard: Dunkel)",
    )

    args = parser.parse_args()

    try:
        from tcg.gui.app import run_gui
    except ImportError as e:
        print(f"\n❌ FEHLER beim Starten der GUI: {e}")
        print("Hinweis: Für die grafische Oberfläche wird PySide6 benötigt:")
        print("    pip install PySide6-Essentials\n")
        sys.exit(1)

    sys.exit(
        run_gui(
            registry_target=args.registry,
            mapping_file=args.mapping,
            resources_file=args.resources,
            dark_theme=not args.light,
        )
    )


if __name__ == "__main__":
    main()
