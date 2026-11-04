# TESTFALL: TC_12_BMS_SIGNAL_TOLERANCES_AND_RANGES
**NAME:** Tc 12 Bms Signal Tolerances And Ranges

## Precondition
10. Zündung an
20. CAN-Signal Clamp15Status auf 1 setzen
30. CAN-Signal CellVoltageMax auf 4.20 V setzen
40. CAN-Signal CellTempMax auf 45 °C setzen
50. CAN-Signal PackCurrent auf -80 A setzen
60. CAN-Signal IsolationResistance auf 1200 kOhm setzen

## Action
70. CAN-Signal CellVoltageMax auf 4.22 V setzen
80. CAN-Signal CellTempMax auf 55 °C setzen
90. CAN-Signal PackCurrent auf -120 A setzen
100. CAN-Signal IsolationResistance auf 950 kOhm setzen

## Expected Result
70. CAN-Signal CellVoltageMax ist 4.20 V ± 50 mV
80. CAN-Signal CellTempMax liegt im Bereich [50 °C, 60 °C]
80. CAN-Signal CellTempMax >= 55 °C
90. CAN-Signal PackCurrent < -100 A
100. CAN-Signal IsolationResistance <= 1000 kOhm
100. CAN-Signal IsolationResistance > 900 kOhm

## Postcondition
110. CAN-Signal CellVoltageMax auf 3.70 V setzen
120. CAN-Signal PackCurrent auf 0 A setzen
130. CAN-Signal Clamp15Status auf 0 setzen
140. Zündung aus
