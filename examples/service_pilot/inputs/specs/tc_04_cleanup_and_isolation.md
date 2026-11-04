# TESTFALL: TC_04_CLEANUP_AND_ISOLATION
**NAME:** Nachbedingungen loeschen temporaere Datensaetze fuer saubere Isolation

## Precondition
10. Dienst-Fehler zurücksetzen
20. Datensatz TEMP_DATA mit Wert "initial_99" anlegen

## Action
30. Warte 10 ms

## Expected Result
30. Datensatz TEMP_DATA hat Wert "initial_99"

## Postcondition
40. Datensatz TEMP_DATA löschen
