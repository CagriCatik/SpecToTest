# TESTFALL: TC_14_CONTROL_FLOW_BRANCHING
**NAME:** Tc 14 Bms Control Flow Branching
**TESTZIEL:** Validierung von Verzweigungen (IF/ELSE IF/ELSE) und Mehrfachauswahl (SWITCH/CASE/DEFAULT) innerhalb von Testabläufen

## Precondition
10. Zündung an
20. CAN-Signal Clamp15Status auf 1 setzen
30. CAN-Signal BMSState auf 3 setzen
40. CAN-Signal CellTempMax auf 25 °C setzen
50. CAN-Signal CoolingRequest auf 0 setzen

## Action
60: FOR (mode;[1, 2, 3])
61:   SWITCH (mode)
62:     CASE (1)
63.       CAN-Signal CellTempMax auf 30 °C setzen
64.       CAN-Signal CoolingRequest auf 0 setzen
65:     CASE (2)
66.       CAN-Signal CellTempMax auf 45 °C setzen
67.       CAN-Signal CoolingRequest auf 1 setzen
68:     DEFAULT
69.       CAN-Signal CellTempMax auf 60 °C setzen
70.       CAN-Signal CoolingRequest auf 2 setzen
71:   END SWITCH
72:   IF (mode == 2)
73.     Warte 50 ms
74:   ELSE IF (mode == 3)
75.     Warte 100 ms
76:   ELSE
77.     Warte 10 ms
78:   END IF
79: END FOR

## Expected Result
60. CAN-Signal CellTempMax ist 60 °C
60. CAN-Signal CoolingRequest ist 2

## Postcondition
80. CAN-Signal CellTempMax auf 25 °C setzen
90. CAN-Signal CoolingRequest auf 0 setzen
100. CAN-Signal BMSState auf 1 setzen
110. CAN-Signal Clamp15Status auf 0 setzen
120. Zündung aus
