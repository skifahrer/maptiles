"""Loads a worker by path, since dashed file names can't be imported."""
import importlib.util
import os
import sys
import unittest

WORKERS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def worker(path, name=None):
    """`workers/<path>` as a module; its folder goes on `sys.path` for sibling imports."""
    full = os.path.join(WORKERS, path)
    folder = os.path.dirname(full)
    if folder not in sys.path:
        sys.path.insert(0, folder)
    name = name or "w_" + path.replace("/", "_").replace("-", "_").removesuffix(".py")
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, full)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def needs(*modules):
    """Skip without `modules`; with `TESTS_REQUIRE_ALL=1` a skip is a failure."""
    missing = [m for m in modules if importlib.util.find_spec(m) is None]
    if missing and os.environ.get("TESTS_REQUIRE_ALL") == "1":
        raise ImportError(f"TESTS_REQUIRE_ALL=1, yet missing: {', '.join(missing)}")
    return unittest.skipIf(missing, f"needs {', '.join(missing)}")
