Deine Aufgabe ist, den vorhandenen Prototyp kritisch zu prüfen, nachgewiesene Schwächen zu beheben und daraus einen nachvollziehbaren, deterministischen Testfallgenerator weiterzuentwickeln. Arbeite direkt im vorhandenen Projekt.

Übernimm Aussagen aus README, Kommentaren oder bisherigen Testergebnissen nicht ungeprüft. Untersuche die Implementierung und führe die relevanten Abläufe selbst aus.

## Ziel und verbindliche Anforderungen

Das Werkzeug soll aus folgenden Bestandteilen ausführbare Python-Testfälle erzeugen:

1. Excel-Testspezifikation.
2. Separates Excel-Operation-Mapping.
3. Vorhandene Python-Grundoperationen.

Die gesamte Verarbeitung muss ohne KI funktionieren:

- Keine LLMs, Embeddings, Agenten oder KI-Dienste im entwickelten Werkzeug.
- Kein Fuzzy Matching und keine heuristische Auswahl vermeintlich passender Operationen.
- Explizite Syntax, eindeutige Zuordnungen und typisierte Parameter.
- Unbekannte oder mehrdeutige Angaben führen zu verständlichen Validierungsfehlern.
- Gleiche fachliche Eingaben erzeugen mit derselben Generatorversion byteidentische Python-Dateien.
- Während Import, Validierung und Generierung werden keine Testoperationen ausgeführt.

Diese Einschränkungen betreffen das entwickelte Werkzeug. Du darfst als Code-Agent den Quellcode analysieren, bearbeiten und testen.

## 1. Zuerst den tatsächlichen Zustand prüfen

Lies den Quellcode, die Excel-Dateien und die Dokumentation. Prüfe insbesondere:

- `generate.py`
- `tcg/model.py`
- `tcg/excel_input.py`
- `tcg/compiler.py`
- `tcg/render.py`
- `tcg/operations.py`
- `tests/test_pipeline.py`
- `generated/test_undervoltage.py`

Führe den Generator, den erzeugten Testfall und die vorhandenen automatisierten Tests aus.

Dokumentiere danach kurz:

- Was funktioniert nachweislich?
- Welche Annahmen sind fest im Code eingebaut?
- Welche Fehler werden früh erkannt, welche erst bei der Ausführung?
- Welche bisherigen Tests prüfen tatsächliches Verhalten?
- Wo bestätigen Tests lediglich dieselben Annahmen wie die Implementierung?
- Welche Aussagen in der Dokumentation sind zu weitgehend?

Eine grüne Testsuite allein reicht als Qualitätsnachweis nicht aus.

## 2. Die Übersetzung anhand eines Schritts erklären

Verfolge mindestens einen Schritt vollständig:

Excel-Zelle → Mappingauswahl → Parameterkonvertierung → Zwischenmodell → erzeugter Python-Aufruf → Operation → Ergebnisprotokoll.

Zeige dabei die tatsächlich betroffenen Dateien und Funktionen.

Beantworte ausdrücklich:

- Wie wird die passende Operation eindeutig bestimmt?
- Wo werden Parametername, Typ, Einheit und Wertebereich geprüft?
- Wie wird verhindert, dass Excel-Inhalte ausführbarer Python-Code werden?
- Wie wird sichergestellt, dass die erzeugte Signatur zur realen Python-Funktion passt?
- Wie lässt sich jeder erzeugte Schritt zur Excel-Quelle zurückverfolgen?

Wenn eine dieser Eigenschaften bisher nur angenommen wird, kennzeichne das als Lücke.

## 3. Die Architektur gezielt verbessern

Erhalte brauchbare Teile. Vermeide einen vollständigen Rewrite ohne konkreten Nachweis seiner Notwendigkeit.

Die Verantwortlichkeiten müssen getrennt bleiben:

