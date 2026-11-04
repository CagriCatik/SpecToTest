# TESTFALL: TC_03_DIAGNOSTIC_POWERCYCLE
**NAME:** Tc 03 Diagnostic Powercycle

## Precondition
10. Zündung an
20. Fehlerspeicher BCM löschen
30. Fehlerspeicher BCM1 löschen

## Action
40. Batteriespannung = 7000mV
50. Fehlerspeicher BCM1 lesen

## Expected Result
50. Fehlerspeichereintrag DTC00173 eingetragen

## Postcondition
60. Batteriespannung = 13.8V
70. Zündung aus
# Loop mit wiederholtem Schritt-Label 70 und Variable iter
70: FOR (iter;[1, 2])
71:   Warte iter
72: END FOR
80. Zündung an
90. FSP BCM1 löschen
100. Zündung aus
