"""Source-checkout compatibility without shadowing the installed src package.

``python pyforge.py`` retains the original GUI route. ``python -m pyforge``
reaches the CLI, including when invoked from this checkout's root directory.
"""

import importlib.util
import sys
from pathlib import Path

_source = Path(__file__).resolve().parent / "src"

if __name__ == "__main__":
    sys.path.insert(0, str(_source))
    if __spec__ is not None and __spec__.name == "pyforge":
        from pyforge.cli import main
    else:
        from pyforge.gui import main

    raise SystemExit(main())
else:
    # Root imports otherwise select this file instead of src/pyforge. Expose
    # the real package without a duplicate package or a GUI side effect.
    _spec = importlib.util.spec_from_file_location(
        __name__,
        _source / "pyforge" / "__init__.py",
        submodule_search_locations=[str(_source / "pyforge")],
    )
    if _spec is None or _spec.loader is None:
        raise ImportError("Cannot locate PyForge's source package; install it or restore src/.")
    _package = importlib.util.module_from_spec(_spec)
    sys.modules[__name__] = _package
    _spec.loader.exec_module(_package)
