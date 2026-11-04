# TESTFALL: TC_03_DATA_CORRUPTION_DETECTION
**NAME:** Dienstfehler Datenverfaelschung wird zuverlaessig als FAIL erkannt

## Precondition
10. Dienst-Fehler zurücksetzen
20. Fehler CORRUPT_DATA im Dienst aktivieren

## Action
30. Datensatz CONFIG_TIMEOUT mit Wert "30" anlegen

## Expected Result
30. Datensatz CONFIG_TIMEOUT hat Wert "30"

## Postcondition
40. Dienst-Fehler zurücksetzen
50. Datensatz CONFIG_TIMEOUT löschen
