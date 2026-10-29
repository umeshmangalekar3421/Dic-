read_liberty /home/umesh/.volare/sky130A/libs.ref/sky130_fd_sc_hd/lib/sky130_fd_sc_hd__tt_025C_1v80.lib
read_verilog /home/umesh/Academic/DIC/CP/o/p/01_stage1_synthesis/synth_fab32.v
link_design fab32
read_sdc /home/umesh/Academic/DIC/CP/o/p/02_stage2_placement/fab32.sdc
report_checks -path_delay max -fields {slew capacitance input_pin net fanout} -digits 4 > /home/umesh/Academic/DIC/CP/o/p/04_stage4_timing/opensta_signoff.rpt
report_worst_slack -max > /home/umesh/Academic/DIC/CP/o/p/04_stage4_timing/worst_setup_slack.txt
report_worst_slack -min > /home/umesh/Academic/DIC/CP/o/p/04_stage4_timing/worst_hold_slack.txt
exit