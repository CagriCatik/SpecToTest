# SpecToTest Specification Language Contract

This document specifies the exact syntax, semantic structure, scoping rules, and lifecycle behavior of test specifications (`.txt` and `.md`) compiled by **SpecToTest**.

---

## 1. File Format & Encoding

- **Supported Formats:** `.txt` (plain text) and `.md` (Markdown).
- **Encoding:** UTF-8 (with or without Byte Order Mark / BOM).
- **Line Endings:** LF (`\n`) or CRLF (`\r\n`).
- **Whitespace:** Tolerant of leading and trailing whitespace and tabs.
- **Comments:**
  - Single-line hash comments: `# This is a comment` (inline comments permitted outside of quoted string literals).
  - C-style single-line comments: `// This is a comment`.
  - C-style multi-line block comments: `/* ... */`.
  - HTML multi-line comments: `<!-- ... -->` (especially in Markdown).
- **Instruction Density:** Exactly one instruction or control statement per line.

### Markdown (`.md`) Support
SpecToTest natively processes Markdown files without any external preprocessor:
- **Headings:** `#`, `##`, `###` can prefix section titles (e.g. `## Precondition`, `## Action`) and metadata (`# TESTFALL: TC_01`).
- **Bold Styling:** Metadata keys like `**TESTFALL:**`, `**NAME:**`, `**TESTZIEL:**` are automatically recognized and normalized.
- **List Bullets:** Steps can be formatted as Markdown bullet points (`- 10. Zündung an` or `* 10. Zündung an`).
- **Code Fences & Dividers:** Fenced code blocks (```` ``` ````) and thematic breaks (`---`, `***`) are gracefully handled.

---

## 2. Document Structure & Header

A specification file may contain one or more test cases.

### Optional Header (Single Test Case)
If a file defines a single test case without an explicit header, the test case ID is derived from the file stem (e.g., `tc_01_undervoltage.txt` -> `TC_01_UNDERVOLTAGE`).

### Explicit Header (Multi-Case or Explicit Identity)
```text
TESTFALL: TC_01_UNDERVOLTAGE_RECOVERY
NAME: Unterspannung und Wiederanlauf
TESTZIEL: Nachweis des autonomen Wiederanlaufs nach Unterspannung (optional)
```

Each explicit test case must specify:
- `TESTFALL: <CASE_ID>` (must match `TC_[A-Z0-9_]{1,60}`).
- `NAME: <Human Readable Name>`.
- `TESTZIEL: <Objective>` (optional).

---

## 3. Sections

Section headings are recognized case-insensitively in both German and English:

| Standard Section | German Headings | English Headings | Purpose |
|---|---|---|---|
| **Precondition** | `Vorbedingungen`, `Vorbedingung` | `Precondition`, `Preconditions` | System setup before testing begins |
| **Action** | `Ablauf`, `Testschritte` | `Action`, `Actions` | Operational stimulus and execution flow |
| **Expected Result** | `Erwartungen`, `Erwartete Ergebnisse`, `Erwartetes Ergebnis` | `Expected`, `Expected Result`, `Expected Results` | Assertions and verification statements |
| **Postcondition** | `Nachbedingungen`, `Nachbedingung` | `Postcondition`, `Postconditions` | Teardown and cleanup actions |

---

## 4. Step Numbering & Expectation Binding

Instructions in the `Action` section may be prefixed with a positive integer step number (e.g., `10.`, `20:`).

### Binding Rules for `Expected Result`

1. **Numbered Expected Results:**
   - Must reference a valid step number present in the `Action` tree (either an action step or a `FOR` loop).
   - If referencing an action step: executed immediately after successful execution of that action step.
   - If multiple expected results reference the same step number: executed in their order of declaration in `Expected Result`.
   - If referencing a `FOR` loop step number: executed exactly once after the loop completes (or breaks).
   - If referencing a step inside a `FOR` loop: executed per iteration inside the loop body immediately following that step.
2. **Rejection of Orphan / Invalid References:**
   - Referencing a step number that does not exist in `Action` raises a **SpecError** (blocks code generation; never appended to the end).
   - Referencing a step number defined in `Precondition` or `Postcondition` raises a **SpecError**.
   - Duplicate step numbers within the `Action` tree of a test case raise a **SpecError**.
3. **Unnumbered Expected Results:**
   - Executed as final assertions after all actions and loops in `Action` have completed, prior to entering `Postcondition` cleanup.
   - Cannot reference loop-scoped variables.

---

## 5. Control Structures & Scoping

SpecToTest supports structured loops and conditional early exits:

### FOR Loop Syntax
```text
FOR (<variable>; [<item1>, <item2>, ...])
    ...
END FOR
```
With optional step numbering:
```text
10. FOR (I; [1, 2, 3])
    20. Batteriespannung = I V
END FOR
```

- **Loop Variable:** Must be a valid identifier (`[A-Za-z_]\w*`). Reserved names (`bench`, `Decimal`, `runner`, Python keywords) and variable shadowing are prohibited.
- **Items:** Homogeneous list of integers, decimals, or quoted strings. Cannot be empty.
- **Scope:** The loop variable is strictly scoped to the loop body and any expected results bound to steps inside that body. Using it outside the loop raises a `SpecError`.

### BREAK Syntax
```text
BREAK
BREAK (<variable> <operator> <value>)
```
Operators: `==`, `!=`, `<`, `<=`, `>`, `>=`.
The condition must evaluate a variable in scope against an integer, decimal, boolean, string, or another scoped variable.

---

## 6. Execution Lifecycle & Error Semantics

- **Precondition & Action Protection:** All preconditions and actions run under protected execution (`try ... finally`).
- **Postcondition Execution Guarantee:** Once a test case begins, postconditions (cleanups) are guaranteed to be attempted, even if Preconditions, Actions, or Checks raise errors.
- **Cleanup Isolation:** Each cleanup step runs in an isolated block. If cleanup step 1 fails, subsequent cleanup steps (step 2, step 3) are still executed.
- **Error Aggregation:** Primary failures in Precondition/Action/Expected and secondary errors in Cleanup are captured together.
- **Result Statuses:**
  - `PASS`: All steps and checks succeeded.
  - `FAIL`: At least one check failed (`CheckFailed`), no technical errors.
  - `ERROR`: Technical exception in execution or cleanup. `ERROR` takes precedence over `FAIL` in overall test outcome.
  - `NOT_RUN`: Steps planned but skipped due to an earlier abort.

