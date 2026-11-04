# TESTFALL: TC_07_CONTROLDESK_HIL_SIMULATION
**NAME:** Tc 07 Controldesk Hil Simulation

## Precondition
10. Zündung an
20. Versorgung auf 13.5 V setzen
30. Parameter GAIN auf 0 schreiben
40. CAN-Signal BatteryVoltageCAN auf 13.5 V setzen
50. CAN-Signal DoorContactStatus auf 0 setzen

## Action
60. Parameter GAIN auf 42 schreiben
70. CAN-Signal DoorContactStatus auf 1 setzen
80. CAN-Signal BrakePedalPosition auf 75 % setzen
90. Warte 200 ms

## Expected Result
60. Parameter GAIN ist 42
70. Auf CAN-Signal DoorContactStatus == 1 warten, maximal 1 s, Prüfintervall 50 ms
80. CAN-Signal BrakePedalPosition ist 75 %

## Postcondition
110. Parameter GAIN auf 0 schreiben
120. CAN-Signal DoorContactStatus auf 0 setzen
130. CAN-Signal BrakePedalPosition auf 0 % setzen
140. Zündung aus
