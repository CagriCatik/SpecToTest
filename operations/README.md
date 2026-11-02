# Operationsbibliothek (`operations/`)

Dieser Ordner enthält alle technischen Operationen, die in den `.txt`-Testspezifikationen verwendet werden können.
Der Compiler-Kern (`tcg/`) ist vollständig unabhängig von diesen Operationen.

## Ordnerstruktur

- `ignition.py` – Zündungsfunktionen (`set_ignition`)
- `diagnostic.py` – Diagnose, Fehlerspeicher lesen/löschen, DTC-Prüfungen
- `supply.py` – Spannungsversorgung, Batteriespannung (`set_battery_voltage`, `set_supply`)
- `timing.py` – Warteoperationen (`wait`)
- `hmi.py` – Bildschirmauswahl, Parameter lesen/schreiben
- `registry.py` – Zentrale Registrierung der Verträge und Typen
- `__init__.py` – Exportiert `REGISTRY`

---

## So fügst du eine neue Operation hinzu

Das Hinzufügen einer neuen Operation erfordert 3 einfache Schritte:

### 1. Python-Funktion schreiben

Erstelle oder öffne die passende Datei in `operations/` (z.B. `operations/can.py`):

```python
def send_can_message(bench, *, message_id: str, data: str):
    """Sendet eine CAN-Nachricht über den Prüfstand."""
    bench.send_can(message_id, data)
```
> **Wichtig:**
> - Der erste Parameter ist immer `bench` (Positionsargument).
> - Alle fachlichen Parameter sind **keyword-only** (nach `*`).
> - Prüfoperationen werfen bei Nichterfüllung `CheckFailed("...")` aus `tcg.runtime`.

---

### 2. Vertrag in `operations/registry.py` eintragen

Öffne `operations/registry.py` und registriere die Funktion:

```python
from . import can

REGISTRY = build_registry((
    ...
    OperationContract(
        'send_can_message', 
        can.send_can_message,
        (
            ParameterSpec('message_id', String()),
            ParameterSpec('data', String()),
        ),
        SETUP,  # SETUP = frozenset({'PRECONDITION', 'ACTION', 'CLEANUP'}) oder CHECK = frozenset({'EXPECTED'})
    ),
))
```

---

### 3. Satzschablone in `inputs/operation_mapping.toml` definieren

Öffne `inputs/operation_mapping.toml` und verknüpfe die deutsche/englische Formulierung mit der Operation:

```toml
[[mapping]]
id = "MAP_SEND_CAN"
template = "CAN-Nachricht {msg_id} mit Daten {payload} senden"
operation = "send_can_message"
parameters = { msg_id = "message_id", payload = "data" }
```

Jetzt kann der Befehl direkt in jeder `.txt`-Spezifikation verwendet werden:
```text
Action
10. CAN-Nachricht "0x123" mit Daten "DEADBEEF" senden
```

