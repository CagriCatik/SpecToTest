# Fremde Beschreibungsdateien (Konformitätskorpus)

Diese Dateien stammen **nicht** aus diesem Projekt. Sie dienen als unabhängiger
Konformitätsnachweis: die Importer werden gegen Dateien geprüft, die von anderen
Werkzeugen und Autoren erzeugt wurden, nicht nur gegen selbst geschriebene.

## Herkunft

| Dateien | Quelle | Lizenz |
| --- | --- | --- |
| `*.ldf` | [c4deszes/ldfparser](https://github.com/c4deszes/ldfparser), Verzeichnis `tests/ldf` | MIT (siehe `LICENSE.ldfparser`) |
| `*.arxml` | [cantools/cantools](https://github.com/cantools/cantools), Verzeichnis `tests/files/arxml` | MIT (siehe `LICENSE.cantools`) |

Die LDF-Dateien decken LIN 1.3, 2.0, 2.1, 2.2, ISO 17987 und SAE J2602 ab sowie
Sonderfälle: Array-Initialwerte, Frames ohne Längenangabe, sporadische Frames,
Diagnose-Frames, Schedule-Kommandos und BCD/ASCII-Encodings.

Die ARXML-Dateien sind **CAN-System- und ECU-Extract-Beschreibungen** (AUTOSAR
3.1.2, 3.2.3 und 4.2). Keine davon enthält ein `SERVICE-INTERFACE`. Sie belegen
daher nicht den Service-Import, sondern dass der Importer reale, nicht unterstützte
ARXML-Dateien **sauber und mit verständlicher Meldung ablehnt** statt abzustürzen
oder etwas zu erfinden. Ein unabhängig erzeugtes ARXML mit Service-Interfaces lag
nicht vor — siehe die Prüfmatrix im README des Projekts.

## Verwendung

`tests/conformance/test_external_descriptions.py` vergleicht für jede Datei das
Ergebnis des SpecToTest-Importers feldweise mit dem Ergebnis der unabhängigen
Referenzimplementierung (`ldfparser`). Fehlt die Referenzbibliothek, werden die
Tests übersprungen — siehe `requirements-dev.txt`.

Die Dateien werden **nicht verändert**. Treten Abweichungen auf, ist der Importer
zu korrigieren, nicht die Datei.
