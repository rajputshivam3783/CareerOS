"""Minimal runner for the dependency-free V25.6 unit tests, for environments without
pytest (it supports the small subset of pytest used in those files: parametrize and
raises). In a normal environment just run ``python -m pytest``."""
import importlib
import inspect
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_REAL_PYTEST = False
if "pytest" not in sys.modules:
    try:
        import pytest  # noqa: F401

        _REAL_PYTEST = True
    except ImportError:
        shim = types.ModuleType("pytest")

        class _Raises:
            def __init__(self, exc, match=None):
                self.exc, self.match = exc, match

            def __enter__(self):
                return self

            def __exit__(self, et, ev, tb):
                import re
                if et is None:
                    raise AssertionError(f"DID NOT RAISE {self.exc}")
                if not issubclass(et, self.exc):
                    return False
                if self.match and not re.search(self.match, str(ev)):
                    raise AssertionError(f"{ev!r} does not match {self.match!r}")
                return True

        class _Mark:
            @staticmethod
            def parametrize(names, values):
                def deco(fn):
                    fn._params = (names, values)
                    return fn
                return deco

        shim.raises = lambda exc, match=None: _Raises(exc, match)
        shim.mark = _Mark()
        shim.parametrize = _Mark.parametrize
        sys.modules["pytest"] = shim


def run(module_name: str) -> tuple[int, int]:
    mod = importlib.import_module(module_name)
    passed = failed = 0
    for name, fn in sorted(vars(mod).items()):
        if not (name.startswith("test_") and inspect.isfunction(fn)):
            continue
        cases = [()]
        if hasattr(fn, "_params"):
            names, values = fn._params
            names = [n.strip() for n in names.split(",")]
            cases = [v if isinstance(v, tuple) and len(names) > 1 else (v,) for v in values]
        for args in cases:
            try:
                fn(*args)
                passed += 1
            except Exception as exc:  # noqa: BLE001
                failed += 1
                print(f"FAIL {module_name}.{name}{args!r:.80}: {type(exc).__name__}: {exc}")
    return passed, failed


if __name__ == "__main__":
    modules = sys.argv[1:] or ["tests.test_v25_6_hardening_unit"]
    if _REAL_PYTEST:
        # pytest is installed: let it run the files (it implements parametrize/raises natively; the tiny
        # fallback runner below only understands the subset needed when pytest is absent).
        import pytest as _pytest

        root = Path(__file__).resolve().parents[1]
        paths = [str(root / (m.replace(".", "/") + ".py")) if not m.endswith(".py") else m for m in modules]
        sys.exit(int(_pytest.main(["-q", "-p", "no:cacheprovider", *paths])))
    total_p = total_f = 0
    for m in modules:
        p, f = run(m)
        total_p += p
        total_f += f
    print(f"passed={total_p} failed={total_f}")
    sys.exit(1 if total_f else 0)
