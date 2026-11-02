"""Composition root for running generated tests on the demonstration adapter."""
import argparse
import json
from pathlib import Path
import sys

from .dummy_bench import DummyBench, load_config
from .model import SpecError
from .profile import load_profile
from .runtime import TestFailure


def execute(run, bench):
    try:
        return run(bench)
    except TestFailure as failure:
        return failure.log


def run_main(profile_id, runners, argv=None):
    parser = argparse.ArgumentParser(description='Run generated tests on the deterministic demo bench')
    parser.add_argument('--resources', required=True)
    parser.add_argument('--bench-config', required=True)
    parser.add_argument('--test-id', choices=tuple(runners))
    args = parser.parse_args(argv)
    try:
        profile = load_profile(Path(args.resources))
        if profile.profile_id != profile_id:
            raise SpecError(f'generated for profile {profile_id}, got {profile.profile_id}')
        config = load_config(Path(args.bench_config), profile)
    except SpecError as error:
        print(f'SETUP FAILED: {error}', file=sys.stderr)
        return 3
    ids = (args.test_id,) if args.test_id else tuple(runners)
    logs = [execute(runners[test_id], DummyBench(config)) for test_id in ids]
    print(json.dumps({'profile_id': profile.profile_id, 'results': [log.report() for log in logs]}, ensure_ascii=False, indent=2))
    results = {log.result for log in logs}
    return 2 if 'ERROR' in results else 1 if 'FAIL' in results else 0
