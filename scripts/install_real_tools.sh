#!/usr/bin/env bash
#
# Install the real EDA tools that FabAware-Opt can use.
#
# Every tool here is OPTIONAL. The project runs without any of them and
# falls back to its own Python models. Installing them simply upgrades the
# corresponding layer from "simulated" to "real".
#
#   bash scripts/install_real_tools.sh            # install everything we can
#   bash scripts/install_real_tools.sh --check    # just report what's there
#
set -uo pipefail

GREEN=$'\033[32m'; YELLOW=$'\033[33m'; RED=$'\033[31m'; OFF=$'\033[0m'
ok()   { printf "  ${GREEN}%-12s${OFF} %s\n" "$1" "$2"; }
miss() { printf "  ${YELLOW}%-12s${OFF} %s\n" "$1" "$2"; }

# ---------------------------------------------------------------------------
check() {
    printf "\nReal-tool backends\n"
    printf -- "-------------------\n"
    for t in yosys ngspice opensta openroad iverilog klayout; do
        if command -v "$t" >/dev/null 2>&1; then
            ok "$t" "installed -> $(command -v "$t")"
        elif command -v "yowasp-$t" >/dev/null 2>&1; then
            ok "$t" "installed (yowasp) -> $(command -v "yowasp-$t")"
        else
            miss "$t" "not installed"
        fi
    done
    printf "\n"
}

    printf "\nPDK\n"
    printf -- "-------------------\n"
    found=0
    for d in "$HOME"/.volare/volare/sky130/versions/*; do
        [[ -d "$d" ]] || continue
        ok "sky130" "$(basename "$d")"
        found=1
    done
    [[ $found -eq 0 ]] && miss "sky130" "not installed"
    if command -v volare >/dev/null 2>&1; then
        ok "volare" "installed -> $(command -v volare)"
    else
        miss "volare" "not installed - needed for the SKY130 PDK"
    fi
    printf "\n"

if [[ "${1:-}" == "--check" ]]; then
    check
    python3 -c "from fabaware.backends import tools; print(tools.summary())" \
        2>/dev/null || true
    exit 0
fi

# ---------------------------------------------------------------------------
PY="${PYTHON:-python3}"
echo "FabAware-Opt real-tool installer"
echo "================================"

# --- Yosys -----------------------------------------------------------------
# Needed for `fabaware-run --real`. Try apt first; fall back to the pip
# (WebAssembly) build, which needs no root and works on any platform.
if command -v yosys >/dev/null 2>&1 || command -v yowasp-yosys >/dev/null 2>&1; then
    ok "yosys" "already installed"
else
    echo "installing Yosys (RTL synthesis)..."
    if sudo -n apt-get install -y yosys >/dev/null 2>&1; then
        ok "yosys" "installed via apt"
    elif "$PY" -m pip install --quiet --user yowasp-yosys 2>/dev/null; then
        ok "yosys" "installed via pip (yowasp-yosys)"
    else
        miss "yosys" "FAILED - try: sudo apt install yosys"
    fi
fi

# --- ngspice ---------------------------------------------------------------
# Transistor-level simulation; replaces fabaware/compact.py when present.
if command -v ngspice >/dev/null 2>&1; then
    ok "ngspice" "already installed"
else
    echo "installing ngspice (SPICE simulation)..."
    if sudo -n apt-get install -y ngspice >/dev/null 2>&1; then
        ok "ngspice" "installed via apt"
    elif sudo -n dnf install -y ngspice >/dev/null 2>&1; then
        ok "ngspice" "installed via dnf"
    elif command -v brew >/dev/null 2>&1 && brew install ngspice >/dev/null 2>&1; then
        ok "ngspice" "installed via brew"
    else
        miss "ngspice" "FAILED - try: sudo apt install ngspice"
    fi
fi

# --- Icarus Verilog --------------------------------------------------------
# Optional: lets you functionally simulate the synthesized netlist.
if command -v iverilog >/dev/null 2>&1; then
    ok "iverilog" "already installed"
else
    echo "installing iverilog (netlist simulation)..."
    if sudo -n apt-get install -y iverilog >/dev/null 2>&1; then
        ok "iverilog" "installed via apt"
    else
        miss "iverilog" "FAILED - optional, safe to skip"
    fi
fi

# --- OpenSTA / OpenROAD ----------------------------------------------------
# Not packaged by distros. These need to be built or downloaded; we only give
# instructions rather than guessing at your platform.
for tool in opensta openroad; do
    if command -v "$tool" >/dev/null 2>&1; then
        ok "$tool" "already installed"
    else
        miss "$tool" "not packaged - see docs/REAL_TOOLS.md section 2"
    fi
done

# --- Optional PDK ----------------------------------------------------------
read -r -p $'\nInstall the open SkyWater SKY130 PDK? [y/N] ' reply
if [[ "${reply,,}" == "y" ]]; then
    echo "fetching SKY130 (this downloads a few GB)..."
    if "$PY" -m pip install --quiet --user volare 2>/dev/null; then
        "$PY" -m volare enable --pdk sky130 \
            0fe599b2afb6708d281543108caf8310912f54af \
            && ok "sky130" "PDK installed" \
            || miss "sky130" "download failed - see docs/REAL_TOOLS.md section 3"
    else
        miss "sky130" "could not install volare"
    fi
fi

echo
check
echo "Done. Run the flow with real tools:"
echo "    fabaware-run --real"
echo "Verify what is live:"
echo "    python3 -c 'from fabaware.backends import tools; print(tools.summary())'"
