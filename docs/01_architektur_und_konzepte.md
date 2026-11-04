# 01 — Architektur & Kernkonzepte

Dieses Dokument beschreibt die architektonischen Grundlagen und Entwurfsprinzipien von **SpecToTest**. Es erläutert, wie das System die klassische Kluft zwischen fachlicher Testspezifikation und ausführbarem Testcode überwindet.

---

## 1. Motivation & Problemstellung

In Entwicklungs- und Testumgebungen (beispielsweise im Automotive HiL/SiL-Umfeld oder bei verteilten Software-Diensten) treffen zwei gegensätzliche Welten aufeinander:

1. **Die Spezifikationswelt:** Testingenieure und Systemarchitekten formulieren Anforderungen in natürlicher Fachsprache (`Zündung an`, `Batteriespannung = 7000mV`, `Fehlerspeichereintrag DTC00173 eingetragen`).
2. **Die Implementierungswelt:** Testskripte in Python oder C# enthalten oft hunderte Zeilen Boilerplate-Code, Prüfstands-Initialisierung, Hardware-Treiberaufrufe, proprietäre Logging-Mechanismen und fest verdrahtete Zeichenketten.

### Die Folgen klassischer Ansätze
- **Hohe Wartungskosten:** Ändert sich ein Funktionsaufruf oder eine Hardware-Bibliothek, müssen dutzende Skripte manuell refaktoriert werden.
- **Mangelnde Auditierbarkeit:** In einem Audit lässt sich nur schwer beweisen, dass Skriptzeile 342 exakt die Anforderung aus Schritt 20 der Spezifikation erfüllt.
- **Hardware-Abhängigkeit:** Tests können oft nicht ohne den physischen Prüfstand ausgeführt oder auf Entwicklerrechnern vorvalidiert werden.

---

## 2. Die Hexagonale Architektur (Ports & Adapters)

Um diese Probleme nachhaltig zu lösen, basiert **SpecToTest** konsequent auf den Prinzipien der **Hexagonalen Architektur** (Alistair Cockburn):

```mermaid
flowchart TB
    subgraph DrivingAdapters["1. Driving Adapters (Eingabe)"]
        CLI["CLI Tool (generate.py)"]
        TextParser["Text Parser Adapter (text_parser.py)"]
        GUIApp["SpecToTest Studio (PySide6 / Qt)"]
    end

    subgraph DrivingPorts["2. Driving Ports (Primäre Schnittstellen)"]
        SpecPort["SpecificationParserPort"]
        GUIPort["GUI Facade Service"]
    end

    subgraph CoreHexagon["DAS HEXAGON: Compiler & AST Kern (tcg/core)"]
        Compiler["Compiler Engine (compiler.py)"]
        MappingEngine["Mapping & Regex Resolver (mapping.py)"]
        TypeConversion["Value Objects & Units (parameters.py)"]
        Contracts["Vertragsprüfung (contracts.py)"]
        ProfileCheck["Ressourcenprüfung (profile.py)"]
        ASTModel["Domänen-Modell & AST (model.py)"]
    end

    subgraph DrivenPorts["3. Driven Ports (Sekundäre Schnittstellen)"]
        EmitterPort["CodeEmitterPort"]
        BenchPort["BenchPort Protocol (now, wait)"]
    end

    subgraph DrivenAdapters["4. Driven Adapters (Ausgabe & Ausführung)"]
        PyEmitter["Python Code Emitter (python_emitter.py)"]
        DummyBench["In-Memory Mock Bench (dummy_bench.py)"]
        HardwareBench["Hardware Prüfstand (HiL / Vector / dSPACE)"]
        Runner["Test Runner & Reporter (runner.py)"]
    end

    subgraph UserDomain["5. Fachdomäne des Anwenders (operations/)"]
        OpsRegistry["Operation Registry (registry.py)"]
        DomainOps["Fach-Module (ignition, supply, diagnostic, can, lin, eth)"]
    end

    CLI --> TextParser
    GUIApp --> GUIPort
    TextParser --> SpecPort
    SpecPort --> Compiler
    GUIPort --> Compiler

    Compiler --> ASTModel
    Compiler --> MappingEngine
    Compiler --> TypeConversion
    Compiler --> Contracts
    Compiler --> ProfileCheck

    Contracts -.prüft Signaturen gegen.-> OpsRegistry
    ProfileCheck -.validiert IDs gegen.-> UserDomain

    Compiler --> EmitterPort
    EmitterPort --> PyEmitter

    Runner --> BenchPort
    BenchPort --> DummyBench
    BenchPort --> HardwareBench
    Runner --> PyEmitter
```

### Die Schichten im Detail

#### A. Das Hexagon (Compiler-Kern `tcg/core`)
Das Zentrum des Systems ist vollständig frei von I/O-, Prüfstands- oder automobilspezifischen Abhängigkeiten:
- **`tcg/core/model.py`:** Definiert die abstrakte Syntax (AST) eines Testfalls (`TestCaseNode`, `ActionStepNode`, `ExpectationNode`, `LoopNode`).
- **`tcg/core/compiler.py`:** Überführt geparste Abschnitte in den AST, bindet Erwartungen an Aktionsschritte und validiert Scoping-Regeln.
- **`tcg/core/mapping.py`:** Kompiliert TOML-Satzmuster in exakte Regex-Muster und ordnet Satzphrasen deterministisch zu.
- **`tcg/core/parameters.py`:** Typsystem mit physikalischer Einheitenumrechnung (`Quantity`), Ressourcen-Bindung und isolationstechnischem Kontext (`set_step_context`).
- **`tcg/core/contracts.py`:** Prüft Typsignaturen und Phasenberechtigungen von Operationen.
- **`tcg/core/profile.py`:** Stellt sicher, dass nur zulässige Bezeichner (z. B. deklarierte Steuergeräte oder Signale) verwendet werden.

