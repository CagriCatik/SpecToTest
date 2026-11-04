# 04 — Operationskatalog & Verträge

Dieses Dokument beschreibt den formalen Aufbau des **Operationskatalogs** (`operations/`), das Vertragssystem (`OperationContract`) sowie den automatisierten Phasenschutz, der fehlerhafte oder gefährliche Aufrufe zur Kompilierzeit verhindert.

---

## 1. Philosophie: Trennung von Vertrag und Implementierung

In **SpecToTest** sind Testoperationen gewöhnliche Python-Funktionen, die über einen Prüfstands-Port (`bench`) Aktionen ausführen oder Zustände abfragen. Sie enthalten **keinerlei** reguläre Ausdrücke, Mappings oder Kenntnisse über die Spezifikationsdatei.

Die Brücke zwischen dem generischen Compiler und der Python-Funktion bildet der **`OperationContract`**:
- Er deklariert die geforderten Parameter, deren Typen und Standardwerte.
- Er legt verbindlich fest, in welchen Phasen des Testfalls die Operation aufgerufen werden darf.

---

## 2. Aufbau eines `OperationContract`

Ein Vertrag wird in `operations/registry.py` oder einem fachspezifischen Modul definiert:

```python
from tcg.core.contracts import OperationContract, ParameterSpec, SETUP, STIMULUS, CHECK, TEARDOWN
from operations.supply import set_supply
from operations.registry import SUPPLY_VOLTAGE

CONTRACT_SET_SUPPLY = OperationContract(
    name='set_supply',
    function=set_supply,
    docstring='Stellt die geregelte Batteriespannung am Prüfstands-Netzteil ein.',
    parameters=(
        ParameterSpec(name='value', type=SUPPLY_VOLTAGE, required=True),
    ),
    phases=SETUP | STIMULUS | TEARDOWN,
)
```

### Bestandteile des Vertrags
1. **`name`:** Eindeutiger Identifikator der Operation (Referenzziel im TOML-Mapping `operation = "set_supply"`).
2. **`function`:** Die tatsächliche Python-Implementierungsfunktion.
3. **`docstring`:** Verständliche Dokumentation (wird in der GUI im Inspektor und in generierten Skripten angezeigt).
4. **`parameters`:** Tupel von `ParameterSpec`-Objekten mit Name, Typ (`Quantity`, `Boolean`, `Resource`, etc.), Optionalität und Defaultwert.
5. **`phases`:** Bitmaske der zulässigen Ausführungsphasen.

---

## 3. Phasenschutz & Phasenmatrix

Operationen haben unterschiedliche Seiteneffekte. Eine Assertion (Zustandsprüfung) darf das System nicht manipulieren, während eine destruktive Stimulationsoperation nicht im Erwartungsabschnitt stehen darf:

```mermaid
flowchart TD
    Section["Spezifikationsabschnitt"] --> Decision{"Welcher Abschnitt?"}
    
    Decision -->|"Precondition"| P_Check["Gefordert: SETUP Phase"]
    Decision -->|"Action"| A_Check["Gefordert: STIMULUS Phase"]
    Decision -->|"Expected Result"| E_Check["Gefordert: CHECK Phase"]
    Decision -->|"Postcondition"| T_Check["Gefordert: TEARDOWN Phase"]

    P_Check --> Validate{"Hat OperationContract die Phase?"}
    A_Check --> Validate
    E_Check --> Validate
    T_Check --> Validate

    Validate -->|"Ja"| Success["Schritt gültig kompilieren"]
    Validate -->|"Nein"| Reject["SpecError: Operation nicht zulässig in dieser Phase"]
```

### Die vier Phasen im Vergleich

| Phase | Spezifikationsabschnitt | Typische Operationen | Verbotene Operationen |
|---|---|---|---|
| **`SETUP`** | `Precondition` | Initialisierung, Zündung einschalten, Fehlerspeicher löschen, Grenzwerte konfigurieren. | Prüfungen, Assertion-Vergleiche. |
| **`STIMULUS`** | `Action` | Spannungsrampen fahren, CAN-Nachrichten senden, LIN-Frames triggern, Wartezeiten. | Reine Leseoperationen ohne Stimulus. |
| **`CHECK`** | `Expected Result` | Signalwert prüfen, Toleranzband verifizieren, Fehlerspeichereintrag abfragen. | Zündung schalten, Spannungen verändern, Signale manipulieren. |
| **`TEARDOWN`** | `Postcondition` | Sicheres Abschalten (Zündung aus, Versorgungsspannung auf 0 V, Bus-Ruhezustand). | Neue Stimulationssequenzen oder Prüfungen. |

