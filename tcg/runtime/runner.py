"""Composition root and execution engine for running generated tests."""
import argparse
import json
from pathlib import Path
import sys
import time
import xml.etree.ElementTree as ET

from tcg.adapters.outbound.dummy_bench import ControlDeskDummyBench, DummyBench, VectorDummyBench, load_config
from tcg.core.model import SpecError
from tcg.core.profile import load_profile
from .result import TestResult
from .test_log import CheckFailed, TestFailure


def execute(run, bench):
    """Execute a single test runner against a bench instance."""
    start_time = time.perf_counter()
    if hasattr(bench, 'log_entries'):
        bench.log_entries.clear()
    spec_doc = getattr(run, '__doc__', '') or ''
    try:
        res = run(bench)
        duration = time.perf_counter() - start_time
        records = list(getattr(bench, 'log_entries', []))
        if hasattr(res, 'report') and hasattr(res, 'result'):
            res.duration = duration
            if hasattr(res, 'records') and not res.records:
                res.records = records
            if hasattr(res, 'specification') and not res.specification:
                res.specification = spec_doc
            return res
        return TestResult(getattr(run, 'test_id', getattr(run, '__name__', 'TEST')), 'PASS', duration=duration, records=records, specification=spec_doc)
    except TestFailure as failure:
        duration = time.perf_counter() - start_time
        failure.log.duration = duration
        if hasattr(failure.log, 'specification') and not failure.log.specification:
            failure.log.specification = spec_doc
        return failure.log
    except CheckFailed as failure:
        duration = time.perf_counter() - start_time
        records = list(getattr(bench, 'log_entries', []))
        test_id = getattr(run, 'test_id', getattr(run, '__name__', 'TEST'))
        return TestResult(test_id=test_id, result='FAIL', error=failure, duration=duration, records=records, specification=spec_doc)
    except Exception as error:
        duration = time.perf_counter() - start_time
        records = list(getattr(bench, 'log_entries', []))
        test_id = getattr(run, 'test_id', getattr(run, '__name__', 'TEST'))
        primary_err = error
        cleanup_errs = []
        if isinstance(error, ExceptionGroup) and error.message == "Multiple errors during cleanup":
            cleanup_errs = list(error.exceptions)
            if error.__context__ is not None:
                primary_err = error.__context__
        elif error.__context__ is not None:
            primary_err = error.__context__
            cleanup_errs = [error]
        return TestResult(test_id=test_id, result='ERROR', error=primary_err, cleanup_errors=cleanup_errs,
                          duration=duration, records=records, specification=spec_doc)


def write_junit_xml(logs, output_path: Path):
    """Export test results to standard JUnit XML format for CI/CD integration."""
    suites = ET.Element('testsuites')
    failures = sum(1 for log in logs if getattr(log, 'result', '') == 'FAIL')
    errors = sum(1 for log in logs if getattr(log, 'result', '') == 'ERROR')
    suite = ET.SubElement(suites, 'testsuite', {
        'name': 'SpecToTest',
        'tests': str(len(logs)),
        'failures': str(failures),
        'errors': str(errors),
    })
    for log in logs:
        test_id = getattr(log, 'test_id', 'TEST')
        duration = getattr(log, 'duration', 0.0)
        tc = ET.SubElement(suite, 'testcase', {
            'name': str(test_id),
            'classname': 'SpecToTest',
            'time': f"{duration:.3f}",
        })
        if getattr(log, 'result', '') == 'FAIL':
            err_msg = str(getattr(log, 'error', 'Check failed'))
            fail = ET.SubElement(tc, 'failure', {'message': err_msg})
            fail.text = err_msg
        elif getattr(log, 'result', '') == 'ERROR':
            err_msg = str(getattr(log, 'error', 'Runtime error'))
            err = ET.SubElement(tc, 'error', {'message': err_msg})
            err.text = err_msg
    tree = ET.ElementTree(suites)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tree.write(str(output_path), encoding='utf-8', xml_declaration=True)


BENCH_FACTORIES = {
    'dummy': DummyBench,
    'vector': VectorDummyBench,
    'controldesk': ControlDeskDummyBench,
}


def register_bench_factory(name: str, factory):
    """Register an injectable bench factory for runtime execution."""
    BENCH_FACTORIES[name] = factory


def get_bench_factory(name: str):
    """Retrieve registered bench factory by name."""
    if name not in BENCH_FACTORIES:
        raise ValueError(f'unknown bench factory {name!r}; available: {sorted(BENCH_FACTORIES)}')
    return BENCH_FACTORIES[name]


def run_main(*pos_args, argv=None, bench_factory=None):
    """CLI runner invoked by generated test script __main__."""
    if len(pos_args) == 1:
        runners = pos_args[0]
        profile_id = None
    elif len(pos_args) >= 2:
        profile_id, runners = pos_args[0], pos_args[1]
    else:
        raise TypeError('run_main expected 1 or 2 positional arguments')

    parser = argparse.ArgumentParser(description='Run generated tests on the deterministic test bench')
    parser.add_argument('--resources', default='inputs/resources.json')
    parser.add_argument('--bench-config', default='inputs/demo_bench.json')
    parser.add_argument('--bench-type', choices=('dummy', 'vector', 'controldesk'), default='dummy')
    parser.add_argument('--test-id', choices=tuple(runners))
    parser.add_argument('--junit-xml', help='Path to output JUnit XML report (for Jenkins/GitLab CI)')
    parser.add_argument('--html-report', help='Path to output HTML report dashboard')
    args = parser.parse_args(argv)
    try:
        profile = load_profile(Path(args.resources))
        if profile_id is not None and profile.profile_id != profile_id:
            raise SpecError(f'generated for profile {profile_id}, got {profile.profile_id}')
        config = load_config(Path(args.bench_config), profile)
    except SpecError as error:
        print(f'SETUP FAILED: {error}', file=sys.stderr)
        return 3

    factory = bench_factory if bench_factory is not None else get_bench_factory(args.bench_type)
    sample_bench = factory(config)
    bench_label = getattr(sample_bench, 'BENCH_NAME', f'{args.bench_type} (Simulation)')

    ids = (args.test_id,) if args.test_id else tuple(runners)
    logs = [execute(runners[test_id], factory(config)) for test_id in ids]
    report_dict = {'results': [r.report() for r in logs]}
    if profile_id:
        report_dict['profile_id'] = profile.profile_id
    print(json.dumps(report_dict, ensure_ascii=False, indent=2))

    if args.junit_xml:
        write_junit_xml(logs, Path(args.junit_xml))

    if args.html_report:
        from .html_report import generate_html_report
        generate_html_report(logs, Path(args.html_report), bench_type=bench_label)

    results = {log.result for log in logs}
    return 2 if 'ERROR' in results else 1 if 'FAIL' in results else 0

