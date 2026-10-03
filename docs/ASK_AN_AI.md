# A prompt to learn this project from another AI

Copy everything inside the box below and paste it into any AI chat
(ChatGPT, Claude, Gemini, Grok…). It is written to be **self-contained** —
the other AI does not need access to your repository.

> **Tip:** after the AI answers, paste in `docs/METHODOLOGY.md` and
> `README.md` and ask *"given what I actually built, correct or deepen
> anything you just told me"*. That second pass is usually the most
> valuable part, because the first answer will be generic and the second
> one will be about *your* code.

---

```
You are my tutor for one long conversation. Teach me from absolute zero.

ABOUT ME
--------
I am an undergraduate engineering student. I have ZERO prior knowledge of
semiconductors, VLSI, chip design, EDA tools, or how a chip is manufactured.
Assume I know programming (Python) but nothing about hardware. Treat every
term of art as unknown until you have defined it.

ABOUT THE PROJECT I BUILT
-------------------------
It is called FabAware-Opt: "AI-Assisted Process-Variation-Aware
Standard-Cell and Physical-Design Optimization for Improved ASIC Yield".

It is a SOFTWARE-ONLY project. It does not fabricate a chip. The accurate
one-sentence scope is: "A fabrication-aware, open-source EDA optimization
framework evaluated through transistor simulation and RTL-to-GDSII
experiments."

The idea it demonstrates: when transistors are manufactured, they come out
slightly different from each other and from what was designed. Because of
that, some finished chips run slower than intended. The project asks an AI
to choose better transistor sizes and wiring choices so that a much larger
fraction of manufactured chips actually work.

The five layers of the project (the actual filenames):
  compact.py   - a fast mathematical model of a transistor
  design.py    - builds a 32-bit arithmetic chip design (a netlist)
  pd.py        - estimates the physical layout (placement + wiring)
  sta.py       - estimates how fast the chip runs, across manufacturing variation
  optimizer.py - THE PART THAT IS ACTUALLY OURS: an AI search (Gaussian
                 process + expected improvement) that picks 13 design
                 settings to maximise yield

The project can also call real industry tools instead of its own models:
  Yosys     -> real synthesis of Verilog into gates        (WORKS, verified)
  ngspice   -> real transistor simulation (BSIM model)     (written, needs install)
  OpenSTA   -> real timing analysis                        (written, needs install)
  OpenROAD  -> real place & route                          (written, needs PDK)
  SKY130    -> a real open-source cell library (PDK)       (written, needs install)
  optimizer.py stays ours - no standard tool does this job.

MEASURED RESULTS I NEED HELP INTERPRETING
-----------------------------------------
Running the tool on a netlist produced by real Yosys:
  timing yield:      34.5%  ->  100.0%   (+65.5 percentage points)
  worst slack:       -3.2 ps -> +57.6 ps
  DRC violations:    225    ->  0
  cell area:         1504   ->  1880 um2   (+25%)
  power:             0.308  ->  0.316 mW   (+2.6%)
The AI's winning move was switching the wiring to different metal layers and
lowering cell density to relieve congestion.

WHAT I WANT YOU TO TEACH ME, IN THIS ORDER
------------------------------------------
1. THE PHYSICAL STORY FIRST.
   What actually is a chip, physically? What is a transistor and how does it
   switch? How are chips manufactured (in plain terms - no cleanroom
   engineering needed, just the logic of the process)? Why can't
   manufacturing make every transistor identical?

2. WHAT "PROCESS VARIATION" AND "YIELD" MEAN.
   Why do apparently identical chips behave differently? What does it mean
   for a chip to "fail timing"? Why is yield a percentage, and why does it
   translate directly into money?

3. THE DESIGN FLOW (RTL-to-GDSII), ONE STEP AT A TIME.
   Take me from "an idea" to "a physical chip", naming each stage: what
   goes in, what comes out, and which software tool does it. Specifically
   explain: RTL/Verilog, synthesis, standard cells, a cell library,
   floorplanning, placement, clock tree synthesis, routing, sign-off,
   tape-out, and DRC. Explain what a Liberty (.lib) file and a LEF file
   contain and why they matter.

4. WHERE MY PROJECT SITS IN THAT FLOW.
   Draw me a clear picture of which stages my five Python modules stand in
   for, and which stages the real tools (Yosys, ngspice, OpenSTA, OpenROAD)
   would occupy. Make explicit what my project does NOT do.

5. THE CORE IDEA MY PROJECT ADDS.
   Explain the optimisation loop in plain language: what the 13 decision
   variables are, why drive strength / transistor width ratio / buffer
   insertion / metal layer choice / placement density each affect yield,
   and how a Gaussian-process surrogate with expected improvement can find
   a good answer in ~40 evaluations instead of millions.

6. HELP ME READ MY OWN RESULTS.
   Walk through the table above line by line. Explain the trade-off:
   area and power went UP while yield went to 100% - why is that a good
   deal, and when would it not be? Explain "slack", "Vmin", and why only
   3 of 5 PVT corners passing is an honest result rather than a failure.

7. THE HONEST LIMITS.
   Tell me plainly what my project does NOT prove, what would be needed to
   make the numbers credible to an actual chip designer, and what claims I
   must never make (it does not fabricate anything).

TEACHING RULES - PLEASE FOLLOW THESE
------------------------------------
- Start from first principles. Never use a specialist term without defining
  it the first time, in one plain sentence.
- Use analogies, and tell me where each analogy breaks down - I do not want
  a comfortable lie.
- Build up: do not mention a concept that depends on something you have not
  yet explained.
- Use concrete numbers and orders of magnitude. "A nanometre is to a metre
  as a marble is to the Earth" is more useful to me than "1e-9 m".
- Where a step has an input and an output, say so explicitly.
- At the end of each of the 7 sections, stop and ask me 2-3 questions to
  check I understood. Wait for my answers before continuing.
- If I ask a question that reveals I have misunderstood something earlier,
  go back and fix the foundation rather than answering on top of it.
- Prefer "here is the intuition" before "here is the formula".

FINALLY
-------
Give me a one-page summary I could read before a viva/presentation: what
the problem is, what the approach is, what the numbers are, what the
limits are. It must be defensible to an examiner who actually knows chip
design.
```

---

## Suggested follow-ups

Once the first AI has taught you the basics, these prompts get you the
parts that are specific to *your* code:

1. **Deepen it.** Paste `docs/METHODOLOGY.md` and ask:
   *"Given what you just taught me, explain my actual methodology document
   back to me. Flag anything that is hand-wavy, unjustified, or that a
   knowledgeable examiner would challenge."*

2. **Pressure-test the claims.** Paste `docs/VALIDATION.md` and ask:
   *"Attack this. What is the weakest claim, and what experiment would
   actually settle it?"*

3. **Prepare for the viva.** Ask:
   *"Generate 15 questions a sceptical examiner would ask about this
   project, hardest first, with the answer you'd expect from a strong
   student."*

4. **Team split.** Paste `docs/TEAM.md` and ask:
   *"Here is how three students are splitting this work. Is the split
   fair, and is each part independently demonstrable?"*
