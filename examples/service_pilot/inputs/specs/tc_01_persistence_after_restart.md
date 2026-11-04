# TESTFALL: TC_01_PERSISTENCE_AFTER_RESTART
**NAME:** Datensatz bleibt nach Kaltstart des Dienstes auf der Festplatte erhalten

## Precondition
10. Dienst neu starten
20. Dienst-Fehler zurücksetzen

## Action
30. Datensatz USER_SESSION mit Wert "active_session_42" anlegen
40. Dienst neu starten

## Expected Result
40. Datensatz USER_SESSION hat Wert "active_session_42"

## Postcondition
50. Datensatz USER_SESSION löschen
