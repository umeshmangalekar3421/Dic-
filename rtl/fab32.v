// FAB-32 — the FabAware-Opt demonstration design, in real synthesizable RTL.
//
// This is the *real* design entry point. It is read by Yosys (industry
// synthesis tool) which turns it into a gate-level netlist. The hand-built
// Python netlist in fabaware/design.py is kept only as an offline fallback.
//
// Structure:
//   * 32-bit adder / logic unit
//   * 4-bit counter FSM supplying the ALU operation field
//   * 32-bit pipeline register
//
// The adder is written behaviourally on purpose: choosing the adder
// architecture (ripple / carry-lookahead / carry-select) is the synthesis
// tool's job, so the netlist we analyse is genuinely Yosys's output.

module fab32 (
    input  wire        clk,
    input  wire [31:0] a,
    input  wire [31:0] b,
    output reg  [31:0] s,
    output wire        cout,
    output wire        op2
);

    // ---------------------------------------------------------------
    // FSM: 4-bit counter. Its low bits drive the ALU operation field.
    // ---------------------------------------------------------------
    reg [3:0] cnt;
    always @(posedge clk) cnt <= cnt + 4'd1;

    wire op0 = cnt[0];
    wire op1 = cnt[1];
    assign op2 = cnt[1] & cnt[2];

    // ---------------------------------------------------------------
    // Datapath
    //   op1 op0 | operation
    //     0   0 | add
    //     0   1 | and
    //     1   0 | or
    //     1   1 | xor
    // ---------------------------------------------------------------
    wire [32:0] add_res = a + b;
    wire [31:0] sum_r   = add_res[31:0];
    assign cout         = add_res[32];

    wire [31:0] and_r = a & b;
    wire [31:0] or_r  = a | b;
    wire [31:0] xor_r = a ^ b;

    reg [31:0] alu;
    always @* begin
        case ({op1, op0})
            2'b00: alu = sum_r;
            2'b01: alu = and_r;
            2'b10: alu = or_r;
            default: alu = xor_r;
        endcase
    end

    // ---------------------------------------------------------------
    // Pipeline register
    // ---------------------------------------------------------------
    always @(posedge clk) s <= alu;

endmodule
