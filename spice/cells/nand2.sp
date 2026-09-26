* 2-input NAND
.subckt NAND2 a b out vdd vss wn=0.84u wp=0.84u l=0.15u
Mna n1 a vss vss nfet_01v8 W={wn} L={l}
Mnb out b n1  vss nfet_01v8 W={wn} L={l}
Mpa out a vdd vdd pfet_01v8 W={wp} L={l}
Mpb out b vdd vdd pfet_01v8 W={wp} L={l}
.ends NAND2
