#!/usr/bin/env bash
#
# install_real_tools.sh — set up every real EDA tool FabAware-Opt can use.
#
#   bash scripts/install_real_tools.sh              # install everything
#   bash scripts/install_real_tools.sh --check      # just report what's there
#   bash scripts/install_real_tools.sh --no-pdk     # skip the 333 MB PDK
#   bash scripts/install_real_tools.sh --with-opensta   # also build OpenSTA
#
# Every tool here is OPTIONAL for running the project — it falls back to its
# own Python models for whatever is missing. Installing them upgrades the
# corresponding layer from "simulated" to "real".
#
# The script is idempotent: run it twice and it will skip what is installed.
#
set -uo pipefail

GREEN=$'\033[32m'; YELLOW=$'\033[33m'; RED=$'\033[31m'; DIM=$'\033[2m'; OFF=$'\033[0m'
ok()   { printf "  ${GREEN}%-12s${OFF} %s\n" "$1" "$2"; }
miss() { printf "  ${YELLOW}%-12s${OFF} %s\n" "$1" "$2"; }
bad()  { printf "  ${RED}%-12s${OFF} %s\n" "$1" "$2"; }
hdr()  { printf "\n${DIM}%s${OFF}\n" "$1"; }

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# ---------------------------------------------------------------------------
# package manager detection
# ---------------------------------------------------------------------------
detect_pkg() {
    if   command -v apt-get >/dev/null 2>&1; then echo apt
    elif command -v dnf     >/dev/null 2>&1; then echo dnf
    elif command -v yum     >/dev/null 2>&1; then echo yum
    elif command -v pacman  >/dev/null 2>&1; then echo pacman
    elif command -v zypper  >/dev/null 2>&1; then echo zypper
    elif command -v apk     >/dev/null 2>&1; then echo apk
    else echo none
    fi
}
PKG="$(detect_pkg)"

# install a distro package, trying the detected manager
pkg_install() {
    local pkg="$1"
    case "$PKG" in
        apt)    sudo apt-get install -y "$pkg" >/dev/null 2>&1 ;;
        dnf)    sudo dnf install -y "$pkg" >/dev/null 2>&1 ;;
        yum)    sudo yum install -y "$pkg" >/dev/null 2>&1 ;;
        pacman) sudo pacman -S --noconfirm "$pkg" >/dev/null 2>&1 ;;
        zypper) sudo zypper install -y "$pkg" >/dev/null 2>&1 ;;
        apk)    sudo apk add "$pkg" >/dev/null 2>&1 ;;
        *)      return 1 ;;
    esac
}

# ---------------------------------------------------------------------------
# reporting
# ---------------------------------------------------------------------------
check() {
    hdr "Real-tool backends"
    for t in yosys ngspice opensta openroad iverilog klayout; do
        if command -v "$t" >/dev/null 2>&1; then
            ok "$t" "installed -> $(command -v "$t")"
        elif command -v "yowasp-$t" >/dev/null 2>&1; then
            ok "$t" "installed (yowasp) -> $(command -v "yowasp-$t")"
        else
            miss "$t" "not installed"
        fi
    done

    hdr "PDK"
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
        miss "volare" "not installed (needed for the SKY130 PDK)"
    fi
    printf "\n"
}

if [[ "${1:-}" == "--check" ]]; then
    echo "FabAware-Opt — installation report"
    echo "package manager: ${PKG}"
    check
    ( cd "$HERE" && python3 -c "from fabaware.backends import tools; print(tools.summary())" 2>/dev/null )
    exit 0
fi

# ---------------------------------------------------------------------------
DO_PDK=1; DO_OPENSTA=0
for a in "$@"; do
    case "$a" in
        --no-pdk)       DO_PDK=0 ;;
        --with-opensta) DO_OPENSTA=1 ;;
    esac
done

PY="${PYTHON:-python3}"
command -v "$PY" >/dev/null 2>&1 || { bad "python3" "not found - install Python 3.9+ first"; exit 1; }

echo "FabAware-Opt — real-tool installer"
echo "=================================="
echo "  distro package manager : $PKG"
echo "  python                 : $($PY --version 2>&1)"
echo "  project                : $HERE"
echo

# --- Python environment -----------------------------------------------------
hdr "1/6  Python environment"
if [[ ! -d "$HERE/venv" ]]; then
    echo "  creating a virtual environment in venv/ ..."
    if $PY -m venv "$HERE/venv" 2>/dev/null; then
        ok "venv" "created"
    else
        miss "venv" "creation failed - installing python3-venv"
        if [[ "$PKG" != "none" ]]; then
            pkg_install python3-venv && $PY -m venv "$HERE/venv" \
                && ok "venv" "created" || bad "venv" "FAILED"
        fi
    fi
else
    ok "venv" "already present"
fi

VENV_PY="$HERE/venv/bin/python"
[[ -x "$VENV_PY" ]] || VENV_PY="$PY"

if "$VENV_PY" -c "import numpy, scipy, sklearn, matplotlib" 2>/dev/null; then
    ok "deps" "numpy/scipy/sklearn/matplotlib already installed"
else
    echo "  installing numpy, scipy, scikit-learn, matplotlib (~300 MB) ..."
    if "$VENV_PY" -m pip install --quiet -e "$HERE[dev,web]" 2>/dev/null; then
        ok "deps" "installed"
    else
        bad "deps" "FAILED - try: venv/bin/python -m pip install -e '.[dev,web]'"
    fi
fi

