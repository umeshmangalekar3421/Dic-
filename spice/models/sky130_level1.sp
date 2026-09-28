* First-order Level-1 MOSFET card matching the Python compact model
* SKY130 1.8 V regular-Vt, NOT the official BSIM6 card.
* tox = 4.14 nm, Vto ~ 0.48/ -0.495, kp from Ion targets.

.model nfet_01v8 NMOS LEVEL=1
+ VTO=0.48 KP=2.4e-4 GAMMA=0.5 PHI=0.7 LAMBDA=0.06
+ TOX=4.14e-9 CGSO=2.0e-10 CGDO=2.0e-10 CJ=2.0e-4 MJ=0.5

.model pfet_01v8 PMOS LEVEL=1
+ VTO=-0.495 KP=1.1e-4 GAMMA=0.5 PHI=0.7 LAMBDA=0.08
+ TOX=4.14e-9 CGSO=2.0e-10 CGDO=2.0e-10 CJ=2.0e-4 MJ=0.5
