"""Event-driven background analysis engine with revision tracking and multi-tier problem classification."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

from tcg.core.profile import ResourceProfile
from tcg.gui.facade import CompilationError, CompilationFacade, CompilationResult, MappingImpact


@dataclass
class InspectionProblem:
    """A problem classified across the 3 inspection tiers (Schritt, Dokument, Projekt)."""
    level: str         # 'Schritt' | 'Dokument' | 'Projekt'
    severity: str      # 'Fehler' | 'Warnung' | 'Info'
    file_name: str
    line: int | None
    message: str
    file_path: Path | None = None
    details: str = ""


class DocAnalysisRunnable(QRunnable):
    """Worker task for asynchronous specification document compilation."""

    def __init__(
        self,
        text: str,
        source_name: str,
        registry: dict[str, Any],
        mapping_dicts: list[dict[str, Any]],
        profile: ResourceProfile,
        revision: int,
        on_success: Callable[[CompilationResult, int], None],
        on_error: Callable[[Exception, int], None],
    ):
        super().__init__()
        self.text = text
        self.source_name = source_name
        self.registry = registry
        self.mapping_dicts = mapping_dicts
        self.profile = profile
        self.revision = revision
        self.on_success = on_success
        self.on_error = on_error

    def run(self):
        try:
            result = CompilationFacade.compile_text(
                text=self.text,
                source_name=self.source_name,
                registry=self.registry,
                mapping_dicts=self.mapping_dicts,
                profile=self.profile,
                strict_project_check=True,
            )
            self.on_success(result, self.revision)
        except Exception as e:
            self.on_error(e, self.revision)


class ProjectAnalysisRunnable(QRunnable):
    """Worker task for asynchronous project-wide impact and consistency analysis."""

    def __init__(
        self,
        specs_files: list[Path],
        registry: dict[str, Any],
        mapping_dicts: list[dict[str, Any]],
        profile: ResourceProfile,
        revision: int,
        on_success: Callable[[dict[str, MappingImpact], list[InspectionProblem], int], None],
        on_error: Callable[[Exception, int], None],
    ):
        super().__init__()
        self.specs_files = specs_files
        self.registry = registry
        self.mapping_dicts = mapping_dicts
        self.profile = profile
        self.revision = revision
        self.on_success = on_success
        self.on_error = on_error

    def run(self):
        try:
            # 1. Project-wide duplicate ID conflicts
            problems: list[InspectionProblem] = []
            id_counts: dict[str, int] = {}
            for m in self.mapping_dicts:
                mid = m.get('id', '').strip()
                if mid:
                    id_counts[mid] = id_counts.get(mid, 0) + 1

            for mid, count in id_counts.items():
                if count > 1:
                    problems.append(
                        InspectionProblem(
                            level='Projekt',
                            severity='Fehler',
                            file_name="Mappings",
                            line=None,
                            message=f"Projektweiter Konflikt: Mapping-ID '{mid}' ist {count}x definiert.",
                            details="Mehrfach vergebene Mapping-IDs blockieren die Übersetzung.",
                        )
                    )

            # 2. Analyze usage and compile each specification to detect project-wide impacts
            impacts = CompilationFacade.analyze_impact(
                specs_files=self.specs_files,
                registry=self.registry,
                mapping_dicts=self.mapping_dicts,
                profile=self.profile,
            )

            # 3. Check for failed files (unparseable or syntax errors)
            for file_path in self.specs_files:
                try:
                    content = file_path.read_text(encoding='utf-8-sig')
                    res = CompilationFacade.compile_text(
                        text=content,
                        source_name=file_path.name,
                        registry=self.registry,
                        mapping_dicts=self.mapping_dicts,
                        profile=self.profile,
                        strict_project_check=False,
                    )
                    if not res.success:
                        for err in res.errors:
                            problems.append(
                                InspectionProblem(
                                    level='Projekt',
                                    severity='Fehler',
                                    file_name=file_path.name,
                                    file_path=file_path,
                                    line=err.line,
                                    message=err.message,
                                    details=res.summary,
                                )
                            )
                except Exception as e:
                    problems.append(
                        InspectionProblem(
                            level='Projekt',
                            severity='Fehler',
                            file_name=file_path.name,
                            file_path=file_path,
                            line=None,
                            message=f"Konnte Datei nicht lesen: {e}",
                        )
                    )

            self.on_success(impacts, problems, self.revision)
        except Exception as e:
            self.on_error(e, self.revision)


class BackgroundAnalysisManager(QObject):
    """Coordinates background analysis jobs with revisions and protection against stale results."""

    sig_doc_analysis_started = Signal(int)  # revision
    sig_doc_analysis_finished = Signal(object, int)  # CompilationResult, revision
    sig_doc_analysis_failed = Signal(str, int)  # error_msg, revision

    sig_project_analysis_started = Signal(int)  # revision
    sig_project_analysis_finished = Signal(object, list, int)  # impacts, problems, revision
    sig_project_analysis_failed = Signal(str, int)  # error_msg, revision

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self.current_doc_revision: int = 0
        self.current_project_revision: int = 0
        self.thread_pool = QThreadPool.globalInstance()

    def schedule_doc_analysis(
        self,
        text: str,
        source_name: str,
        registry: dict[str, Any],
        mapping_dicts: list[dict[str, Any]],
        profile: ResourceProfile,
    ) -> int:
        """Schedule an asynchronous document compilation with a new revision."""
        self.current_doc_revision += 1
        rev = self.current_doc_revision
        self.sig_doc_analysis_started.emit(rev)

        # Create immutable snapshots of mappings
        copied_mappings = [dict(m) for m in mapping_dicts]

        task = DocAnalysisRunnable(
            text=text,
            source_name=source_name,
            registry=registry,
            mapping_dicts=copied_mappings,
            profile=profile,
            revision=rev,
            on_success=self._on_doc_success,
            on_error=self._on_doc_error,
        )
        self.thread_pool.start(task)
        return rev

    def schedule_project_analysis(
        self,
        specs_files: list[Path],
        registry: dict[str, Any],
        mapping_dicts: list[dict[str, Any]],
        profile: ResourceProfile,
    ) -> int:
        """Schedule an asynchronous project-wide impact analysis with a new revision."""
        self.current_project_revision += 1
        rev = self.current_project_revision
        self.sig_project_analysis_started.emit(rev)

        copied_mappings = [dict(m) for m in mapping_dicts]
        task = ProjectAnalysisRunnable(
            specs_files=list(specs_files),
            registry=registry,
            mapping_dicts=copied_mappings,
            profile=profile,
            revision=rev,
            on_success=self._on_project_success,
            on_error=self._on_project_error,
        )
        self.thread_pool.start(task)
        return rev

    def _on_doc_success(self, result: CompilationResult, revision: int):
        self.sig_doc_analysis_finished.emit(result, revision)

    def _on_doc_error(self, err: Exception, revision: int):
        self.sig_doc_analysis_failed.emit(str(err), revision)

    def _on_project_success(self, impacts: dict[str, MappingImpact], problems: list[InspectionProblem], revision: int):
        self.sig_project_analysis_finished.emit(impacts, problems, revision)

    def _on_project_error(self, err: Exception, revision: int):
        self.sig_project_analysis_failed.emit(str(err), revision)
