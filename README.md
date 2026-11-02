# Deterministischer Text-zu-Python-Testgenerator

Anwender pflegen Testfälle als übersichtliche UTF-8-Textdateien. Entwickler pflegen
wiederverwendbare Python-Operationen. Ein separates Operation-Mapping verbindet die
lesbaren Sätze mit registrierten Operationen:

```text
TXT-Testspezifikation + Operation-Mapping + Python-Operationsbibliothek
→ vollständige ausführbare Python-Testfälle
```

Der Generator arbeitet ohne KI und ohne Fuzzy Matching. Unbekannte, mehrdeutige oder
unvollständige Angaben blockieren die Generierung. Generierte Python-Dateien werden
nicht manuell bearbeitet.

## Schnellstart

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt

# Ein einzelner Diagnose-Testfall
python generate.py --spec inputs/testspezifikation_beispiel.txt \
  --mapping inputs/operation_mapping.xlsx \
  --resources inputs/resources.json \
  --registry tcg.demo_registry:REGISTRY \
  --runner tcg.demo_runner \
  --output generated/test_diagnostic_example.py

# Derselbe Ausgangsfall plus ein nur in TXT ergänzter HMI-/Parameter-Test
python generate.py --spec inputs/testspezifikation.txt \
  --mapping inputs/operation_mapping.xlsx \
  --resources inputs/resources.json \
  --registry tcg.demo_registry:REGISTRY \
  --runner tcg.demo_runner \
  --output generated/test_cases.py

python -m generated.test_cases \
  --resources inputs/resources.json \
  --bench-config inputs/demo_bench.json

python -m unittest discover -s tests -v
```

Mit `--test-id TC_HMI_PARAMETER_001` wird nur ein bestimmter Fall ausgeführt.

## Textformat

Ein vollständiger Fall sieht so aus:

```text
# Kommentare beginnen mit #. Leerzeilen sind erlaubt.
TESTFALL: TC_HMI_PARAMETER_001
NAME: HMI und Parameterfluss
TESTZIEL: Bildschirm auswählen und einen Parameter schreiben und prüfen.

VORBEDINGUNGEN:
10. Bildschirm HOME auswählen

TESTSCHRITTE:
10. Einstellungen öffnen
  AKTION: Bildschirm SETTINGS auswählen
  ERWARTUNG 10: Anzeige zeigt "Settings"

20. Verstärkung schreiben
  AKTION: Parameter GAIN auf 42 schreiben
  ERWARTUNG 10: Parameter GAIN ist 42
  ERWARTUNG 20: Anzeige zeigt "Settings"

