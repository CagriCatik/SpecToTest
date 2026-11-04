# TESTFALL: TC_06_SERVICE_CRASH_TECHNICAL_ERROR
**NAME:** Dienstabsturz und Verbindungsabbruch erzeugen technischen ERROR

## Precondition
10. Dienst-Fehler zurücksetzen

## Action
20. Fehler CRASH_SERVICE im Dienst aktivieren
30. Datensatz CONFIG_TIMEOUT mit Wert "10" anlegen

## Postcondition
40. Dienst-Fehler zurücksetzen
