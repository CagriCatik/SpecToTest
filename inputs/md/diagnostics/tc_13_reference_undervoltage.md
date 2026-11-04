# TESTFALL: TC_UNDERVOLTAGE_REFERENCE
**NAME:** Unterspannung mit Fehlerspeicherprüfung

## Precondition
10. Zündung an
20. Fehlerspeicher BCM1 löschen
30. Batteriespannung = 13.8V

## Action
40. Batteriespannung = 7000mV
50. Warte 1 s
60. Fehlerspeicher BCM1 lesen

## Expected Result
60. Fehlerspeichereintrag DTC00173 eingetragen

## Postcondition
70. Batteriespannung = 13.8V
80. Zündung aus
90. Fehlerspeicher BCM1 löschen
