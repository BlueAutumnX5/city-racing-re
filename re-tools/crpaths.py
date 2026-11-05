"""re-tools shim: the real path config is ../crpaths.py (scripts here run with re-tools first on sys.path)."""
import importlib.util as _ilu
import os as _os

_spec = _ilu.spec_from_file_location(
    "_crpaths_root", _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), "crpaths.py"))
_root = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(_root)
globals().update({k: v for k, v in vars(_root).items() if not k.startswith("__")})
