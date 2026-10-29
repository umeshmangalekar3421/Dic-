# FabAware-Opt: generated constraints for P&R
create_clock -name clk -period 10 [get_ports {clk}]
set_clock_uncertainty 0.0 [get_clocks *]
set_input_transition 0.010 [all_inputs]
set_load 0.005 [all_outputs]

