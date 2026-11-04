"""Interactive Sentence Matching Playground for SpecToTest GUI."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from tcg.gui.models import MappingStudioState


class SentenceTesterWidget(QWidget):
    """Interactive sentence testing and verification playground."""

    def __init__(self, state: MappingStudioState, parent: QWidget | None = None):
        super().__init__(parent)
        self.state = state

        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        # 1. Header & Quick Presets
        header_box = QHBoxLayout()
        title_lbl = QLabel("<b>🎯 Interaktiver Satzprüfer & Matcher-Playground</b>")
        title_lbl.setFont(QFont("", 11, QFont.Weight.Bold))
        header_box.addWidget(title_lbl)

        header_box.addStretch()

        header_box.addWidget(QLabel("Beispiele einfügen:"))
        self.preset_combo = QComboBox()
        self.preset_combo.addItem("-- Beispiel wählen --", "")
        self.preset_combo.addItem("Batteriespannung = 13.8V", "Batteriespannung = 13.8V")
        self.preset_combo.addItem("Versorgung auf 12 V setzen", "Versorgung auf 12 V setzen")
        self.preset_combo.addItem("Warte 500 ms", "Warte 500 ms")
        self.preset_combo.addItem("Zündung an", "Zündung an")
        self.preset_combo.addItem("Fehlerspeicher BCM1 löschen", "Fehlerspeicher BCM1 löschen")
        self.preset_combo.addItem("Fehlerspeichereintrag DTC00173 eingetragen", "Fehlerspeichereintrag DTC00173 eingetragen")
        self.preset_combo.addItem("CAN-Signal Engine_Speed = 2500 rpm", "CAN-Signal Engine_Speed = 2500 rpm")
        self.preset_combo.currentIndexChanged.connect(self.on_preset_selected)
        header_box.addWidget(self.preset_combo)

        layout.addLayout(header_box)

        # 2. Input Box & Controls
        input_box = QHBoxLayout()
        input_box.setSpacing(8)

        self.sentence_edit = QLineEdit()
        self.sentence_edit.setPlaceholderText("Gib hier einen natürlichen Spezifikationssatz ein, z.B. 'Batteriespannung = 13.8V'...")
        self.sentence_edit.setFont(QFont("Monospace", 10))
        self.sentence_edit.returnPressed.connect(self.run_test)
        input_box.addWidget(self.sentence_edit, stretch=3)

        input_box.addWidget(QLabel("Prüf-Phase:"))
        self.phase_combo = QComboBox()
        self.phase_combo.addItem("Beliebig", None)
        self.phase_combo.addItem("ACTION", "ACTION")
        self.phase_combo.addItem("PRECONDITION", "PRECONDITION")
        self.phase_combo.addItem("EXPECTED", "EXPECTED")
        self.phase_combo.addItem("CLEANUP", "CLEANUP")
        input_box.addWidget(self.phase_combo)

        self.btn_test = QPushButton("Satz prüfen")
        self.btn_test.setStyleSheet("background-color: #0d6efd; color: white; font-weight: bold; padding: 6px 16px; border-radius: 4px;")
        self.btn_test.clicked.connect(self.run_test)
        input_box.addWidget(self.btn_test)

        layout.addLayout(input_box)

        # 3. Output Card
        self.result_card = QGroupBox("Ergebnis der Satzanalyse")
        res_layout = QVBoxLayout(self.result_card)

        self.status_lbl = QLabel("Gib einen Satz ein und klicke auf 'Satz prüfen'.")
        self.status_lbl.setWordWrap(True)
        self.status_lbl.setTextFormat(Qt.TextFormat.RichText)
        res_layout.addWidget(self.status_lbl)

        self.details_edit = QTextEdit()
        self.details_edit.setReadOnly(True)
        self.details_edit.setFont(QFont("Monospace", 9))
        self.details_edit.setMaximumHeight(160)
        res_layout.addWidget(self.details_edit)

        layout.addWidget(self.result_card)

    def on_preset_selected(self):
        txt = self.preset_combo.currentData()
        if txt:
            self.sentence_edit.setText(txt)
            self.run_test()

    def set_sentence(self, text: str):
        self.sentence_edit.setText(text)
        self.run_test()

    def run_test(self):
        sentence = self.sentence_edit.text().strip()
        phase = self.phase_combo.currentData()

        if not sentence:
            self.status_lbl.setText("<span style='color: #888;'>Bitte einen Satz eingeben.</span>")
            self.details_edit.clear()
            return

        res = self.state.test_sentence(sentence, phase=phase)

        if res['success']:
            op_name = res['operation']
            map_id = res['mapping_id']
            tmpl = res['template']
            args = res['arguments']
            phases = res['allowed_phases']
            phase_valid = res['phase_valid']
            phase_msg = res.get('phase_msg')

            # Render summary banner
            if phase_valid:
                badge_style = "color: #198754; font-weight: bold;"
                status_icon = "✅"
                verdict_text = "Erfolgreich aufgelöst & validiert"
            else:
                badge_style = "color: #dc3545; font-weight: bold;"
                status_icon = "⚠️"
                verdict_text = f"Phasenkonflikt: {phase_msg}"

            self.status_lbl.setText(
                f"<div style='font-size: 13px;'>"
                f"{status_icon} <span style='{badge_style}'>{verdict_text}</span><br>"
                f"<b>Mapping:</b> <code>{map_id}</code> (Template: <i>\"{tmpl}\"</i>)<br>"
                f"<b>Aufgerufene Operation:</b> <code>{op_name}</code> (Erlaubt: {', '.join(phases)})"
                f"</div>"
            )

            # Render code & arguments details
            call_args = ", ".join(f"{k}={v!r}" for k, v in args.items())
            details = [
                f"# Generierter Python-Operationsaufruf:",
                f"{op_name}(bench, {call_args})\n",
                f"# Extrahierte und typkonvertierte Argumente:",
            ]
            for k, v in args.items():
                details.append(f"  • {k} = {v!r} (Typ: {type(v).__name__})")

            self.details_edit.setPlainText("\n".join(details))
        else:
            err = res.get('error', 'Unbekannter Fehler')
            self.status_lbl.setText(
                f"<div style='color: #dc3545; font-weight: bold;'>"
                f"❌ Keine Übereinstimmung oder Validierungsfehler:<br>"
                f"<span style='font-weight: normal; color: #842029;'>{err}</span>"
                f"</div>"
            )
            self.details_edit.setPlainText(
                f"# Fehlermeldung des Mapping-Compilers:\n{err}\n\n"
                f"# Tipp: Prüfe, ob die Syntax des Satzes exakt mit einem Template übereinstimmt "
                f"oder ob Einheiten / Grenzwerte des Parameters verletzt wurden."
            )

