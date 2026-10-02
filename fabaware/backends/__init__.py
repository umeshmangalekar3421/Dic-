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
from . import yosys  # noqa: F401
from . import ngspice  # noqa: F401
from . import opensta  # noqa: F401
from . import liberty  # noqa: F401
from . import emit  # noqa: F401
from . import crosscheck  # noqa: F401
from . import openroad  # noqa: F401
from . import pdk  # noqa: F401

__all__ = ["tools", "yosys", "ngspice", "opensta", "liberty", "emit",
           "crosscheck", "openroad", "pdk"]
