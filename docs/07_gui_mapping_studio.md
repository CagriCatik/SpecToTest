# 07 — SpecToTest Studio (GUI)

Dieses Dokument beschreibt die Architektur, die Arbeitsbereiche und die Bedienung von **SpecToTest Studio**, der grafischen Desktop-Entwicklungsumgebung auf Basis von **PySide6 / Qt**.

---

## 1. Starten der Benutzeroberfläche

Die GUI kann direkt über das Startskript `gui.py` aufgerufen werden:

```bash
# Standard-Start (Dunkles Farbschema, Automotive-Profil)
python3 gui.py

# Start im hellen Farbschema
python3 gui.py --light

# Start mit einem spezifischen Profil (z. B. Software Service Pilot)
python3 gui.py --profile service
```

---

## 2. Architektur & Entkopplung (`tcg/gui/`)

Die GUI ist strikt von den Compiler-Interna entkoppelt. Sie greift niemals unkontrolliert auf AST-Strukturen zu, sondern nutzt ein sauberes Schichtenmodell:

```mermaid
flowchart TD
    subgraph UIComponents["Benutzeroberfläche (Workspaces)"]
        Win["Hauptfenster (app.py)"]
        SpecWS["Spezifikations-Editor (view_specifications.py)"]
        CatWS["Operationskatalog (view_catalog.py)"]
        CommWS["Kommunikationsansicht (view_communication.py)"]
        TestWS["Satzprüfung (view_tester.py)"]
    end

    subgraph FacadeLayer["Fassaden- & Zustands-Schicht"]
        Facade["GUI-Fassade (facade.py)"]
        AppState["Zustandsmodell (models.py)"]
        AnalysisMgr["Hintergrund-Analyse-Manager"]
        ProfileMgr["Projektprofil-Manager (profiles.py)"]
    end

    subgraph CoreEngine["Compiler & Kommunikations-Katalog"]
        CoreComp["tcg.core (compiler, mapping, profile)"]
        CommCat["tcg.comm (Bus-Kataloge, DBC, LDF, ARXML)"]
        Registry["operations.registry"]
    end

    Win --> SpecWS
    Win --> CatWS
    Win --> CommWS
    Win --> TestWS

    SpecWS --> Facade
    CatWS --> AppState
    CommWS --> Facade
    TestWS --> Facade

    Facade --> AppState
    Facade --> AnalysisMgr
    AppState --> ProfileMgr

    AppState --> CoreComp
    AppState --> CommCat
    AppState --> Registry
```

- **`AppState` (`models.py`):** Hält die aktiven Mappings, die geladene Registry, das Ressourcenprofil und die Kommunikationsdatenbank.
- **`Facade` (`facade.py`):** Kapselt komplexe Operationen (z. B. asynchrone Syntaxanalyse im Hintergrund, Verknüpfungsberechnungen zwischen Aktionen und Erwartungen).
- **`AnalysisManager`:** Führt die Kompilierung bei Tastatureingaben verzögert (Debounce 300 ms) im Hintergrund aus, ohne die UI zu blockieren.

---

## 3. Die vier Haupt-Workspaces

### A. Spezifikations-Editor (`view_specifications.py`)
Der zentrale Arbeitsbereich für das Schreiben und Untersuchen von Tests:

```mermaid
flowchart LR
    Tree["1. Projekt- & Dateibaum (links)"]
    Editor["2. Spezifikations-Editor (Mitte)"]
    Inspector["3. Schritt-Inspektor (rechts)"]
    Problems["4. Einklappbare Problemliste (unten)"]

    Tree -->|"Datei wählen"| Editor
    Editor -->|"Cursor bewegen"| Inspector
    Editor -->|"Hintergrund-Prüfung"| Problems
```

1. **Projektbaum (links):**
   - Strukturierte Ordneransicht aller `.txt`- und `.md`-Spezifikationen.
   - Filterfeld zur schnellen Volltext-Suche nach Dateinamen.
   - Vollständiger Dateipfad und Modus als Tooltip.
2. **Editor (Mitte):**
   - Syntax-Highlighting für Abschnitte (`Precondition`, `Action`, etc.), Schrittnummern und Kontrollstrukturen.
   - Änderungsstatus-Anzeige (`*` bei ungespeicherten Änderungen).
   - Schnellspeicher-Button (`Cmd+S` / `Ctrl+S`).
