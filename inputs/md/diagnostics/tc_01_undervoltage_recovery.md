# TESTFALL: TC_01_UNDERVOLTAGE_RECOVERY
**NAME:** Tc 01 Undervoltage Recovery
**ANFORDERUNG:** REQ_DIAG_UNDERVOLTAGE_001

## Precondition
10. Zündung an
20. Fehlerspeicher BCM1 löschen
30. Batteriespannung = 13.8V

## Action
40. Batteriespannung = 7000mV
50. Warte 1 s
60. Fehlerspeicher BCM1 lesen
70. Batteriespannung = 13.8V
80. Warte 500 ms

## Expected Result
60. Fehlerspeichereintrag DTC00173 eingetragen

## Postcondition
90. Batteriespannung = 13.8V
100. Zündung aus
110. FSP BCM1 löschen