- Excel-Adapter: Dateien und Tabellen lesen.
- Domänenmodell: Testfälle, Schritte und Parameter beschreiben.
- Mappingauflösung: eindeutige Operationen bestimmen.
- Validierung: Struktur und fachliche Verträge prüfen.
- Codegenerator: ausschließlich validierte Modelle übersetzen.
- Operationsbibliothek: technische Aktionen und Prüfungen ausführen.
- Prüfstandsadapter: Simulation beziehungsweise spätere Hardwareanbindung.

Der Kern darf weder Excel-Bibliotheken noch Hardwaretreiber benötigen.

Untersuche besonders die derzeitige Mischung aus Operationsfunktionen und Dummy-Prüfstand. Trenne sie, wenn dadurch eine konkrete Kopplung beseitigt wird.

Funktionen sollen eine klar benennbare Aufgabe haben. Vermeide eine zentrale Funktion, die Import, Mapping, Validierung, Codeausgabe und Ausführung gleichzeitig übernimmt.

## 4. Operationsverträge und Mapping belastbar machen

Prüfe die bestehende Operations-Registry auf Widersprüche zu den implementierten Funktionen.

Ein Operationsvertrag soll mindestens festlegen:

- Eindeutige Operations-ID.
- Pflichtparameter und ausdrücklich unterstützte optionale Parameter.
- Parametertypen und gegebenenfalls Einheiten.
- Zulässige Testphasen.
- Zugeordnete Python-Implementierung.

Verhindere unbemerkte Abweichungen zwischen Registry und Funktionssignaturen. Verwende hierfür eine explizite Registrierung und geeignete Signaturprüfungen, sofern das zur vorhandenen Struktur passt.

Excel darf ausschließlich freigegebene Operationen referenzieren. Keine beliebigen Imports, Modulpfade oder Python-Ausdrücke aus Excel ausführen.

Trenne allgemeine Operationen von den Ressourcen und Grenzen des Dummy-Prüfstands. Beispielsweise sind `BCM`, `UNDERVOLTAGE` und ein maximaler Spannungswert keine universellen Eigenschaften eines Testfallgenerators.

Ein kleines, validiertes JSON-Prüfstandsprofil ist dafür ausreichend. Führe keine zusätzliche Konfigurationsbibliothek ohne konkreten Bedarf ein.

## 5. Gegenbeispiele tatsächlich prüfen

Ergänze gezielte Tests für relevante, bisher unzureichend abgedeckte Fälle:

- Fehlende oder doppelte Spaltenüberschriften.
- Fehlende Pflichtfelder.
- Unbekannte Operationen und Ressourcen.
- Doppelte Mapping-IDs.
- Mehrere passende Vorlagen für denselben Schritt.
- Fehlende, zusätzliche oder falsch benannte Platzhalter.
- Abweichungen zwischen Operationsvertrag und Python-Signatur.
- Ungültige Einheiten und Werte außerhalb erlaubter Grenzen.
- Nullwerte gegenüber leeren Zellen.
- Doppelte oder unzulässige Schrittnummern.
- Ungültige Phasenfolgen.
- Python-artige Zeichenfolgen, Anführungszeichen und Sonderzeichen in Eingaben.
- Fehlgeschlagene Prüfungen.
- Technische Operationsfehler.
- Fehler während Cleanup.
- Ungültige Eingaben bei bereits vorhandener Ausgabedatei.

Nutze echte Excel-Dateien für ausgewählte Import- und Integrationstests. Mocks dürfen ergänzen, aber den Excel-Import nicht vollständig ersetzen.

Prüfe außerdem, ob eine Änderung der Zeilenreihenfolge im Mapping das Ergebnis eines eindeutig zugeordneten Tests unverändert lässt.

## 6. Die Aussagekraft der Dummy-Ausführung prüfen

Ein Dummy-Prüfstand muss eine eigene Zustandsentwicklung besitzen. Er darf erwartete Ergebnisse nicht aus der Testspezifikation übernehmen und anschließend einfach als erfüllt melden.

