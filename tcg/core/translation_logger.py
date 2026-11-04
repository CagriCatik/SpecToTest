"""Translation / Compilation Logger.

Produces detailed, human-readable traceability logs for the compilation phase:
- Inbound Specification parsing (MD/TXT)
- Sentence matching against TOML mappings
- Parameter extraction and physical unit conversions (e.g. mV -> V)
- Expectation binding to action steps
- Control flow & loop scoping
- Outbound Python test generation and AST validation
"""
from datetime import datetime
import logging
from pathlib import Path
from typing import Any


LOGGER_NAME = 'tcg.compilation'


def setup_translation_logger(
    log_dir: Path | str = 'logs',
    prefix: str = 'compilation',
    timestamp: datetime | None = None,
) -> tuple[logging.Logger, Path]:
    """Configures a logger writing timestamped compilation logs to `log_dir` and updates `latest_translation.log`.

    Returns:
        tuple[logging.Logger, Path]: The configured Logger and Path to timestamped log file.
    """
    directory = Path(log_dir)
    directory.mkdir(parents=True, exist_ok=True)

    ts = (timestamp or datetime.now()).strftime('%Y%m%d_%H%M%S')
    log_file = directory / f"{prefix}_{ts}.log"
    latest_file = directory / "latest_translation.log"

    logger = logging.getLogger(f"{LOGGER_NAME}.{ts}")
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    for h in list(logger.handlers):
        logger.removeHandler(h)
        h.close()

    formatter = logging.Formatter(
        '%(asctime)s [%(levelname)-5s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
    )

    fh_ts = logging.FileHandler(str(log_file), mode='w', encoding='utf-8')
    fh_ts.setLevel(logging.DEBUG)
    fh_ts.setFormatter(formatter)
    logger.addHandler(fh_ts)

    fh_latest = logging.FileHandler(str(latest_file), mode='w', encoding='utf-8')
    fh_latest.setLevel(logging.DEBUG)
    fh_latest.setFormatter(formatter)
    logger.addHandler(fh_latest)

    return logger, log_file


def log_batch_header(logger: logging.Logger, spec_source: Path, total_files: int, output_dir: Path) -> None:
    """Logs the start of a batch compilation run."""
    logger.info("=" * 86)
    logger.info("⚡ SpecToTest — Übersetzungsvorgang gestartet (Compiler & Code-Generierung)")
    logger.info("=" * 86)
    logger.info("Spezifikationsquelle: %s (%d Spezifikationsdateien gefunden)", spec_source, total_files)
    logger.info("Zielverzeichnis:      %s", output_dir)
    logger.info("-" * 86)


def log_spec_file_start(logger: logging.Logger, spec_path: Path, rel_dir: str) -> None:
    """Logs the parsing of a single specification file."""
    domain_tag = f"[{rel_dir}]" if rel_dir != "." else "[root]"
    logger.info("")
    logger.info(">>> %-12s Lese Spezifikation: %s (Format: %s)", domain_tag, spec_path.name, spec_path.suffix.upper())


def log_case_header(logger: logging.Logger, case_id: str, name: str, objective: str | None) -> None:
    """Logs test case metadata discovered by inbound parser."""
    logger.info("    ╔═ Testfall-ID: %s", case_id)
    logger.info("    ║  Name:        %s", name)
    if objective:
        logger.info("    ║  Testziel:    %s", objective)
    logger.info("    ╠─ Übersetzung der Spezifikationsschritte in typisierte Operationen:")


def log_step_translation(
    logger: logging.Logger,
    phase: str,
    line_no: int | str,
    step_num: int | str | None,
    description: str,
    mapping_id: str,
    operation_name: str,
    arguments: tuple | list | dict,
    expectation_target: int | str | None = None,
) -> None:
    """Logs the step-by-step translation from spec line to mapped Python operation."""
    num_str = f"{step_num}." if step_num is not None else "  "
    line_tag = f"Z.{line_no:<3}" if line_no else "    "

    # Format arguments
    if isinstance(arguments, dict):
        args_formatted = ", ".join(f"{k}={repr(v)}" for k, v in arguments.items())
    elif isinstance(arguments, (tuple, list)):
        args_formatted = ", ".join(f"{k}={repr(v)}" for k, v in arguments)
    else:
        args_formatted = str(arguments)

    binding_tag = ""
    if expectation_target is not None:
        binding_tag = f" ➔ [Erwartung gebunden an Aktion {expectation_target}]"

    logger.info(
        "    ║  %s %-12s | %-4s %-40s ➔ [%s] %s(%s)%s",
        line_tag,
        f"[{phase}]",
        num_str,
        f'"{description}"',
        mapping_id,
        operation_name,
        args_formatted,
        binding_tag,
    )


