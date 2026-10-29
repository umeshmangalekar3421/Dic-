# FAB-32: Stage-by-Stage RTL-to-GDSII ML Flow Report

## Overview
This repository implements a complete, fabrication-aware, machine-learning-assisted RTL-to-GDSII flow on the **SkyWater 130nm standard cell library (`sky130_fd_sc_hd`)**.

At every stage of the flow, genuine open-source industry EDA engines (**Yosys, OpenROAD, OpenSTA, ngspice**) generate golden physical design outputs, while dedicated **Python Machine Learning models** (trained on 133,000+ silicon pins from CircuitOps) predict physical metrics in real time.

---

## Stage-by-Stage Results Summary

| Stage | EDA Ground Truth Tool | Generated Artifact | Python ML Surrogate Model | Target Metric | ML Accuracy ($R^2$) | Key Stage Result |
|---|---|---|---|---|---|---|
| **00. Handwritten** | Original RTL Entry | `fab32.v` | N/A (Baseline Specification) | Architectural Definition | — | 32-bit Carry-Select Adder + ALU + 4-bit Counter FSM |
| **01. Synthesis** | **Yosys 0.52** | `synth_fab32.v` | `synthesis_cap_model.pkl` | Net Capacitance ($fF$) | **$R^2 = 0.8618$** | 272 nets synthesized. Mean Net Cap = 30.36 fF |
| **02. Placement** | **OpenROAD (GPL/DPL)** | `placed_fab32.def` | `wirelength_model.pkl` | Routed Netlength ($nm$) | **$R^2 = 0.9958$** | 329 cells placed. Total Wirelength = 1578.09 $\mu m$ |
| **03. Routing & CTS**| **OpenROAD (Route)** | `routed_fab32.def` | `slew_model.pkl` | Pin Transition Slew ($ps$) | **$R^2 = 0.8459$** | Clean detailed routing: **0 DRC violations**. Mean Slew = 1054.16 ps |
| **04. Timing Signoff**| **OpenSTA 3.1.0** | `opensta_signoff.rpt` | `slack_model.pkl` | Setup Slack ($ps$) | **$R^2 = 0.9125$** | Signoff setup slack: **worst slack max 7.63**. Mean ML Slack = -3908.0 ps |
| **05. Yield Opt** | **ngspice + GP** | `optimized_fab32.v` | **Active Learning GP** | Monte Carlo Yield | Bayesian Optimization | Yield boosted from **41.0% $\to$ 100.0%** ($W_p/W_n = 1.172$) |

---

## Directory Index (`o/p/`)

```
o/p/
├── 00_original_handwritten/
│   ├── fab32.v                         # Original synthesizable behavioral Verilog RTL
│   ├── fab32_python_structural.v       # Gate-level structural Verilog netlist
│   ├── handwritten_architecture_spec.md# Architectural specification & pinout
│   └── handwritten_metrics.json        # Design statistics (gates, flops, ports)
│
├── 01_stage1_synthesis/
│   ├── synth_fab32.v                   # Yosys synthesized gate-level Verilog netlist
│   ├── synthesis_report.txt            # Full Yosys synthesis execution log
│   ├── stage1_net_cap_prediction.csv   # ML Model 1 predicted net load capacitances
│   └── stage1_synthesis_summary.json   # Synthesis metrics summary
│
├── 02_stage2_placement/
│   ├── placed_fab32.def                # OpenROAD placed DEF (components & coordinates)
│   ├── cell_placement_coordinates.csv  # Standard cell (x, y) coordinates
│   ├── stage2_wirelength_prediction.csv# ML Model 2 predicted routed wirelengths
│   └── stage2_placement_summary.json   # Placement density & core utilization
│
├── 03_stage3_routing/
│   ├── routed_fab32.def                # OpenROAD routed DEF with CTS buffers & metal wires
│   ├── cts_routing_report.txt          # CTS insertion and routing log
│   ├── stage3_slew_prediction.csv      # ML Model 3 predicted transition slews
│   └── stage3_routing_summary.json     # DRC check results & routing statistics
│
├── 04_stage4_timing/
│   ├── opensta_signoff.rpt             # OpenSTA signoff timing report
│   ├── critical_path_breakdown.txt     # Top critical path breakdown
│   ├── stage4_slack_prediction.csv     # ML Model 4 predicted slacks vs ground truth
│   └── stage4_timing_summary.json      # Setup/hold slacks and path delays
│
├── 05_stage5_yield/
│   ├── optimized_fab32.v               # Final ML/GP-optimized netlist
│   ├── yield_optimization_report.txt   # Comprehensive Monte Carlo yield report
│   ├── yield_monte_carlo.csv           # 100-chip Monte Carlo simulation results
│   ├── yield_distribution.png          # Baseline vs Optimized Yield comparison plot
│   └── stage5_yield_summary.json       # Transistor ratios & yield improvement
│
└── flow_summary.md                     # This summary document
```
