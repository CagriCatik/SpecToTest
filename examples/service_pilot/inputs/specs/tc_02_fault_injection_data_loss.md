# TESTFALL: TC_02_FAULT_INJECTION_DATA_LOSS
**NAME:** Dienstfehler Datenverlust beim Neustart wird zuverlässig als FAIL erkannt

## Precondition
10. Dienst neu starten
20. Fehler DROP_ON_RESTART im Dienst aktivieren

## Action
30. Datensatz AUTH_TOKEN mit Wert "secret_token_xyz" anlegen
40. Dienst neu starten

## Expected Result
40. Datensatz AUTH_TOKEN hat Wert "secret_token_xyz"

## Postcondition
50. Dienst-Fehler zurücksetzen
60. Datensatz AUTH_TOKEN löschen
