"""Communication view: loaded descriptions, networks, resources and bench capabilities.

This is a panel inside the existing catalog workspace, not a separate application per
bus type. It answers, for the active project:

* which descriptions were loaded, and which failed (with the reason),
* which networks and communication objects are available,
* the qualified reference and origin of a selected resource,
* which bench capabilities the configured bench does not offer.
"""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QSizePolicy,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from tcg.comm.capabilities import bench_capabilities, known_capabilities, missing_for
from tcg.gui.models import MappingStudioState
from tcg.gui.styles import get_monospace_font, get_theme_tokens


class CommunicationWorkspace(QWidget):
    """Shows the active project's communication catalog and its status."""

    def __init__(self, state: MappingStudioState, on_change: Callable[[], None] | None = None,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.state = state
        self.on_change = on_change
        self.dark_theme = True
        self.setup_ui()
        self.refresh()

    # --- construction -----------------------------------------------------
    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        self.lbl_status = QLabel()
        self.lbl_status.setWordWrap(True)
        self.lbl_status.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.lbl_status.setSizePolicy(QSizePolicy.Policy.Preferred,
                                      QSizePolicy.Policy.Fixed)
        layout.addWidget(self.lbl_status)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(QLabel('<b>Geladene Beschreibungen</b>'))
        self.sources_tree = QTreeWidget()
        self.sources_tree.setHeaderLabels(['Datei', 'Netzwerk', 'Format', 'Status'])
        sources_header = self.sources_tree.header()
        sources_header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        sources_header.setStretchLastSection(True)
        self.sources_tree.setColumnWidth(0, 150)
        self.sources_tree.setColumnWidth(1, 110)
        self.sources_tree.setColumnWidth(2, 70)
        left_layout.addWidget(self.sources_tree)

        left_layout.addWidget(QLabel('<b>Testbench-Fähigkeiten</b>'))
        self.capabilities_tree = QTreeWidget()
        self.capabilities_tree.setHeaderLabels(['Fähigkeit', 'Status'])
        capability_header = self.capabilities_tree.header()
        capability_header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        capability_header.setStretchLastSection(True)
        self.capabilities_tree.setColumnWidth(0, 150)
        left_layout.addWidget(self.capabilities_tree)
        splitter.addWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        header = QHBoxLayout()
        header.addWidget(QLabel('<b>Netzwerke und Kommunikationsobjekte</b>'))
        self.search = QLineEdit()
        self.search.setPlaceholderText('Filter (Name, Netzwerk, Art) ...')
        self.search.textChanged.connect(self.populate_resources)
        header.addWidget(self.search, stretch=1)
        right_layout.addLayout(header)

        self.resource_tree = QTreeWidget()
        self.resource_tree.setHeaderLabels(['Objekt', 'Art', 'Qualifizierte Referenz',
                                            'Einheit / Zustände', 'Herkunft'])
        header_view = self.resource_tree.header()
        header_view.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        # The qualified reference is the point of this view, so give it the room.
        header_view.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header_view.setStretchLastSection(False)
        self.resource_tree.setColumnWidth(0, 220)
        self.resource_tree.setColumnWidth(1, 80)
        self.resource_tree.setColumnWidth(3, 160)
        self.resource_tree.setColumnWidth(4, 130)
        right_layout.addWidget(self.resource_tree)

        self.lbl_detail = QLabel('Wähle ein Kommunikationsobjekt, um Herkunft und '
                                 'qualifizierte Referenz zu sehen.')
        self.lbl_detail.setWordWrap(True)
        self.lbl_detail.setFont(get_monospace_font(9))
        right_layout.addWidget(self.lbl_detail)
        self.resource_tree.itemSelectionChanged.connect(self.on_resource_selected)
        splitter.addWidget(right)

        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        self.splitter = splitter
        layout.addWidget(splitter, stretch=1)

    # --- data -------------------------------------------------------------
    @property
    def catalog(self):
        return self.state.catalog

    def refresh(self):
        self.populate_status()
        self.populate_sources()
        self.populate_resources()
        self.populate_capabilities()

    def populate_status(self):
        tokens = get_theme_tokens(self.dark_theme)
        if self.state.catalog_error:
            colour = tokens['error']
            text = (f'Kommunikationskatalog nicht verfügbar - '
                    f'{self.state.catalog_error}. Kommunikationsabhängige '
                    f'Operationen sind deaktiviert.')
        elif self.catalog is None:
            colour = tokens['text_muted']
            text = ('Für dieses Projekt ist keine Kommunikationsbeschreibung '
                    'konfiguriert. Symbolische Signalzustände und bus-spezifische '
                    'Operationen stehen nicht zur Verfügung.')
        else:
            colour = tokens['success']
            text = (f'Kommunikationskatalog geladen: {len(self.catalog.resources)} '
                    f'Objekte in {len(self.catalog.networks())} Netzwerk(en) '
                    f'({", ".join(self.catalog.networks())}).')
        self.lbl_status.setText(text)
        self.lbl_status.setStyleSheet(f'color: {colour};')

    def populate_sources(self):
        tokens = get_theme_tokens(self.dark_theme)
        self.sources_tree.clear()
        if self.state.catalog_error:
            item = QTreeWidgetItem(['(Laden fehlgeschlagen)', '-', '-', 'Fehler'])
            item.setToolTip(3, self.state.catalog_error)
            self.sources_tree.addTopLevelItem(item)
            return
        if self.catalog is None:
            self.sources_tree.addTopLevelItem(
                QTreeWidgetItem(['(keine konfiguriert)', '-', '-', 'Nicht konfiguriert']))
            return
        for source in self.catalog.sources:
            status = 'Geladen' if source.loaded else 'Fehler'
            item = QTreeWidgetItem([source.name, source.network, source.format,
                                    f'{status} ({source.resource_count} Objekte)'
                                    if source.loaded else status])
            item.setToolTip(0, source.path)
            item.setToolTip(3, source.status_text())
            self.sources_tree.addTopLevelItem(item)

    def populate_resources(self):
        self.resource_tree.clear()
        if self.catalog is None:
            return
        needle = self.search.text().strip().casefold()
        for network in self.catalog.networks():
            network_item = QTreeWidgetItem([network, '', '', '', ''])
            matched = 0
            by_kind = {}
            for resource in self.catalog.resources_of(network=network):
                by_kind.setdefault(str(resource.kind), []).append(resource)
            for kind in sorted(by_kind):
                kind_item = QTreeWidgetItem([kind, '', '', '', ''])
                kind_matched = 0
                for resource in sorted(by_kind[kind], key=lambda r: r.name):
                    haystack = (f'{resource.name} {resource.network} {resource.kind} '
                                f'{resource.qualified_name}').casefold()
                    if needle and needle not in haystack:
                        continue
                    encoding = resource.encoding
                    if encoding is None:
                        detail = ''
                    elif encoding.declared_states:
                        detail = ', '.join(encoding.declared_states)
                    else:
                        detail = encoding.unit or ''
                        if encoding.is_scaled:
                            detail = (f'{detail} (Faktor {encoding.factor}, '
                                      f'Offset {encoding.offset})').strip()
                    child = QTreeWidgetItem([
                        resource.name, str(resource.kind), resource.qualified_name,
                        detail, resource.source])
                    child.setData(0, Qt.ItemDataRole.UserRole, resource.qualified_name)
                    child.setToolTip(2, resource.describe())
                    ambiguous = self.catalog.is_address_colliding(resource)
                    if ambiguous:
                        child.setToolTip(0, 'Adapteradresse ist mehrfach belegt: '
                                            'setze adapter_naming oder adapter_names '
                                            'für eine der Beschreibungen.')
                        child.setText(0, f'{resource.name} (Adresskonflikt)')
                    kind_item.addChild(child)
                    kind_matched += 1
                if kind_matched:
                    kind_item.setText(1, f'{kind_matched}')
                    network_item.addChild(kind_item)
                    matched += kind_matched
            if matched:
                network_item.setText(1, f'{matched} Objekte')
                self.resource_tree.addTopLevelItem(network_item)
        self.resource_tree.expandToDepth(0 if needle else 0)

    def populate_capabilities(self):
        self.capabilities_tree.clear()
        bench = self.current_bench()
        if bench is None:
            self.capabilities_tree.addTopLevelItem(
                QTreeWidgetItem(['(kein Prüfstand konfiguriert)', 'Unbekannt']))
            return
        available = bench_capabilities(bench)
        for name in sorted(known_capabilities()):
            status = 'Verfügbar' if name in available else 'Nicht verfügbar'
            item = QTreeWidgetItem([name, status])
            item.setToolTip(1, f'{name}: {status} auf {getattr(bench, "BENCH_NAME", "?")}')
            self.capabilities_tree.addTopLevelItem(item)

    def current_bench(self):
        """Instantiate the configured simulation bench, if one can be built."""
        try:
            from pathlib import Path

            from tcg.adapters.outbound.dummy_bench import (
                ControlDeskDummyBench,
                DummyBench,
                VectorDummyBench,
                load_config,
            )
            profile_config = self.state.profile_config
            if profile_config is None or not profile_config.bench_config:
                return None
            path = profile_config.resolve_path(profile_config.bench_config)
            if not Path(path).is_file():
                return None
            config = load_config(Path(path), self.state.profile)
            kinds = {'vector': VectorDummyBench, 'controldesk': ControlDeskDummyBench}
            return kinds.get(profile_config.bench_type, DummyBench)(config)
        except Exception:
            return None

    def missing_capabilities_for(self, cases):
        """Capabilities the configured bench does not offer for `cases`."""
        bench = self.current_bench()
        if bench is None:
            return ()
        from tcg.comm.capabilities import required_capabilities
        needed = frozenset().union(*required_capabilities(cases).values()) \
            if cases else frozenset()
        return missing_for(needed, bench_capabilities(bench))

    def on_resource_selected(self):
        items = self.resource_tree.selectedItems()
        if not items:
            return
        reference = items[0].data(0, Qt.ItemDataRole.UserRole)
        if not reference or self.catalog is None:
            self.lbl_detail.setText('Wähle ein Kommunikationsobjekt, um Herkunft und '
                                    'qualifizierte Referenz zu sehen.')
            return
        resource = self.catalog.find(reference)
        lines = [
            f'Qualifizierte Referenz : {resource.qualified_name}',
            f'Technologie / Art      : {resource.technology} / {resource.kind}',
            f'Netzwerk               : {resource.network}',
            f'Herkunft               : {resource.source}',
        ]
        if resource.container:
            lines.append(f'Enthalten in           : {resource.container}')
        encoding = resource.encoding
        if encoding is not None:
            lines.append(f'Einheit                : {encoding.unit or "-"}')
            lines.append(f'Skalierung             : physikalisch = roh * '
                         f'{encoding.factor} + {encoding.offset}')
            if encoding.declared_states:
                lines.append(f'Symbolische Zustände   : '
                             f'{", ".join(encoding.declared_states)}')
        lines.append(f'Adapteradresse         : {self.catalog.adapter_address(resource)}')
        if self.catalog.is_address_colliding(resource):
            lines.append('Hinweis                : Adapteradresse mehrfach belegt; '
                         'adapter_naming oder adapter_names setzen.')
        self.lbl_detail.setText('\n'.join(lines))

    def set_theme(self, dark_theme: bool):
        self.dark_theme = dark_theme
        self.refresh()
