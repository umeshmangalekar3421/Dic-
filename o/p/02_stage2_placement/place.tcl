read_liberty /home/umesh/.volare/sky130A/libs.ref/sky130_fd_sc_hd/lib/sky130_fd_sc_hd__tt_025C_1v80.lib
read_lef /home/umesh/.volare/sky130A/libs.ref/sky130_fd_sc_hd/techlef/sky130_fd_sc_hd__max.tlef
read_lef /home/umesh/.volare/sky130A/libs.ref/sky130_fd_sc_hd/techlef/sky130_fd_sc_hd__min.tlef
read_lef /home/umesh/.volare/sky130A/libs.ref/sky130_fd_sc_hd/techlef/sky130_fd_sc_hd__nom.tlef
read_lef /home/umesh/.volare/sky130A/libs.ref/sky130_fd_sc_hd/techlef/sky130_fd_sc_hd__rram__max.tlef
read_lef /home/umesh/.volare/sky130A/libs.ref/sky130_fd_sc_hd/techlef/sky130_fd_sc_hd__rram__min.tlef
read_lef /home/umesh/.volare/sky130A/libs.ref/sky130_fd_sc_hd/techlef/sky130_fd_sc_hd__rram__nom.tlef
read_lef /home/umesh/.volare/sky130A/libs.ref/sky130_fd_sc_hd/lef/sky130_ef_sc_hd.lef
read_lef /home/umesh/.volare/sky130A/libs.ref/sky130_fd_sc_hd/lef/sky130_fd_sc_hd.lef
read_verilog /home/umesh/Academic/DIC/CP/o/p/01_stage1_synthesis/synth_fab32.v
link_design fab32
read_sdc /home/umesh/Academic/DIC/CP/o/p/02_stage2_placement/fab32.sdc
initialize_floorplan -die_area "0 0 80.0 80.0" -core_area "5.0 5.0 75.0 75.0" -site unithd
make_tracks
place_pins -hor_layers met3 -ver_layers met2
global_placement -density 0.60 -pad_left 2 -pad_right 2 -overflow 0.2
detailed_placement
write_def /home/umesh/Academic/DIC/CP/o/p/02_stage2_placement/placed_fab32.def
exit