Wird beispielsweise versucht, `Batteriespannung = 7000mV` im Abschnitt `Expected Result` einzusetzen, bricht der Compiler sofort ab:
```text
SpecError: operation 'set_supply' is not permitted in section 'Expected Result' (requires CHECK phase)
```

---

## 4. Die mitgelieferten Standard-Fachbibliotheken

In `operations/` stellt SpecToTest sofort einsatzbereite Fachmodule für Standard-Aufgaben bereit:

### A. Zündungssteuerung (`operations/ignition.py`)
- **`set_ignition(bench, state: bool)`:** Schaltet Klemme 15 / Zündung ein (`True`) oder aus (`False`). Phasen: `SETUP | STIMULUS | TEARDOWN`.

### B. Spannungsversorgung (`operations/supply.py`)
- **`set_supply(bench, value: Decimal)`:** Setzt die Versorgungsspannung am Netzteil.
- **`expect_supply_tolerance(bench, value: Decimal, tolerance: Decimal)`:** Prüft, ob die gemessene Spannung im Fenster `[value - tol, value + tol]` liegt. Phase: `CHECK`.
- **`expect_supply_range(bench, min_value: Decimal, max_value: Decimal)`:** Prüft Intervallgrenzen. Phase: `CHECK`.

### C. Fehlerspeicher & Diagnose (`operations/diagnostic.py`)
- **`clear_fault_memory(bench, ecu: str)`:** Löscht Fehlerspeicher über UDS-Service 0x14. Phasen: `SETUP | TEARDOWN`.
- **`read_fault_memory(bench, ecu: str)`:** Liest Fehlerspeichereinträge via UDS-Service 0x19. Phasen: `STIMULUS`.
- **`expect_fault_memory_entry(bench, ecu: str, code: str)`:** Prüft das Vorhandensein eines spezifischen DTCs (z. B. `DTC00173`). Phase: `CHECK`.
- **`expect_no_fault_memory_entry(bench, ecu: str, code: str)`:** Verifiziert, dass ein DTC nicht eingetragen ist. Phase: `CHECK`.

### D. HMI & Bildschirmanzeige (`operations/hmi.py`)
- **`set_screen(bench, screen: str)`:** Wechselt den Bildschirm auf dem Kombiinstrument / Infotainment.
- **`expect_screen(bench, screen: str)`:** Prüft den aktuellen Anzeigezustand.

### E. Timing & Polling (`operations/timing.py`)
- **`wait(bench, seconds: Decimal)`:** Deterministisches Warten auf der Bench.
- **`wait_can_signal(bench, signal: str, value: Decimal, timeout: Decimal, interval: Decimal)`:** Pollt ein Signal mit Timeout und Prüfintervall.

---

## 5. Eigene Operationen erstellen & registrieren

Das Hinzufügen einer neuen Prüfstandsoperation erfolgt in drei einfachen Schritten:

### Schritt 1: Python-Funktion implementieren
Erstelle oder erweitere ein Modul (z. B. `operations/cooling.py`):
```python
def set_pump_speed(bench, speed_percent: Decimal) -> None:
    """Steuert die Kühlmittelpumpe mit der gewünschten Drehzahl in Prozent an."""
    bench.write_pwm('COOLING_PUMP', float(speed_percent))
```

### Schritt 2: Vertrag in `operations/registry.py` registrieren
```python
from tcg.core.contracts import OperationContract, ParameterSpec, STIMULUS, SETUP
from tcg.core.parameters import Quantity
from operations.cooling import set_pump_speed

PUMP_SPEED = Quantity(
    dimension='percentage',
    unit='%',
    minimum=Decimal('0'),
    maximum=Decimal('100'),
)

CONTRACT_COOLING_PUMP = OperationContract(
    name='set_pump_speed',
    function=set_pump_speed,
    docstring='Steuert die Kühlmittelpumpe an (0 bis 100%).',
    parameters=(
        ParameterSpec('speed_percent', PUMP_SPEED, required=True),
    ),
    phases=SETUP | STIMULUS,
)
```

Füge den Vertrag zu `REGISTRY` hinzu:
```python
REGISTRY = build_registry([
    ...,
    CONTRACT_COOLING_PUMP,
])
```

### Schritt 3: Satzmuster in `inputs/operation_mapping.toml` definieren
```toml
[[mapping]]
id = "MAP_COOLING_PUMP_SET"
template = "Kühlmittelpumpe auf {drehzahl} regeln"
operation = "set_pump_speed"
parameters = { drehzahl = "speed_percent" }
```

Damit steht die Anweisung sofort in Spezifikationen und im GUI Mapping Studio zur Verfügung:
```text
## Action
10. Kühlmittelpumpe auf 75% regeln
```