3. **Schritt-Inspektor (rechts, 3 Tabs):**
   - **Tab „Details“:** Zeigt für die Zeile unter dem Cursor sofort das zugeordnete Satzmuster (`[MAP_...]`), die aufgerufene Operation, deren Docstring und alle extrahierten Parameter mit Typ an.
   - **Sprung zur Verknüpfung (`btn_jump_linked`):** Befindet sich der Cursor auf einem Aktionsschritt, führt ein Klick direkt zur zugehörigen Prüfung im Abschnitt `Expected Result` (und umgekehrt).
   - **Tab „Schritt einfügen“:** Ermöglicht das schnelle Einfügen vorbereiteter Satzbausteine über strukturierte Eingabefelder (`widget_smart_param.py`).
   - **Tab „Python“:** Zeigt die Live-Vorschau der generierten Python-Funktion für den aktuellen Testfall.
4. **Einklappbare Problemliste (unten):**
   - Zeigt Syntaxfehler, ungebundene Sätze, ungültige Ressourcen oder Phasenverletzungen übersichtlich in einer sortierbaren Tabelle an.
   - Klick auf einen Fehler springt direkt in die betreffende Zeile im Editor.

---

### B. Operationskatalog (`view_catalog.py`)
Der vollständige Überblick über alle im System registrierten Fachfunktionen:
- **Phasenfilter:** Filtern nach `SETUP`, `STIMULUS`, `CHECK` oder `TEARDOWN`.
- **Statusanzeige:** Erkennt sofort Lücken (rot: Operation existiert im Code, besitzt aber noch kein Satzmuster; grün: Operation ist verknüpft).
- **Details:** Zeigt Parameterliste mit Pflicht-/Optional-Kennzeichnung, Einheiten und zulässigen Wertebereichen.
- **Mapping-Verwaltung:** Neues Satzmuster für eine Operation direkt per Dialog anlegen oder bestehende Mappings bearbeiten.

---

### C. Multi-Bus Kommunikationsansicht (`view_communication.py`)
Ermöglicht das visuelle Durchsuchen aller geladenen Fahrzeugnetzwerke:
- **Netzwerkbaum:** Gruppiert nach Technologie (CAN, LIN, Ethernet).
- **Detaillierte Tabellen:**
  - **CAN & LIN:** Botschaften, Frame-IDs, Zykluszeiten, Startbits, Bitlängen, Byte-Order, Skalierungsfaktoren, Offsets und diskrete Enums (z. B. `0 = Geschlossen`, `1 = Offen`).
  - **Ethernet (SOME/IP):** Service-IDs, Instance-IDs, Methoden mit Request-/Response-Signaturen und abonnierbare Events.
- **Volltext-Filter:** Schnelles Auffinden von Signalen über alle Netzwerke hinweg.

---

### D. Satzprüfung / Mapping Tester (`view_tester.py`)
Ein interaktives Testlabor für Satzformulierungen:
- Eingabe einer beliebigen Textzeile.
- Sofortige Rückmeldung:
  - Match-Status (Erfolgreich gemappt, Ambiguität oder kein Match).
  - Aufgerufene Operation und extrahierte Parameter.
  - Warnung vor unerwünschten Mehrdeutigkeiten.

---

## 4. Projektprofile & Transaktionaler Profilwechsel

SpecToTest Studio unterstützt mehrere Projektkonfigurationen (z. B. Automotive HiL vs. Software Service Pilot).

```mermaid
sequenceDiagram
    autonumber
    actor User as Anwender
    participant UI as MappingStudioWindow
    participant State as AppState (models.py)
    participant Validator as test_validate_profile (profiles.py)

    User->>UI: Profil wechseln (z. B. zu "Service Pilot")
    UI->>UI: Ungespeicherte Änderungen abfragen (Prompt Save)
    UI->>State: set_project_profile(profile)
    State->>Validator: Transaktionale Validierung aller Artefakte

    alt Alle Artefakte (Registry, Mappings, Profile, CAN-DB) gültig
        Validator-->>State: OK (Artifacts Bundle)
        State->>State: Zustand atomar aktualisieren
        State-->>UI: Erfolgreich gewechselt
        UI->>UI: Editor, Katalog & Kommunikationsbaum aktualisieren
    else Fehler in Konfiguration (z. B. defekte CAN-Datenbank)
        Validator-->>State: FEHLER (Fehlermeldung)
        State->>State: Ursprünglicher Zustand bleibt 100% unverändert!
        State-->>UI: Abbruch mit Fehlermeldung
        UI->>User: Fehlermeldung als Dialog anzeigen
    end
```

### Transaktionale Sicherheit
Ein Profilwechsel wird **nur dann** vollzogen, wenn die Zielkonfiguration vollständig fehlerfrei geladen werden kann. Ist beispielsweise eine CAN-Signaldatenbank beschädigt, wird der Wechsel abgebrochen und der aktuelle Arbeitsstand bleibt unberührt.