#### B. Driving Ports & Adapters (Eingabe)
- **Adapter `text_parser.py`:** Liest Spezifikationen im `.txt`- oder `.md`-Format ein, filtert Kommentare (Hash, C-Style, HTML-Blöcke) und strukturiert Abschnitte.
- **Adapter `generate.py`:** Kommandozeilenwerkzeug zur Batch-Generierung von Testskripten für CI/CD-Pipelines.
- **Adapter `tcg/gui/`:** Interaktive Arbeitsumgebung (SpecToTest Studio) mit Syntaxprüfung und Zeileninspektor.

#### C. Driven Ports & Adapters (Ausgabe & Prüfstand)
- **Adapter `python_emitter.py`:** Übersetzt den AST in lesbaren Python-Code.
- **Port `BenchPort`:** Schnittstellenprotokoll (`Protocol`), das Zeitstempel (`now()`) und Zeitschritte (`wait(seconds)`) bereitstellt.
- **Adapter `dummy_bench.py`:** Schnelle In-Memory-Simulation für lokale Entwicklung und CI/CD.
- **Adapter Hardware:** Echte Prüfstände (CANoe über COM-Interface, dSPACE ControlDesk, LIN-/Ethernet-Treiber).
- **Adapter `runner.py`:** Führt die generierten Tests aus, sammelt Messwerte und erzeugt Reports.

#### D. Die Fachdomäne (`operations/`)
Hier implementieren Testingenieure ihre fachlichen Bibliotheken (z. B. Spannungsversorgung einstellen, CAN-Signal senden, Fehlerspeicher löschen). Der Compiler-Kern kennt diese Funktionen nicht persönlich — er kennt nur deren formale Verträge (`OperationContract`).

---

## 3. End-to-End Datenfluss & Pipeline

Der Lebenszyklus eines Testfalls von der Spezifikation bis zur Testergebnis-Analyse vollzieht sich in einer deterministischen, sequentiellen Pipeline:

```mermaid
sequenceDiagram
    autonumber
    actor Ing as Testingenieur / CI
    participant Parser as Inbound TextParser
    participant Compiler as Core Compiler
    participant Mapping as Core Mapping & Types
    participant Profile as Core Profile
    participant Emitter as Python Emitter
    participant Runner as Test Runner
    participant Bench as BenchPort Adapter
    participant Report as Reporting Engine

    Ing->>Parser: Spezifikationsdatei (tc_01.md)
    Parser->>Compiler: Geparste Sektionen (Precondition, Action, etc.)
    
    loop Für jeden Schritt
        Compiler->>Mapping: Phrase auflösen (z. B. "Batteriespannung = 7000mV")
        Mapping->>Mapping: Template-Match & Kontext-Isolation
        Mapping->>Mapping: Einheitenumrechnung (7000mV -> Decimal('7.000') V)
        Mapping-->>Compiler: Gebundene Operation & Argumente
        Compiler->>Profile: Ressourcen prüfen (z. B. Steuergerät BCM1)
        Profile-->>Compiler: Ressource bestätigt
    end

    Compiler->>Compiler: AST aufbauen, Erwartungen binden, Phasen prüfen
    Compiler->>Emitter: Fertiger AST (TestCaseNode)
    Emitter-->>Ing: Generiertes Python-Skript (test_tc_01.py)

    Ing->>Runner: Skript ausführen (run_bench.py)
    Runner->>Bench: Verbindung herstellen & initialisieren
    
    rect rgb(240, 248, 255)
        note over Runner,Bench: Deterministische Testausführung
        Runner->>Bench: Precondition ausführen
        Runner->>Bench: Action stimulieren & Prüfschritt bewerten
        Runner->>Bench: Postcondition garantiert ausführen (try ... finally)
    end

    Runner->>Report: Testergebnisse & Traces übergeben
    Report-->>Ing: HTML-Dashboard (report.html) & JUnit-XML (junit.xml)
```

---

## 4. Die Kernprinzipien von SpecToTest

### 1. Strikt deterministisches Kompilieren
Für dieselbe Eingabe (Spezifikation, Mapping, Ressourcenprofil) generiert der Compiler Bit für Bit exakt denselben Python-Code. Es gibt keine Zufallselemente, keine Heuristiken und keine impliziten Standardwerte, die nicht formal deklariert sind.

### 2. Garantierte Aufräumsicherheit (`try ... finally`)
Im generierten Testcode werden alle Nachbedingungen (`Postcondition`) in einem `try ... finally`-Block gekapselt. Selbst wenn ein Testschritt mitten im Ablauf fehlschlägt oder eine Assertion nicht erfüllt ist, wird das System immer in einen sicheren Ausgangszustand versetzt (z. B. Zündung aus, Spannungsversorgung abschalten).

### 3. Vollständige Auditierbarkeit & Traceability
Jedes generierte Python-Testskript enthält im Modul-Docstring den exakten Wortlaut der ursprünglichen Spezifikation. Jeder einzelne generierte Aufruf ist mit der Zeilennummer und dem Originalsatz aus der Spezifikation kommentiert.

### 4. Technologieneutrale Multi-Bus-Unterstützung
CAN, LIN und Automotive Ethernet (SOME/IP) werden über ein einheitliches Abstraktionsmodell in `tcg/comm/` verwaltet. Weder der Compiler noch die Spezifikationssprache sind an eine bestimmte Bus-Hardware gebunden.
