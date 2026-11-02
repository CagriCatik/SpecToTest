#!/usr/bin/env python3
"""Unified Test Bench Runner with HTML Dashboard Reporting.

Discovers and executes generated test cases against an in-memory or simulated
hardware test bench (Vector CANoe / dSPACE ControlDesk / Generic) and produces
both console verdicts and a rich, interactive HTML report.
"""
import argparse
import importlib.util
from pathlib import Path
import sys
import time

from tcg.adapters.outbound.dummy_bench import ControlDeskDummyBench, DummyBench, VectorDummyBench, load_config
from tcg.core.profile import load_profile
from tcg.runtime.html_report import generate_html_report
from tcg.runtime.runner import execute, write_junit_xml


def discover_test_modules(suite_dir: Path) -> list[tuple[str, Path]]:
    """Finds all generated test scripts (test_*.py) in the suite directory."""
    modules = []
    for file_path in sorted(suite_dir.glob('test_*.py')):
        modules.append((file_path.stem, file_path))
    return modules


def load_module_runners(module_path: Path) -> dict:
    """Dynamically imports a generated test module and retrieves its RUNNERS dictionary."""
    spec = importlib.util.spec_from_file_location(module_path.stem, module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load module from {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return getattr(module, 'RUNNERS', {})


def main():
    parser = argparse.ArgumentParser(description='Execute generated test suite on test bench with HTML reporting')
    parser.add_argument('--suite', default='generated', help='Directory containing generated test cases')
    parser.add_argument('--bench-type', choices=('dummy', 'vector', 'controldesk'), default='vector',
                        help='Test bench driver/mock (default: vector)')
    parser.add_argument('--bench-config', default='inputs/demo_bench.json', help='Test bench configuration JSON')
    parser.add_argument('--resources', default='inputs/resources.json', help='Resources profile JSON')
    parser.add_argument('--html-report', default='reports/test_report.html', help='Path for output HTML report')
    parser.add_argument('--junit-xml', help='Optional path for JUnit XML report')
    parser.add_argument('--filter', help='Optional substring filter for test case IDs')
    args = parser.parse_args()

    suite_dir = Path(args.suite)
    if not suite_dir.exists():
        print(f"ERROR: Suite directory '{suite_dir}' does not exist.", file=sys.stderr)
        return 2

    # Load configuration & profile
    profile = load_profile(Path(args.resources))
    bench_cfg = load_config(Path(args.bench_config), profile)

    bench_factories = {
        'dummy': ('Generic In-Memory Bench (DummyBench)', DummyBench),
        'vector': ('Vector CANoe / CANalyzer (VectorDummyBench)', VectorDummyBench),
        'controldesk': ('dSPACE ControlDesk HiL (ControlDeskDummyBench)', ControlDeskDummyBench),
    }
    bench_name, bench_cls = bench_factories[args.bench_type]

    # Discover tests
    test_files = discover_test_modules(suite_dir)
    if not test_files:
        print(f"WARNUNG: Keine Testskripte in '{suite_dir}' gefunden.", file=sys.stderr)
        return 0

    print("=" * 78)
    print("⚡ SpecToTest — Automatisierter Testbench-Lauf")
    print("=" * 78)
    print(f"Prüfstand:   {bench_name}")
    print(f"Test-Suite:  {suite_dir} ({len(test_files)} Skripte gefunden)")
    print(f"HTML-Report: {args.html_report}")
    print("-" * 78)

    all_logs = []
    start_total = time.perf_counter()

    for mod_name, file_path in test_files:
        try:
            runners = load_module_runners(file_path)
        except Exception as err:
            print(f"❌ Fehler beim Laden von {file_path.name}: {err}", file=sys.stderr)
            continue

        for test_id, runner in runners.items():
            if args.filter and args.filter.lower() not in test_id.lower():
                continue

            # Fresh bench instance per test case for deterministic isolation
            bench = bench_cls(bench_cfg)
            log = execute(runner, bench)
            all_logs.append(log)

            status_symbol = "✅ PASS" if log.result == "PASS" else ("❌ FAIL" if log.result == "FAIL" else "⚠️ ERROR")
            duration_ms = getattr(log, 'duration', 0.0) * 1000
            steps_count = len(getattr(log, 'records', []))
            print(f" {status_symbol}  {test_id:<42} ({steps_count:>2} Schritte, {duration_ms:>6.1f} ms)")
            if log.result != "PASS" and getattr(log, 'error', None):
                print(f"        └─ Error: {log.error}")

    total_duration = time.perf_counter() - start_total

    # Summary
    pass_cnt = sum(1 for l in all_logs if l.result == "PASS")
    fail_cnt = sum(1 for l in all_logs if l.result == "FAIL")
    err_cnt = sum(1 for l in all_logs if l.result == "ERROR")

    print("-" * 78)
    print(f"Ergebnis: {pass_cnt} bestanden, {fail_cnt} fehlgeschlagen, {err_cnt} Fehler (Gesamtdauer: {total_duration:.2f} s)")
    print("=" * 78)

    # Generate HTML Report
    html_path = Path(args.html_report)
    generate_html_report(all_logs, html_path, bench_type=bench_name)
    print(f"📊 Interaktiver HTML-Report gespeichert unter: {html_path.resolve()}")

    # Generate JUnit XML if requested
    if args.junit_xml:
        xml_path = Path(args.junit_xml)
        write_junit_xml(all_logs, xml_path)
        print(f"📄 JUnit XML Report gespeichert unter:       {xml_path.resolve()}")

    return 2 if err_cnt > 0 else (1 if fail_cnt > 0 else 0)


if __name__ == '__main__':
    sys.exit(main())

