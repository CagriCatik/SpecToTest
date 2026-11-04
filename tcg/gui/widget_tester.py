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
        title_lbl = QLabel("<b>Satzprüfer & Matcher-Labor</b>")
        title_lbl.setFont(QFont("", 11, QFont.Weight.Bold))
        header_box.addWidget(title_lbl)

        header_box.addStretch()

        header_box.addWidget(QLabel("Beispiele einfügen:"))
        self.preset_combo = QComboBox()
        self.preset_combo.addItem("-- Beispiel wählen --", "")
        self.preset_combo.addItem("Batteriespannung = 13.8V", "Batteriespannung = 13.8V")
        self.preset_combo.addItem("Versorgung auf 12 V setzen", "Versorgung auf 12 V setzen")
        self.preset_combo.addItem("Warte 500 ms", "Warte 500 ms")
        self.preset_combo.addItem("Warte missing (Kontextvariable)", "Warte missing")
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
        self.btn_test.setStyleSheet("background-color: #2563eb; color: white; font-weight: bold; padding: 6px 16px; border-radius: 4px;")
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
            self.status_lbl.setText("<span style='color: #64748b;'>Bitte einen Satz eingeben.</span>")
            self.details_edit.clear()
            return

        res = self.state.test_sentence(sentence, phase=phase)

        if res['success']:
            op_name = res['operation']
            map_id = res['mapping_id']
            tmpl = res['template']
            args = res['arguments']
            phases = res['allowed_phases']

            if res.get('is_contextual_variable'):
                # Variable context warning as requested by the reviewer
                status_text = res.get('status_text', "Satzmuster erkannt; Variable benötigt einen gültigen Kontext (z.B. Schleife).")
                self.status_lbl.setText(
                    f"<div style='font-size: 13px;'>"
                    f"<span style='color: #f59e0b; font-weight: bold;'>Hinweis:</span> {status_text}<br>"
                    f"<b>Mapping:</b> <code>{map_id}</code> (Template: <i>\"{tmpl}\"</i>)<br>"
                    f"<b>Ziel-Operation:</b> <code>{op_name}</code>"
                    f"</div>"
                )

                var_names = ", ".join(f"'{v}'" for v in res.get('variable_names', []))
                details = [
                    f"# Satzmuster passt syntaktisch zu Mapping '{map_id}':",
                    f"# Die Eingabe enthält die Variable(n): {var_names}\n",
                    f"# WICHTIG:",
                    f"# Einzelsätze mit Variablen sind keine selbstständig gültigen Testschritte.",
                    f"# Die Variable {var_names} ist nur innerhalb eines gültigen Schleifenkontexts",
                    f"# (z.B. 'FOR (missing; [1 s, 2 s]) ... END FOR') zulässig.\n",
                    f"# Extrahierte Argumente:",
                ]
                for k, v in args.items():
                    details.append(f"  • {k} = {v!r}")

                self.details_edit.setPlainText("\n".join(details))
                return

            phase_valid = res['phase_valid']
            phase_msg = res.get('phase_msg')

            # Render summary banner
            if phase_valid:
                badge_style = "color: #10b981; font-weight: bold;"
                verdict_text = "Erfolgreich aufgelöst und Parameter validiert"
            else:
                badge_style = "color: #ef4444; font-weight: bold;"
                verdict_text = f"Phasenkonflikt: {phase_msg}"

            self.status_lbl.setText(
                f"<div style='font-size: 13px;'>"
                f"<span style='{badge_style}'>{verdict_text}</span><br>"
                f"<b>Mapping:</b> <code>{map_id}</code> (Template: <i>\"{tmpl}\"</i>)<br>"
                f"<b>Aufgerufene Operation:</b> <code>{op_name}</code> (Erlaubte Phasen: {', '.join(phases)})"
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
                f"<div style='color: #ef4444; font-weight: bold;'>"
                f"Keine Übereinstimmung oder Validierungsfehler:<br>"
                f"<span style='font-weight: normal; color: #b91c1c;'>{err}</span>"
                f"</div>"
            )
            self.details_edit.setPlainText(
                f"# Fehlermeldung des Mapping-Compilers:\n{err}\n\n"
                f"# Hinweis: Prüfe, ob die Syntax des Satzes exakt mit einem Template übereinstimmt "
                f"oder ob Einheiten / Grenzwerte des Parameters verletzt wurden."
            )
