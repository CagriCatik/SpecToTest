# TESTFALL: TC_05_SWEEP_BATCH_RECORDS
**NAME:** Mehrere Datensaetze und Schleifenverarbeitung

## Precondition
10. Dienst-Fehler zurücksetzen

## Action
20. Datensatz CACHE_KEY_1 mit Wert "batch_val_1" anlegen
30. Datensatz CACHE_KEY_2 mit Wert "batch_val_2" anlegen
40: FOR (t;[10 ms, 20 ms])
41:   Warte t
42: END FOR

## Expected Result
20. Datensatz CACHE_KEY_1 hat Wert "batch_val_1"
30. Datensatz CACHE_KEY_2 hat Wert "batch_val_2"

## Postcondition
50. Datensatz CACHE_KEY_1 löschen
60. Datensatz CACHE_KEY_2 löschen
