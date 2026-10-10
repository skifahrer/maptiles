"""Loads a worker by path, since dashed file names can't be imported."""
import importlib.util
import os
import shutil
import sys
import unittest

WORKERS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def worker(path, name=None):
    """`workers/<path>` as a module; its folder goes on `sys.path` for sibling imports."""
    full = os.path.join(WORKERS, path)
    folder = os.path.dirname(full)
    name = name or "w_" + path.replace("/", "_").replace("-", "_").removesuffix(".py")
    if name in sys.modules:
        return sys.modules[name]
    _own_siblings(folder)
    spec = importlib.util.spec_from_file_location(name, full)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _own_siblings(folder):
    """Bare sibling imports (`import tiles`) resolve in `folder`, not another job's."""
    if folder in sys.path:
        sys.path.remove(folder)
    sys.path.insert(0, folder)
    for f in os.listdir(folder):
        mod = sys.modules.get(f.removesuffix(".py")) if f.endswith(".py") else None
        if mod and os.path.dirname(getattr(mod, "__file__", "") or "") != folder:
            del sys.modules[f.removesuffix(".py")]


def needs(*modules):
    """Skip without `modules`; with `TESTS_REQUIRE_ALL=1` a skip is a failure."""
    return _skip([m for m in modules if importlib.util.find_spec(m) is None])


def needs_cmd(*commands):
    """`needs` for programs on `PATH`."""
    return _skip([c for c in commands if shutil.which(c) is None])


def _skip(missing):
    if missing and os.environ.get("TESTS_REQUIRE_ALL") == "1":
        raise ImportError(f"TESTS_REQUIRE_ALL=1, yet missing: {', '.join(missing)}")
    return unittest.skipIf(missing, f"needs {', '.join(missing)}")
