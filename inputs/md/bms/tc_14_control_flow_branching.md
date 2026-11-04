# TESTFALL: TC_14_CONTROL_FLOW_BRANCHING
**NAME:** Tc 14 Bms Control Flow Branching
**ANFORDERUNG:** REQ_BMS_CONTROL_FLOW_001
**TESTZIEL:** Validierung der dynamischen Leistungs- und Kühlanpassung des BMS mittels bedingter Verzweigungen (IF/ELSE IF/ELSE), Zustandsauswahl (SWITCH/CASE/DEFAULT) und WHILE-Schleifen

## Precondition
10. Zündung an
20. CAN-Signal Clamp15Status auf 1 setzen
30. CAN-Signal BMSState auf 3 setzen
40. CAN-Signal CellTempMax auf 25 °C setzen
50. CAN-Signal CoolingRequest auf 0 setzen
60. CAN-Signal MaxDischargeCurrent auf 400 A setzen
70. Fehlerspeicher BMS löschen

## Action
80. CAN-Signal PackVoltage auf 400 V setzen
90: FOR (mode;[1, 2, 3])
100:  SWITCH (mode)
110:    CASE (1)
120.      CAN-Signal CellTempMax auf 30 °C setzen
130.      CAN-Signal CoolingRequest auf 0 setzen
140:    CASE (2)
150.      CAN-Signal CellTempMax auf 45 °C setzen
160.      CAN-Signal CoolingRequest auf 1 setzen
170:    DEFAULT
180.      CAN-Signal CellTempMax auf 60 °C setzen
190.      CAN-Signal CoolingRequest auf 2 setzen
200:  END SWITCH
210:  IF (mode == 1 AND mode < 2)
220.    CAN-Signal MaxDischargeCurrent auf 400 A setzen
230:  ELSE IF (mode == 2 OR mode == 99)
240.    CAN-Signal MaxDischargeCurrent auf 250 A setzen
250:  ELSE
260.    CAN-Signal MaxDischargeCurrent auf 100 A setzen
270:  END IF
280.  Warte 50 ms
290: END FOR
300: FOR (retry;[1])
301:   WHILE (retry <= 1)
302.     Fehlerspeicher BMS lesen
303:     BREAK (retry == 1)
304:   END WHILE
305: END FOR

## Expected Result
80. CAN-Signal PackVoltage ist 400 V
120. CAN-Signal CellTempMax ist 30 °C
130. CAN-Signal CoolingRequest ist 0
150. CAN-Signal CellTempMax ist 45 °C
160. CAN-Signal CoolingRequest ist 1
180. CAN-Signal CellTempMax ist 60 °C
190. CAN-Signal CoolingRequest ist 2
220. CAN-Signal MaxDischargeCurrent ist 400 A
240. CAN-Signal MaxDischargeCurrent ist 250 A
260. CAN-Signal MaxDischargeCurrent ist 100 A
90. CAN-Signal CellTempMax ist 60 °C
90. CAN-Signal CoolingRequest ist 2
90. CAN-Signal MaxDischargeCurrent ist 100 A
302. Fehlerspeichereintrag DTC_BMS_OVERTEMPERATURE in BMS eingetragen

## Postcondition
310. CAN-Signal CellTempMax auf 25 °C setzen
320. CAN-Signal CoolingRequest auf 0 setzen
330. CAN-Signal MaxDischargeCurrent auf 300 A setzen
340. CAN-Signal BMSState auf 1 setzen
350. Fehlerspeicher BMS löschen
360. CAN-Signal Clamp15Status auf 0 setzen
370. Zündung aus
