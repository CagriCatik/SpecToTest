# TESTFALL: TC_10_BMS_THERMAL_DERATING_SWEEP
**NAME:** Tc 10 Bms Thermal Derating Sweep
**ANFORDERUNG:** REQ_BMS_THERMAL_DERATING_001

## Precondition
10. Zündung an
20. CAN-Signal Clamp15Status auf 1 setzen
30. CAN-Signal BMSState auf 3 setzen
40. CAN-Signal CellTempMax auf 25 °C setzen
50. CAN-Signal CoolingRequest auf 0 setzen
60. CAN-Signal MaxDischargeCurrent auf 400 A setzen

## Action
70: FOR (temp;[35, 45, 55, 65])
71:   CAN-Signal CellTempMax auf temp setzen
72:   Warte 50 ms
73:   BREAK (temp == 55)
74: END FOR
80. CAN-Signal CoolingRequest auf 2 setzen
90. CAN-Signal MaxDischargeCurrent auf 150 A setzen
100. Warte 100 ms

## Expected Result
70. CAN-Signal CellTempMax ist 55 °C
80. CAN-Signal CoolingRequest ist 2
90. CAN-Signal MaxDischargeCurrent ist 150 A

## Postcondition
110. CAN-Signal CellTempMax auf 25 °C setzen
120. CAN-Signal CoolingRequest auf 0 setzen
130. CAN-Signal MaxDischargeCurrent auf 300 A setzen
140. CAN-Signal BMSState auf 1 setzen
150. CAN-Signal Clamp15Status auf 0 setzen
160. Zündung aus
