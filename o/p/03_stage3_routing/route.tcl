read_liberty /home/umesh/.volare/sky130A/libs.ref/sky130_fd_sc_hd/lib/sky130_fd_sc_hd__tt_025C_1v80.lib
read_lef /home/umesh/.volare/sky130A/libs.ref/sky130_fd_sc_hd/techlef/sky130_fd_sc_hd__max.tlef
read_lef /home/umesh/.volare/sky130A/libs.ref/sky130_fd_sc_hd/techlef/sky130_fd_sc_hd__min.tlef
read_lef /home/umesh/.volare/sky130A/libs.ref/sky130_fd_sc_hd/techlef/sky130_fd_sc_hd__nom.tlef
read_lef /home/umesh/.volare/sky130A/libs.ref/sky130_fd_sc_hd/techlef/sky130_fd_sc_hd__rram__max.tlef
read_lef /home/umesh/.volare/sky130A/libs.ref/sky130_fd_sc_hd/techlef/sky130_fd_sc_hd__rram__min.tlef
read_lef /home/umesh/.volare/sky130A/libs.ref/sky130_fd_sc_hd/techlef/sky130_fd_sc_hd__rram__nom.tlef
read_lef /home/umesh/.volare/sky130A/libs.ref/sky130_fd_sc_hd/lef/sky130_ef_sc_hd.lef
read_lef /home/umesh/.volare/sky130A/libs.ref/sky130_fd_sc_hd/lef/sky130_fd_sc_hd.lef
read_def /home/umesh/Academic/DIC/CP/o/p/02_stage2_placement/placed_fab32.def
read_sdc /home/umesh/Academic/DIC/CP/o/p/02_stage2_placement/fab32.sdc
estimate_parasitics -placement
repair_design
repair_clock_nets
clock_tree_synthesis -root_buf sky130_fd_sc_hd__clkbuf_16 -buf_list sky130_fd_sc_hd__clkbuf_16 -sink_clustering_size 10 -sink_clustering_max_diameter 50
set_propagated_clock [all_clocks]
detailed_placement
global_route -guide_file /home/umesh/Academic/DIC/CP/o/p/03_stage3_routing/route.guide -congestion_iterations 50 -verbose
detailed_route -output_drc /home/umesh/Academic/DIC/CP/o/p/03_stage3_routing/route_drc.rpt -output_maze /home/umesh/Academic/DIC/CP/o/p/03_stage3_routing/route_maze.log -verbose 0
write_def /home/umesh/Academic/DIC/CP/o/p/03_stage3_routing/routed_fab32.def
report_checks -path_delay max -fields {slew capacitance input_pin net fanout} -digits 4 > /home/umesh/Academic/DIC/CP/o/p/03_stage3_routing/openroad_cts_sta.rpt
exit