NACHBEDINGUNGEN:
10. Parameter GAIN auf 0 schreiben
20. Bildschirm HOME auswählen
```

Mehrere `TESTFALL:`-Blöcke dürfen in derselben Datei stehen. Die Nummern definieren
die Reihenfolge; sie müssen positiv und innerhalb ihres Bereichs eindeutig sein.

### Pflichtangaben

- `TESTFALL`, `NAME` und `TESTZIEL` stehen in dieser Reihenfolge am Blockanfang.
- `VORBEDINGUNGEN`, `TESTSCHRITTE` und `NACHBEDINGUNGEN` sind explizite Abschnitte.
- Ein Testschritt hat einen Namen, genau eine eingerückte `AKTION` und mindestens
  eine eingerückte, nummerierte `ERWARTUNG`.
- Mehrere Erwartungen eines Schritts werden nach ihrer Nummer ausgeführt.
- Jede fachliche Aktion und Erwartung muss exakt einem Mapping entsprechen.

Es gibt keine implizite Erwartung für eine leere Zeile. Kommentare und Leerzeilen
sind die einzigen optionalen Elemente. Tabs und nachgestellte Leerzeichen werden
abgelehnt. Fehler nennen Datei und Zeile. Nach einem Lauf werden alle
Nachbedingungen versucht, auch wenn der Hauptablauf oder ein vorheriges Cleanup
fehlschlägt.

## Mapping und lesbare Sätze

`inputs/operation_mapping.xlsx` ist Projektkonfiguration für die
Operationsbibliothek, nicht die Oberfläche zum Schreiben einzelner Testfälle. Es
enthält `Mapping_ID`, `Vorlage`, `Operation` und `Parameterzuordnung`. Beispiel:

```text
Vorlage:              Fehler {code} in {steuergeraet} ist {status}
Operation:            expect_diagnostic
Parameterzuordnung:   code=code;steuergeraet=controller;status=active
```

So bleibt `Fehler UNDERVOLTAGE in BCM ist aktiv` in der Spezifikation lesbar. Der
Typ `Boolean('aktiv', 'inaktiv')` des Operationsvertrags konvertiert den Status zu
`True`; der Textparser kennt weder Diagnose noch Boolean-Parameternamen.

Für jeden Satz muss genau eine Mappingvorlage passen. Mappings referenzieren nur
registrierte Operations-IDs und enthalten keinen ausführbaren Python-Code.

## Zeitsemantik

Zeitverhalten ist immer Teil einer ausdrücklich registrierten Prüfoperation:

| Bedeutung | Textbeispiel | Operation |
|---|---|---|
| Zustand jetzt prüfen | `Fehler ... ist inaktiv` | `expect_diagnostic` |
| Bis zur Zeitgrenze warten | `Auf Fehler ... warten, maximal 500 ms, Prüfintervall 100 ms` | `expect_diagnostic_within` |
| Während einer Dauer überwachen | `Fehler ... bleibt 300 ms aktiv, Prüfintervall 100 ms` | `monitor_diagnostic` |

Der Generator ersetzt keine Prüfung durch eine feste Wartezeit. Die Demo-Überwachung
tastet einschließlich Start- und Endzeitpunkt im genannten Intervall ab.

## Was wird künftig wo geändert?

- **Neuer Test mit vorhandenen Fähigkeiten:** nur eine TXT-Spezifikation ergänzen.
- **Andere Reihenfolge, Parameter, Erwartungen oder Cleanup:** nur den Testfalltext
  ändern.
- **Neue Formulierung für eine vorhandene Fähigkeit:** Mapping ergänzen.
- **Neue technische Fähigkeit:** Python-Funktion implementieren, Operationsvertrag
  registrieren und Mapping ergänzen. Textparser und Renderer bleiben unverändert.
- **Neue Sprachfunktion wie Schleife oder Verzweigung:** erst dann Parser,
  Zwischenmodell und Renderer allgemein erweitern.

`inputs/testspezifikation_beispiel.txt` enthält den Ausgangsfall.
`inputs/testspezifikation.txt` ergänzt `TC_HMI_PARAMETER_001` ausschließlich im
Text und verwendet vorhandene Operationen. Die erzeugten Dateien liegen unter
`generated/`.

## Architektur und Grenzen

Textimport, neutrales Modell, Mappingauflösung, Typkonvertierung, Compiler, Renderer
und Runtime sind fachlich allgemein. Demo-Operationen, Ressourcen und
Zustandsregeln liegen getrennt in `tcg/demo_operations.py`,
`tcg/demo_registry.py`, `inputs/resources.json` und `inputs/demo_bench.json`.

Die frühere `.xlsx`-Spezifikation kann aus Kompatibilitätsgründen weiterhin gelesen
werden; der dokumentierte Anwenderweg verwendet TXT. Das Operation-Mapping bleibt
vorerst eine separate Excel-Projektdatei. Die abgebildeten `FOR`-/`BREAK`-Befehle
sind bewusst **nicht** unterstützt und führen zu einer konkreten Fehlermeldung.
Schleifen benötigen zunächst ein allgemeines Sprachmodell und dürfen nicht als
fachlicher Sonderfall eingebaut werden.

Die Dummy-Bench simuliert Versorgung/Diagnose, HMI und Parameter mit virtueller
Zeit. Es werden keine Hardware-, EXAM- oder ecu.test-Kompatibilität und keine
Produktionsreife behauptet.
