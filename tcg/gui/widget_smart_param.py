"""Smart input widgets for typed parameters (Quantities, Booleans, Resources)."""
from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QWidget,
)


def _as_tuple(value):
    """Treat one technology/kind restriction and several restrictions uniformly."""
    if value is None:
        return ()
    return tuple(value) if isinstance(value, (tuple, list, set, frozenset)) else (value,)


def _communication_reference_options(parameter_type: Any) -> list[Any] | None:
    """Return catalog resources allowed by a bound communication reference.

    ``ResourceReference`` deliberately lives in ``operations.comm_types`` rather
    than the GUI.  Structural detection keeps this widget generic while preserving
    its technology- and object-kind restrictions.
    """
    if not (hasattr(parameter_type, 'catalog') and hasattr(parameter_type, 'kinds')):
        return None

    catalog = parameter_type.catalog
    if not getattr(catalog, 'configured', False):
        return []
    technologies = _as_tuple(getattr(parameter_type, 'technology', None))
    kinds = _as_tuple(parameter_type.kinds)
    return sorted(
        (resource for resource in catalog.resources
         if (not technologies or resource.technology in technologies)
         and (not kinds or resource.kind in kinds)),
        key=lambda resource: resource.qualified_name.casefold(),
    )


class SmartParamWidget(QWidget):
    """Container holding inputs for a parameter placeholder."""

    def __init__(
        self,
        val_widget: QWidget,
        unit_widget: QComboBox | None = None,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.val_widget = val_widget
        self.unit_widget = unit_widget
        self.spinbox = val_widget  # convenient alias for test access
        self.unit_combo = unit_widget

        layout.addWidget(self.val_widget, stretch=2)
        if self.unit_widget:
            layout.addWidget(self.unit_widget)

    def get_value_string(self) -> str:
        if isinstance(self.val_widget, QDoubleSpinBox):
            val = self.val_widget.value()
            return str(int(val)) if val.is_integer() else str(val)
        elif isinstance(self.val_widget, QComboBox):
            return str(self.val_widget.currentData() or self.val_widget.currentText())
        elif isinstance(self.val_widget, QLineEdit):
            return self.val_widget.text().strip()
        return ""

    def get_unit_string(self) -> str:
        if self.unit_widget and isinstance(self.unit_widget, QComboBox):
            return str(self.unit_widget.currentData() or "")
        return ""


def build_smart_param_widget(
    param_spec: Any,
    ph_name: str,
    profile_resources: dict[str, list[str]],
    on_change: Any,
) -> SmartParamWidget:
    """Build a typed SmartParamWidget based on contract parameter specification."""
    if not param_spec:
        line_edit = QLineEdit("10")
        line_edit.textChanged.connect(on_change)
        return SmartParamWidget(line_edit, None)

    t = param_spec.type

    # 1. Communication references are selected from the active catalog, never
    # typed as an arbitrary placeholder.  A qualified reference remains stable
    # even when several networks contain a signal with the same bare name.
    communication_options = _communication_reference_options(t)
    if communication_options is not None:
        combo = QComboBox()
        for resource in communication_options:
            combo.addItem(resource.qualified_name, resource.qualified_name)
            combo.setItemData(combo.count() - 1, resource.describe(),
                              role=Qt.ItemDataRole.ToolTipRole)
        if not communication_options:
            profile_kind = getattr(t, 'profile_kind', '')
            legacy_options = profile_resources.get(profile_kind, [])
            for resource_name in legacy_options:
                combo.addItem(resource_name, resource_name)
        if combo.count() == 0:
            combo.addItem('(keine passenden Kommunikationsobjekte geladen)', '')
            combo.setEnabled(False)
        combo.setMaxVisibleItems(12)
        combo.currentIndexChanged.connect(on_change)
        return SmartParamWidget(combo, None)

    # 2. Quantity with unit (voltage, time, can_signal)
    if hasattr(t, 'unit') and t.unit:
        spinbox = QDoubleSpinBox()
        spinbox.setRange(0, 1000000)
        spinbox.setDecimals(2)

        unit_combo = QComboBox()
        units = [factor[0] for factor in getattr(t, 'factors', ())]
        if not units and t.unit:
            units = [t.unit]
        for u in units:
            unit_combo.addItem(u if u else "(keine Einheit)", u)

        if getattr(t, 'dimension', None) == 'voltage':
            spinbox.setValue(12)
        elif getattr(t, 'dimension', None) == 'time':
            spinbox.setValue(500 if "ms" in units else 1)
            if "ms" in units:
                unit_combo.setCurrentText("ms")
        else:
            spinbox.setValue(10)

        spinbox.valueChanged.connect(on_change)
        unit_combo.currentIndexChanged.connect(on_change)
        return SmartParamWidget(spinbox, unit_combo)

    # 3. Boolean ('an' / 'aus', 'aktiv' / 'inaktiv')
    if hasattr(t, 'true_value') and hasattr(t, 'false_value'):
        combo = QComboBox()
        combo.addItem(t.true_value, t.true_value)
        combo.addItem(t.false_value, t.false_value)
        combo.currentIndexChanged.connect(on_change)
        return SmartParamWidget(combo, None)

    # 4. Resource profile values (controller, diagnostic_code, signal, screen)
    if hasattr(t, 'kind') and t.kind:
        res_list = profile_resources.get(t.kind, [])
        if res_list:
            combo = QComboBox()
            for r in res_list:
                combo.addItem(r, r)
            combo.currentIndexChanged.connect(on_change)
            return SmartParamWidget(combo, None)

    # Default string/decimal input
    default_text = "10" if "value" in ph_name or "wert" in ph_name else "default"
    line_edit = QLineEdit(default_text)
    line_edit.textChanged.connect(on_change)
    return SmartParamWidget(line_edit, None)

