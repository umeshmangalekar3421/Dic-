# FAB-32 Architectural Specification (Handwritten Design)

## Overview
**FAB-32** is a 32-bit datapath processing block designed for fabrication-aware physical design and timing yield optimization in the SkyWater 130nm process node.

## Architectural Blocks
1. **32-Bit Carry-Select Adder**:
   - Structured into eight 4-bit blocks.
   - Dual carry chains ($C_{in} = 0$ and $C_{in} = 1$) evaluated in parallel.
   - Multiplexers select the correct sum and carry-out once the block carry arrives, minimizing critical path propagation delay.
2. **32-Bit Arithmetic Logic Unit (ALU)**:
   - Supports four operations selected by 2-bit operation field `op[1:0]`:
     - `00`: Addition (`sum_r`)
     - `01`: Bitwise AND (`a & b`)
     - `10`: Bitwise OR (`a | b`)
     - `11`: Bitwise XOR (`a ^ b`)
3. **4-Bit Up-Counter Finite State Machine (FSM)**:
   - Synchronous 4-bit counter driving control signals `op0 = cnt[0]`, `op1 = cnt[1]`, `op2 = cnt[1] & cnt[2]`.
   - Cycles ALU through arithmetic and logic operations autonomously.
4. **32-Bit Pipeline Output Register**:
   - Flip-flops capturing datapath outputs (`s[31:0]`) on the positive clock edge `clk`.

## I/O Pinout
- `clk` (Input): Master system clock.
- `a[31:0]` (Input): 32-bit primary operand A.
- `b[31:0]` (Input): 32-bit primary operand B.
- `s[31:0]` (Output): 32-bit registered datapath result.
- `cout` (Output): Carry-out bit from addition.
- `op2` (Output): Decoded FSM status signal.
