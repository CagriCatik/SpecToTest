# TESTFALL: TC_04_PARAMETER_LIMITS_SWEEP
**NAME:** Tc 04 Parameter Limits Sweep

## Precondition
10. Bildschirm HOME auswählen
20. Parameter LIMIT auf 0 schreiben
30. Parameter GAIN auf 0 schreiben

## Action
40. Parameter LIMIT auf 50 schreiben
50. Parameter GAIN auf 25 schreiben
60. Bildschirm SETTINGS auswählen
70: FOR (v;[10, 20, 30])
71:   Parameter LIMIT auf v schreiben
72:   Warte 100 ms
73:   BREAK (v==20)
74: END FOR

## Expected Result
60. Anzeige zeigt "Settings"
70. Parameter LIMIT ist 20

## Postcondition
80. Parameter LIMIT auf 0 schreiben
90. Parameter GAIN auf 0 schreiben
100. Bildschirm HOME auswählen