# --- Yosys ------------------------------------------------------------------
hdr "2/6  Yosys (RTL synthesis)"
if command -v yosys >/dev/null 2>&1 || command -v yowasp-yosys >/dev/null 2>&1; then
    ok "yosys" "already installed"
else
    echo "  installing Yosys ..."
    if [[ "$PKG" != "none" ]] && pkg_install yosys; then
        ok "yosys" "installed via $PKG"
    elif "$VENV_PY" -m pip install --quiet yowasp-yosys 2>/dev/null; then
        ok "yosys" "installed via pip (yowasp-yosys, WebAssembly build)"
    else
        bad "yosys" "FAILED - try: sudo $PKG install yosys"
    fi
fi

# --- ngspice ----------------------------------------------------------------
hdr "3/6  ngspice (transistor simulation)"
if command -v ngspice >/dev/null 2>&1; then
    ok "ngspice" "already installed"
else
    echo "  installing ngspice ..."
    if [[ "$PKG" != "none" ]] && pkg_install ngspice; then
        ok "ngspice" "installed via $PKG"
    else
        bad "ngspice" "FAILED - try: sudo $PKG install ngspice"
    fi
fi

# --- SKY130 PDK -------------------------------------------------------------
hdr "4/6  SKY130 PDK (real cell library)"
if [[ $DO_PDK -eq 0 ]]; then
    miss "sky130" "skipped (--no-pdk)"
else
    if command -v volare >/dev/null 2>&1; then
        ok "volare" "already installed"
    else
        echo "  installing volare ..."
        if "$VENV_PY" -m pip install --quiet volare 2>/dev/null; then
            ok "volare" "installed"
        else
            bad "volare" "FAILED - try: pip install volare"
        fi
    fi

    # find volare on PATH - it may have landed in the venv
    VOLARE="$(command -v volare || echo "$HERE/venv/bin/volare")"

    if [[ -x "$VOLARE" ]]; then
        if ls -d "$HOME"/.volare/volare/sky130/versions/* >/dev/null 2>&1; then
            ok "sky130" "already installed ($(ls "$HOME"/.volare/volare/sky130/versions | tail -1))"
        else
            echo "  resolving the latest SKY130 build ..."
            VER="$(curl -sL https://api.github.com/repos/chipfoundry/volare/releases/latest 2>/dev/null \
                   | sed -n 's/.*"tag_name" *: *"sky130-\([^"]*\)".*/\1/p' | head -1)"
            if [[ -z "$VER" ]]; then
                bad "sky130" "could not resolve the latest version (network blocked?)"
                echo "           run manually:  volare enable --pdk sky130 <version>"
            else
                echo "  downloading SKY130 $VER (~333 MB compressed) ..."
                if "$VOLARE" enable --pdk sky130 "$VER" 2>&1 | tail -3; then
                    ok "sky130" "installed ($VER)"
                else
                    bad "sky130" "download FAILED - check your network"
                fi
            fi
        fi
    else
        bad "volare" "not on PATH after install"
    fi
fi

# --- OpenSTA ----------------------------------------------------------------
hdr "5/6  OpenSTA (static timing analysis)"
if command -v sta >/dev/null 2>&1; then
    ok "opensta" "already installed"
elif [[ $DO_OPENSTA -eq 0 ]]; then
    miss "opensta" "skipped - not in package managers"
    echo "           to build it:  bash scripts/install_real_tools.sh --with-opensta"
    echo "           or download a binary from the OpenROAD releases page"
else
    echo "  building OpenSTA from source (this takes ~10-20 minutes) ..."
    if [[ "$PKG" != "none" ]]; then
        pkg_install cmake || true
        pkg_install swig || true
        pkg_install tcl-dev || pkg_install tcl-devel || true
        pkg_install libboost-all-dev || pkg_install boost-devel || true
    fi
    TMP="$(mktemp -d)"
    if git clone --depth 1 https://github.com/parallaxsw/OpenSTA.git "$TMP/OpenSTA" 2>/dev/null; then
        mkdir -p "$TMP/OpenSTA/build" && cd "$TMP/OpenSTA/build" \
            && cmake .. >/dev/null 2>&1 && make -j"$(nproc)" >/dev/null 2>&1 \
            && sudo make install >/dev/null 2>&1 \
            && ok "opensta" "built and installed" \
            || bad "opensta" "build failed - see $TMP/OpenSTA/build"
    else
        bad "opensta" "could not clone the repository"
    fi
fi

# --- OpenROAD ---------------------------------------------------------------
hdr "6/6  OpenROAD (place & route)"
if command -v openroad >/dev/null 2>&1; then
    ok "openroad" "already installed"
else
    miss "openroad" "not in any package manager - manual install required"
    echo "           fastest route is a prebuilt binary:"
    echo "             https://github.com/Precision-Innovations/OpenROAD/releases"
    echo "           unzip it, then either add it to PATH or:"
    echo "             export FABAWARE_OPENROAD=/path/to/openroad"
fi

# ---------------------------------------------------------------------------
echo
echo "=================================="
echo "Installation report"
check
echo "Next steps:"
echo "  1. activate the environment:  source venv/bin/activate"
echo "  2. verify everything works:   python3 scripts/verify_real_backends.py"
echo "  3. run the full flow:         fabaware-run --real --spice"
if [[ $DO_PDK -eq 1 ]]; then
    echo "  4. with the PDK:             fabaware-run --pdk sky130 --pdr --sta"
fi
echo
