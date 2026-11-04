# TESTFALL: TC_06_CAN_SIGNAL_TRANSMISSION
**NAME:** Tc 06 Can Signal Transmission

## Precondition
10. Zündung an
20. CAN-Signal Clamp15Status auf 1 setzen
30. CAN-Signal EngineSpeed auf 0 rpm setzen
40. CAN-Signal VehicleSpeed auf 0 km/h setzen

## Action
50. CAN-Signal EngineSpeed auf 2500 rpm setzen
60. CAN-Signal VehicleSpeed auf 50 km/h setzen
70: FOR (spd;[60, 80, 100])
71:   CAN-Signal VehicleSpeed auf spd setzen
72:   Warte 100 ms
73:   BREAK (spd==80)
74: END FOR

## Expected Result
50. CAN-Signal EngineSpeed ist 2500 rpm
70. CAN-Signal VehicleSpeed ist 80 km/h

## Postcondition
80. CAN-Signal VehicleSpeed auf 0 km/h setzen
90. CAN-Signal EngineSpeed auf 0 rpm setzen
100. CAN-Signal Clamp15Status auf 0 setzen
110. Zündung aus
