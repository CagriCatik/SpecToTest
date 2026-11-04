#!/usr/bin/env python3
"""Unified Test Bench Runner with HTML Dashboard Reporting.

Discovers and executes generated test cases against an in-memory or simulated
hardware test bench (Vector CANoe / dSPACE ControlDesk / Generic) and produces
both console verdicts and a rich, interactive HTML report.
"""
import argparse
import importlib.util
import json
from pathlib import Path
import sys
import time

from tcg.adapters.outbound.dummy_bench import ControlDeskDummyBench, DummyBench, VectorDummyBench, load_config
from tcg.core.profile import load_profile
from tcg.runtime.execution_logger import (
    log_step_record,
    log_suite_start,
    log_suite_summary,
    log_test_case_result,
    log_test_case_start,
    setup_execution_logger,
)
from tcg.runtime.html_report import generate_html_report
from tcg.runtime.result import TestResult
from tcg.runtime.runner import execute, get_bench_factory, write_junit_xml


def load_manifest(suite_dir: Path) -> dict | None:
    """Loads and parses .manifest.json or manifest.json if present."""
    manifest_file = suite_dir / '.manifest.json'
    if not manifest_file.exists():
        manifest_file = suite_dir / 'manifest.json'

    if not manifest_file.exists():
        return None

    try:
        return json.loads(manifest_file.read_text(encoding='utf-8'))
    except Exception as err:
        raise ValueError(f"Invalid JSON in manifest '{manifest_file}': {err}") from err


def discover_test_modules(suite_dir: Path) -> list[tuple[str, Path]]:
    """Finds all generated test scripts (test_*.py) in the suite directory, strictly using the manifest if present."""
    data = load_manifest(suite_dir)
    if data is not None:
        file_list = data.get('files')
        if not isinstance(file_list, list):
            manifest_file = suite_dir / '.manifest.json' if (suite_dir / '.manifest.json').exists() else suite_dir / 'manifest.json'
            raise ValueError(f"Manifest '{manifest_file}' missing required 'files' list")

        modules = []
        for rel in file_list:
            p = suite_dir / rel
            if not p.is_file():
                raise FileNotFoundError(f"Missing test module listed in manifest: '{rel}'")
            if '__pycache__' not in p.parts:
                modules.append((p.stem, p))
        return sorted(modules, key=lambda item: str(item[1]))

    candidates = [p for p in sorted(suite_dir.rglob('test_*.py')) if '__pycache__' not in p.parts]
    modules = []
    seen_rel_paths = set()
    for p in candidates:
        rel = p.relative_to(suite_dir)
        # If an un-categorized root copy exists alongside categorized versions, skip the root copy
        if len(rel.parts) == 1 and any(len(c.relative_to(suite_dir).parts) > 1 and c.name == p.name for c in candidates):
            continue
        rel_key = str(rel.with_suffix(''))
        if rel_key not in seen_rel_paths:
            seen_rel_paths.add(rel_key)
            modules.append((p.stem, p))
    return sorted(modules, key=lambda item: str(item[1]))


