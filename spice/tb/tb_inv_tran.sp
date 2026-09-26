* Transient FO4-ish inverter chain (3 stages, load = 4x mid stage)
.include ../models/sky130_level1.sp
.include ../cells/inv.sp

Vdd vdd 0 1.8
Vin in  0 PULSE(0 1.8 0.2n 10p 10p 0.5n 1n)

X1 in  n1  vdd 0 INV wn=0.42u wp=0.84u
X2 n1  n2  vdd 0 INV wn=1.68u wp=3.36u
X3 n2  out vdd 0 INV wn=6.72u wp=13.44u
Cload out 0 5f

.tran 1p 2n
.measure tran tphl trig v(n1) val=0.9 rise=1 targ v(n2) val=0.9 fall=1
.measure tran tplh trig v(n1) val=0.9 fall=1 targ v(n2) val=0.9 rise=1
.end
