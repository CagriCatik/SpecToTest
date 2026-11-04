"""Persistent execution logger writing timestamped .log files to disk.

Provides structured logging for automated test bench runs, capturing every step,
actuator confirmation, check verdict, exception, and overall summary.
"""
from datetime import datetime
import logging
from pathlib import Path
from typing import Any


LOGGER_NAME = 'tcg.execution'


def setup_execution_logger(
    log_dir: Path | str = 'logs',
    prefix: str = 'test_run',
    timestamp: datetime | None = None,
) -> tuple[logging.Logger, Path]:
    """Configures a logger that writes to a timestamped file in `log_dir` and updates `latest.log`.

    Returns:
        tuple[logging.Logger, Path]: The configured Logger and the Path to the timestamped log file.
    """
    directory = Path(log_dir)
    directory.mkdir(parents=True, exist_ok=True)

    ts = (timestamp or datetime.now()).strftime('%Y%m%d_%H%M%S')
    log_file = directory / f"{prefix}_{ts}.log"
    latest_file = directory / "latest.log"

    logger = logging.getLogger(f"{LOGGER_NAME}.{ts}")
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    # Remove existing handlers if any
    for h in list(logger.handlers):
        logger.removeHandler(h)
        h.close()

    formatter = logging.Formatter(
        '%(asctime)s [%(levelname)-5s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
    )

    # Handler for timestamped log
    fh_timestamped = logging.FileHandler(str(log_file), mode='w', encoding='utf-8')
    fh_timestamped.setLevel(logging.DEBUG)
    fh_timestamped.setFormatter(formatter)
    logger.addHandler(fh_timestamped)

    # Handler for latest.log (overwritten each run)
    fh_latest = logging.FileHandler(str(latest_file), mode='w', encoding='utf-8')
    fh_latest.setLevel(logging.DEBUG)
    fh_latest.setFormatter(formatter)
    logger.addHandler(fh_latest)

    return logger, log_file


def log_suite_start(logger: logging.Logger, bench_name: str, suite_dir: Path, script_count: int) -> None:
    """Logs the header of a test suite run."""
    logger.info("=" * 82)
    logger.info("⚡ SpecToTest — Testbench Ausführung gestartet")
    logger.info("=" * 82)
    logger.info("Prüfstand:   %s", bench_name)
    logger.info("Test-Suite:  %s (%d Testskripte gefunden)", suite_dir, script_count)
    logger.info("-" * 82)


def log_test_case_start(logger: logging.Logger, test_id: str, category: str) -> None:
    """Logs the start of a single test case."""
    logger.info("[%s] ▶ STARTE Testfall (Kategorie: %s)", test_id, category)


def log_step_record(logger: logging.Logger, test_id: str, record: dict[str, Any]) -> None:
    """Logs a single executed test step or check with actuator confirmation and time.

    Supports both TestLog records and Bench log_entries.
    """
    op = record.get('operation', 'unknown')

    # Format 1: Bench log_entries
    if 'details' in record:
        details = dict(record['details'])
        status = details.pop('status', None)
        args_str = ", ".join(f"{k}={v}" for k, v in details.items())
        time_str = f" [t={record.get('time', '')}]" if record.get('time') else ""
        status_str = f" [Aktorik: {status}]" if status else ""
        msg = f"[{test_id}]    • {op}({args_str}){status_str}{time_str}"
        logger.info(msg)
        return

    # Format 2: TestLog records
    step_id = record.get('execution_id', '?')
    phase = record.get('phase', 'ACTION')
    args = record.get('arguments', {})
    args_str = ", ".join(f"{k}={v}" for k, v in args.items())
    res = record.get('result', 'PASS')
    t_bench = record.get('bench_time_s')
    t_str = f" [t={t_bench}s]" if t_bench is not None else ""

    status_detail = ""
    if 'status' in record:
        status_detail = f" [Aktorik: {record['status']}]"
    if 'detail' in record and record['detail']:
        status_detail += f" ({record['detail']})"

    msg = f"[{test_id}]    • Step {step_id:<4} ({phase:<7}) {op}({args_str}) -> {res}{status_detail}{t_str}"
    if res == 'PASS':
        logger.info(msg)
    elif res == 'FAIL':
        logger.warning(msg)
    else:
        logger.error(msg)


def log_test_case_result(logger: logging.Logger, test_id: str, log_obj: Any) -> None:
    """Logs the verdict and runtime of a finished test case."""
    result = getattr(log_obj, 'result', 'UNKNOWN')
    duration_ms = getattr(log_obj, 'duration', 0.0) * 1000
    records = getattr(log_obj, 'records', [])
    err = getattr(log_obj, 'error', None)

    if result == 'PASS':
        logger.info(
            "[%s] ✔ VERDICT: PASS (%d Schritte erfolgreich, %.2f ms)",
            test_id, len(records), duration_ms
        )
    elif result == 'FAIL':
        logger.warning(
            "[%s] ✘ VERDICT: FAIL (%d Schritte, %.2f ms) — CheckFailed: %s",
            test_id, len(records), duration_ms, err
        )
    else:
        logger.error(
            "[%s] ⚠ VERDICT: ERROR (%d Schritte, %.2f ms) — Error: %s",
            test_id, len(records), duration_ms, err
        )


def log_suite_summary(
    logger: logging.Logger,
    all_logs: list[Any],
    total_duration_s: float,
    html_report_path: Path | None = None,
    junit_xml_path: Path | None = None,
    log_file_path: Path | None = None,
) -> None:
    """Logs the final summary table and generated report locations."""
    passed = sum(1 for l in all_logs if getattr(l, 'result', None) == 'PASS')
    failed = sum(1 for l in all_logs if getattr(l, 'result', None) == 'FAIL')
    errors = sum(1 for l in all_logs if getattr(l, 'result', None) == 'ERROR')
    total = len(all_logs)

    logger.info("-" * 82)
    logger.info(
        "ZUSAMMENFASSUNG: %d Gesamt | %d PASS | %d FAIL | %d ERROR (Laufzeit: %.3f s)",
        total, passed, failed, errors, total_duration_s
    )
    if html_report_path:
        logger.info("HTML-Report:   %s", html_report_path.resolve())
    if junit_xml_path:
        logger.info("JUnit-XML:     %s", junit_xml_path.resolve())
    if log_file_path:
        logger.info("Log-Datei:     %s", log_file_path.resolve())
    logger.info("=" * 82)