def load_module_runners(module_path: Path) -> dict:
    """Dynamically imports a generated test module and retrieves its RUNNERS dictionary."""
    spec = importlib.util.spec_from_file_location(module_path.stem, module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load module from {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return getattr(module, 'RUNNERS', {})


def main(argv=None):
    parser = argparse.ArgumentParser(description='Execute generated test suite on test bench with HTML reporting')
    parser.add_argument('--suite', default='generated', help='Directory containing generated test cases')
    parser.add_argument('--bench-type', choices=('dummy', 'vector', 'controldesk'), default='vector',
                        help='Test bench driver/mock (default: vector)')
    parser.add_argument('--bench-config', default='inputs/demo_bench.json', help='Test bench configuration JSON')
    parser.add_argument('--resources', default='inputs/resources.json', help='Resources profile JSON')
    parser.add_argument('--html-report', default='reports/test_report.html', help='Path for output HTML report')
    parser.add_argument('--log-dir', default='logs', help='Directory for timestamped execution logs (default: logs)')
    parser.add_argument('--junit-xml', help='Optional path for JUnit XML report')
    parser.add_argument('--filter', help='Optional substring filter for test case IDs')
    args = parser.parse_args(argv)

    suite_dir = Path(args.suite)
    if not suite_dir.exists():
        print(f"ERROR: Suite directory '{suite_dir}' does not exist.", file=sys.stderr)
        return 2

    # Configure timestamped file logger
    exec_logger, log_file_path = setup_execution_logger(log_dir=args.log_dir)

    # Load configuration & profile
    profile = load_profile(Path(args.resources))
    bench_cfg = load_config(Path(args.bench_config), profile)

    bench_cls = get_bench_factory(args.bench_type)
    bench_name = getattr(bench_cls, 'BENCH_NAME', f'{args.bench_type} (Simulation)')

    # Discover tests
    try:
        manifest_data = load_manifest(suite_dir)
        test_files = discover_test_modules(suite_dir)
        manifest_specs = None
        if manifest_data is not None and 'specs' in manifest_data:
            raw_specs = manifest_data.get('specs')
            if not isinstance(raw_specs, dict):
                manifest_file = suite_dir / '.manifest.json' if (suite_dir / '.manifest.json').exists() else suite_dir / 'manifest.json'
                raise ValueError(f"Manifest '{manifest_file}' missing valid 'specs' dictionary")
            manifest_specs = {Path(k).as_posix(): v for k, v in raw_specs.items()}
            # Check for duplicate Test_IDs across specs within the manifest
            manifest_seen_ids = {}
            for rel_file, spec_info in manifest_specs.items():
                tids = spec_info.get('test_ids', []) if isinstance(spec_info, dict) else (spec_info if isinstance(spec_info, list) else [])
                for tid in tids:
                    if tid in manifest_seen_ids:
                        raise ValueError(
                            f"Duplicate test case ID '{tid}' declared in manifest across '{manifest_seen_ids[tid]}' and '{rel_file}'"
                        )
                    manifest_seen_ids[tid] = rel_file
    except Exception as err:
        exec_logger.error("Fehler bei der Testfall-Erkennung in '%s': %s", suite_dir, err)
        err_id = "MANIFEST_ERROR" if isinstance(err, ValueError) else "MISSING_TEST_FILE"
        err_log = TestResult(
            test_id=err_id,
            result='ERROR',
            error=err,
            duration=0.0,
            records=[],
        )
        err_log.category = 'manifest'
        all_logs = [err_log]
        log_test_case_result(exec_logger, err_id, err_log)

        print("=" * 78)
        print("⚡ SpecToTest — Automatisierter Testbench-Lauf")
        print("=" * 78)
        print(f"Prüfstand:   {bench_name}")
        print(f"Test-Suite:  {suite_dir}")
        print(f"HTML-Report: {args.html_report}")
        print(f"Log-Datei:   {log_file_path}")
        print("-" * 78)
        print(f" ⚠️ ERROR [manifest   ] {err_id:<38} (Manifestfehler)")
        print(f"        └─ Error: {err}", file=sys.stderr)
        print("-" * 78)
        print("Ergebnis: 0 bestanden, 0 fehlgeschlagen, 1 Fehler (Gesamtdauer: 0.00 s)")
        print("=" * 78)

        # Generate HTML Report
        html_path = Path(args.html_report)
        generate_html_report(all_logs, html_path, bench_type=bench_name)
        print(f"📊 Interaktiver HTML-Report gespeichert unter: {html_path.resolve()}")
        print(f"📝 Timestamped Log-Datei gespeichert unter:   {log_file_path.resolve()}")

        # Generate JUnit XML if requested
        xml_path = Path(args.junit_xml) if args.junit_xml else None
        if xml_path:
            write_junit_xml(all_logs, xml_path)
            print(f"📄 JUnit XML Report gespeichert unter:       {xml_path.resolve()}")

        log_suite_summary(
            exec_logger,
            all_logs,
            0.0,
            html_report_path=html_path,
            junit_xml_path=xml_path,
            log_file_path=log_file_path,
        )
        return 2

    if not test_files:
        print(f"WARNUNG: Keine Testskripte in '{suite_dir}' gefunden.", file=sys.stderr)
        return 0

    log_suite_start(exec_logger, bench_name, suite_dir, len(test_files))

    print("=" * 78)
    print("⚡ SpecToTest — Automatisierter Testbench-Lauf")
    print("=" * 78)
    print(f"Prüfstand:   {bench_name}")
    print(f"Test-Suite:  {suite_dir} ({len(test_files)} Skripte gefunden)")
    print(f"HTML-Report: {args.html_report}")
    print(f"Log-Datei:   {log_file_path}")
    print("-" * 78)

    all_logs = []
    seen_suite_runner_ids = {}
    start_total = time.perf_counter()

    for mod_name, file_path in test_files:
        category = file_path.parent.name if file_path.parent != suite_dir else 'general'
        rel_posix = file_path.relative_to(suite_dir).as_posix()

        expected_ids = None
        if manifest_specs is not None:
            if rel_posix not in manifest_specs:
                exec_logger.error("Manifest missing specification entry for '%s'", rel_posix)
                err = RuntimeError(f"Manifest missing specification entry for '{rel_posix}'")
                err_log = TestResult(
                    test_id=file_path.stem.upper(),
                    result='ERROR',
                    error=err,
                    duration=0.0,
                    records=[],
                )
                err_log.category = category
                all_logs.append(err_log)
                log_test_case_result(exec_logger, err_log.test_id, err_log)
                print(f" ⚠️ ERROR [{category:<11}] {file_path.name:<38} (Manifest-Inkonsistenz)")
                print(f"        └─ Error: {err}", file=sys.stderr)
                continue
            spec_entry = manifest_specs[rel_posix]
            if isinstance(spec_entry, dict):
                expected_ids = spec_entry.get('test_ids')
            elif isinstance(spec_entry, list):
                expected_ids = spec_entry
            if not isinstance(expected_ids, list):
                expected_ids = None

        try:
            runners = load_module_runners(file_path)
            if not isinstance(runners, dict):
                raise ImportError(f"RUNNERS in {file_path.name} must be a dictionary, got {type(runners).__name__}")
            if not runners and expected_ids is None:
                raise ImportError(f"No test runners (RUNNERS dictionary) found in {file_path.name}")
        except Exception as err:
            exec_logger.error("Fehler beim Laden von %s: %s", file_path.name, err)
            err_log = TestResult(
                test_id=file_path.stem.upper(),
                result='ERROR',
                error=err,
                duration=0.0,
                records=[],
            )
            err_log.category = category
            all_logs.append(err_log)
            log_test_case_result(exec_logger, err_log.test_id, err_log)
            print(f" ⚠️ ERROR [{category:<11}] {file_path.name:<38} (Ladefehler)")
            print(f"        └─ Error: {err}", file=sys.stderr)
            continue

        extra_ids = set()
        duplicate_expected = set()
        if expected_ids is not None:
            # 1. Check for duplicates within expected_ids for this module
            seen_expected = set()
            for tid in expected_ids:
                if tid in seen_expected:
                    duplicate_expected.add(tid)
                seen_expected.add(tid)
            for dup_id in sorted(duplicate_expected):
                err = RuntimeError(f"Duplicate test case ID '{dup_id}' declared in manifest for {file_path.name}")
                err_log = TestResult(test_id=dup_id, result='ERROR', error=err, duration=0.0, records=[])
                err_log.category = category
                all_logs.append(err_log)
                log_test_case_result(exec_logger, dup_id, err_log)
                print(f" ⚠️ ERROR [{category:<11}] {dup_id:<38} (Doppelte Testfall-ID im Manifest)")
                print(f"        └─ Error: {err}", file=sys.stderr)

            # 2. Check for missing test IDs (declared in manifest, missing from RUNNERS)
            missing_ids = [tid for tid in expected_ids if tid not in runners and tid not in duplicate_expected]
            for mid in missing_ids:
                err = RuntimeError(f"Expected test case '{mid}' declared in manifest is missing from {file_path.name} RUNNERS")
                err_log = TestResult(test_id=mid, result='ERROR', error=err, duration=0.0, records=[])
                err_log.category = category
                all_logs.append(err_log)
                log_test_case_result(exec_logger, mid, err_log)
                print(f" ⚠️ ERROR [{category:<11}] {mid:<38} (Fehlende Testfall-ID in RUNNERS)")
                print(f"        └─ Error: {err}", file=sys.stderr)

            # 3. Check for unexpected test IDs (in RUNNERS, but not declared in manifest)
            extra_ids = set(tid for tid in runners if tid not in seen_expected)
            for eid in sorted(extra_ids):
                err = RuntimeError(f"Unexpected test case ID '{eid}' in {file_path.name} RUNNERS not declared in manifest")
                err_log = TestResult(test_id=eid, result='ERROR', error=err, duration=0.0, records=[])
                err_log.category = category
                all_logs.append(err_log)
                log_test_case_result(exec_logger, eid, err_log)
                print(f" ⚠️ ERROR [{category:<11}] {eid:<38} (Unerwartete Testfall-ID in RUNNERS)")
                print(f"        └─ Error: {err}", file=sys.stderr)

        # 4. Check for duplicate test IDs across modules in the suite
        duplicate_runners = set()
        for tid in runners:
            if tid in seen_suite_runner_ids:
                duplicate_runners.add(tid)
                prev_file = seen_suite_runner_ids[tid]
                err = RuntimeError(f"Duplicate test case ID '{tid}' in {file_path.name}; already declared in {prev_file}")
                err_log = TestResult(test_id=tid, result='ERROR', error=err, duration=0.0, records=[])
                err_log.category = category
                all_logs.append(err_log)
                log_test_case_result(exec_logger, tid, err_log)
                print(f" ⚠️ ERROR [{category:<11}] {tid:<38} (Doppelte Testfall-ID in Suite)")
                print(f"        └─ Error: {err}", file=sys.stderr)
            else:
                seen_suite_runner_ids[tid] = file_path.name

        # Execute valid runners
        for test_id, runner in runners.items():
            if test_id in extra_ids or test_id in duplicate_runners:
                continue
            if args.filter and args.filter.lower() not in test_id.lower():
                continue

            category = file_path.parent.name if file_path.parent != suite_dir else 'general'
            log_test_case_start(exec_logger, test_id, category)

            # Fresh bench instance per test case for deterministic isolation
            bench = bench_cls(bench_cfg)
            log = execute(runner, bench)
            log.category = category
            all_logs.append(log)

            # Log steps to persistent log file
            for rec in getattr(log, 'records', []):
                log_step_record(exec_logger, test_id, rec)
            log_test_case_result(exec_logger, test_id, log)

            status_symbol = "✅ PASS" if log.result == "PASS" else ("❌ FAIL" if log.result == "FAIL" else "⚠️ ERROR")
            duration_ms = getattr(log, 'duration', 0.0) * 1000
            steps_count = len(getattr(log, 'records', []))
            print(f" {status_symbol}  [{category:<11}] {test_id:<38} ({steps_count:>2} Schritte, {duration_ms:>6.1f} ms)")
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
    print(f"📝 Timestamped Log-Datei gespeichert unter:   {log_file_path.resolve()}")
    print(f"📌 Aktueller Log-Shortcut (Latest):          {(Path(args.log_dir) / 'latest.log').resolve()}")

    # Generate JUnit XML if requested
    xml_path = Path(args.junit_xml) if args.junit_xml else None
    if xml_path:
        write_junit_xml(all_logs, xml_path)
        print(f"📄 JUnit XML Report gespeichert unter:       {xml_path.resolve()}")

    log_suite_summary(
        exec_logger,
        all_logs,
        total_duration,
        html_report_path=html_path,
        junit_xml_path=xml_path,
        log_file_path=log_file_path,
    )

    return 2 if err_cnt > 0 else (1 if fail_cnt > 0 else 0)


if __name__ == '__main__':
    sys.exit(main())

