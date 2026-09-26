# Optional ngspice netlists

These netlists are **not required** to reproduce the project numbers.
They are a hand-off for anyone who later installs [ngspice](https://ngspice.sourceforge.io/).

The Level-1 MOSFET parameters are a first-order match to the Python compact
model (SKY130 1.8 V regular-Vt Ion / Vt / tox).  They will *not* overlay
the official SkyWater BSIM6 card.

```text
ngspice -b tb/tb_inv_tran.sp
```

If you have the official SKY130 PDK, replace `.include ../models/sky130_level1.sp`
with the PDK corner file and rerun.  That is extra credit, not part of the
graded flow.