Baue mindestens zwei kontrollierte Gegenproben:

1. Ein erwarteter Zustand wird absichtlich falsch spezifiziert. Der erzeugte Test muss fehlschlagen.
2. Das Dummy-System reagiert absichtlich später als im Test vorgesehen. Die Prüfung muss fehlschlagen.

Beide Gegenproben müssen weiterhin Cleanup ausführen.

Dokumentiere präzise, was diese Simulation nachweist und welche Eigenschaften realer Hardware damit ungeprüft bleiben.

## 7. Reproduzierbarkeit nachweisen

Erzeuge denselben Test zweimal aus unveränderten Eingaben und vergleiche die Python-Dateien byteweise.

Prüfe getrennt:

- Deterministische Codegenerierung.
- Reproduzierbare Dummy-Ausführung.

Keine Zeitstempel, Zufallswerte, absoluten lokalen Pfade oder instabilen Reihenfolgen in generierte Testdateien aufnehmen.

Führe den Generator außerdem in einem frischen Python-Prozess aus. Ein Vergleich innerhalb desselben Prozesses genügt nicht als einziger Nachweis.

## 8. Einen zweiten unabhängigen Beispieltest ergänzen

Erstelle zusätzlich zum Unterspannungstest einen zweiten kleinen Testfall, beispielsweise einen normalen Zündungsablauf mit Zustandsprüfung.

Verwende dazu eine eigene Excel-Testspezifikation und dieselbe Operationsbibliothek beziehungsweise dasselbe Mapping, soweit fachlich passend.

Der zweite Test soll zeigen, dass der Generator nicht ausschließlich auf die zwölf Schritte des ursprünglichen Beispiels zugeschnitten ist.

Eine Testfall-ID pro Spezifikationsdatei ist für diesen Entwicklungsschritt ausreichend. Ich brauche aber mehrere Testcases in der Testspezifikation, dementsprechen dann auch generierte testcases in python also output.

## 9. Selbstständig bis zum verifizierten Ergebnis arbeiten

Beginne mit Bestandsaufnahme und reproduzierbaren Befunden. Behebe danach die nachgewiesenen Probleme in kleinen Schritten.

Du darfst lokale Dateien bearbeiten, Beispiele ergänzen und Tests ausführen. Frage nur nach, wenn eine fehlende fachliche Entscheidung das korrekte Weiterarbeiten tatsächlich blockiert.

Erfinde keine Anforderungen eines realen Steuergeräts. Kennzeichne Demo-Regeln ausdrücklich.

## Abnahmekriterien

Die Aufgabe ist abgeschlossen, wenn:

- Beide Excel-Beispiele erfolgreich Python-Testfälle erzeugen.
- Beide erzeugten Testfälle in der Dummy-Umgebung ausführbar sind.
- Gezielt falsche Erwartungen nachweislich fehlschlagen.
- Mehrdeutige oder ungültige Spezifikationen die Generierung blockieren.
- Cleanup bei normalen Ausführungsfehlern zuverlässig versucht wird.
- Operationsverträge und Implementierungen auf Konsistenz geprüft werden.
- Byteidentische Generierung nachgewiesen ist.
- Die vorhandenen und ergänzten relevanten Tests bestehen.
- Die README die tatsächlichen Fähigkeiten, Eingaberegeln und Grenzen beschreibt.

Berichte abschließend knapp:

1. Wichtigste Befunde mit Dateiverweisen.
2. Umgesetzte Änderungen und deren Zweck.
3. Tatsächlich ausgeführte Befehle und Ergebnisse.
4. Ein konkretes Beispiel der Übersetzung von Excel nach Python.
5. Verbleibende Grenzen und der nächste sinnvolle Entwicklungsschritt.

Behaupte keine Produktionsreife oder Hardwarekompatibilität, die du nicht geprüft hast.