def log_loop_header(logger: logging.Logger, variable: str, items: tuple | list) -> None:
    """Logs the start of a FOR-loop block in specification."""
    logger.info("    ║  [FOR-LOOP]      | Variable: '%s' in %s", variable, list(items))


def log_code_emitted(logger: logging.Logger, case_id: str, output_path: Path, loc: int, ast_ok: bool) -> None:
    """Logs the successful generation and AST validation of Python test code."""
    status = "GÜLTIG (AST Syntax-Check OK)" if ast_ok else "SYNTAXFEHLER"
    logger.info("    ╠─ Python-Code-Generierung:")
    logger.info("    ║  Zieldatei:   %s", output_path)
    logger.info("    ║  Code-Umfang: %d Zeilen Python", loc)
    logger.info("    ╚═ AST-Status:  %s", status)


def log_compiled_case(logger: logging.Logger, case: Any, output_path: Path, source: str) -> None:
    """Logs full case translation trace and generated python metrics."""
    from tcg.core.model import BreakStatement, IfBlock, Loop, Step, SwitchBlock

    log_case_header(logger, case.id, case.name, case.objective)

    def _walk(items):
        for item in items:
            if isinstance(item, Step):
                op_name = getattr(item.contract, 'id', getattr(item.contract, 'name', 'unknown'))
                target = item.test_step if item.phase == 'EXPECTED' else None
                log_step_translation(
                    logger=logger,
                    phase=item.phase,
                    line_no=item.source.row,
                    step_num=item.test_step,
                    description=item.description,
                    mapping_id=item.mapping_id,
                    operation_name=op_name,
                    arguments=item.arguments,
                    expectation_target=target,
                )
            elif isinstance(item, Loop):
                log_loop_header(logger, item.variable, item.items)
                _walk(item.body)
            elif isinstance(item, IfBlock):
                for idx, branch in enumerate(item.branches):
                    keyword = "IF" if idx == 0 else "ELSE IF"
                    cond_str = branch.condition.render()
                    logger.info("    ║  [%-15s] | (%s)", keyword, cond_str)
                    _walk(branch.body)
                if item.else_body:
                    logger.info("    ║  [ELSE]           |")
                    _walk(item.else_body)
            elif isinstance(item, SwitchBlock):
                logger.info("    ║  [SWITCH]         | Variable: '%s'", item.expression)
                for case_item in item.cases:
                    logger.info("    ║  [CASE]           | Wert: %r", case_item.value)
                    _walk(case_item.body)
                if item.default_body:
                    logger.info("    ║  [DEFAULT]        |")
                    _walk(item.default_body)
            elif isinstance(item, BreakStatement):
                cond = item.condition.render() if item.condition else "True"
                logger.info("    ║  Z.%-3s [BREAK]       | if %s: break", item.source.row, cond)

    _walk(case.steps)
    loc = len(source.splitlines())
    log_code_emitted(logger, case.id, output_path, loc, True)


def log_batch_summary(
    logger: logging.Logger,
    total_specs: int,
    total_cases: int,
    total_steps: int,
    duration_s: float,
    log_file: Path,
) -> None:
    """Logs the final summary of the compilation run."""
    logger.info("")
    logger.info("=" * 86)
    logger.info("ZUSAMMENFASSUNG ÜBERSETZUNG:")
    logger.info("  • Verarbeitete Spezifikationen: %d", total_specs)
    logger.info("  • Erzeugte Testfälle:           %d", total_cases)
    logger.info("  • Übersetzte Fachschritte:      %d", total_steps)
    logger.info("  • Gesamtdauer Übersetzung:      %.3f s", duration_s)
    logger.info("  • Übersetzungs-Logdatei:        %s", log_file.resolve())
    logger.info("=" * 86)
