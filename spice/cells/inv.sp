* Static CMOS inverter, SKY130-like 1.8 V
* Nodes: in out vdd vss
.subckt INV in out vdd vss wn=0.42u wp=0.84u l=0.15u
Mn out in vss vss nfet_01v8 W={wn} L={l}
Mp out in vdd vdd pfet_01v8 W={wp} L={l}
.ends INV
