"""
Real-tool backends.
===================

FabAware-Opt can run on either

* **real EDA tools** when they are installed (Yosys, ngspice, OpenSTA,
  OpenROAD), or
* the **self-contained Python models** that ship with the project.

Backends are auto-detected. Nothing here is required to run the project — the
fallback models are always used for whatever is missing, and the console
reports exactly which backend produced which number.

    from fabaware.backends import tools
    tools.summary()      # what is installed and what is being used
"""

from . import tools  # noqa: F401

__all__ = ["tools", "yosys"]
