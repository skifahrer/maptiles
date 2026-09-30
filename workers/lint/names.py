#!/usr/bin/env python3
"""A name a worker reads must also be written.

Workers with a dash in the name load through `importlib` (`plan = _load(…)`),
so neither `bash -n` nor an import sees `plan.SLOPE_CELLS_PER_S`. Two things are
guarded: `alias.NAME` on a loaded module, and reading UPPER-CASE names in the
same file (constants are written so, local names aren't).
"""
import ast
import builtins
import glob
import os
import sys

FILES = sorted(glob.glob("workers/**/*.py", recursive=True))
BUILTIN = set(dir(builtins))


def is_constant(name):
    return name[:1].isupper() and name.upper() == name and name not in BUILTIN


def top_names(tree):
    """Names a module binds at top level – the ones it can export."""
    names = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            names.update(a.asname or a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.AnnAssign):
            names.update(bound(node.target))
        elif isinstance(node, ast.AugAssign):
            names.update(bound(node.target))
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                names.update(bound(target))
        elif isinstance(node, (ast.For, ast.AsyncFor)):
            names.update(bound(node.target))
        elif isinstance(node, (ast.If, ast.Try, ast.With, ast.While)):
            # `try: import x / except: x = None` and the like
            names.update(top_names(ast.Module(body=node.body, type_ignores=[])))
            for branch in (getattr(node, "orelse", []), getattr(node, "finalbody", [])):
                names.update(top_names(ast.Module(body=branch, type_ignores=[])))
            for h in getattr(node, "handlers", []):
                names.update(top_names(ast.Module(body=h.body, type_ignores=[])))
    return names


def bound(target):
    if isinstance(target, ast.Name):
        return {target.id}
    if isinstance(target, ast.Starred):
        return bound(target.value)
    if isinstance(target, (ast.Tuple, ast.List)):
        return set().union(*(bound(p) for p in target.elts)) if target.elts else set()
    return set()


def all_bound(node):
    """Everything bound anywhere under a node – enough for local names."""
    names = set()
    for p in ast.walk(node):
        if isinstance(p, ast.Name) and isinstance(p.ctx, (ast.Store, ast.Del)):
            names.add(p.id)
        elif isinstance(p, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(p.name)
        elif isinstance(p, (ast.Import, ast.ImportFrom)):
            names.update(a.asname or a.name.split(".")[0] for a in p.names)
        elif isinstance(p, ast.arg):
            names.add(p.arg)
        elif isinstance(p, ast.ExceptHandler) and p.name:
            names.add(p.name)
        elif isinstance(p, ast.Global):
            names.update(p.names)
    return names


def loaded_modules(path, tree):
    """`alias = _load("name", "…/file.py")` → alias: that file's path."""
    out = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        if not isinstance(node.targets[0], ast.Name):
            continue
        expr = node.value
        if not isinstance(expr, ast.Call) or not isinstance(expr.func, ast.Name):
            continue
        if expr.func.id not in ("_load", "load"):
            continue
        # the last string argument is the file name, `os.path.join` too
        files = [t.value for a in expr.args for t in ast.walk(a)
                  if isinstance(t, ast.Constant) and isinstance(t.value, str)
                  and t.value.endswith(".py")]
        if not files:
            continue
        target = os.path.join(os.path.dirname(path), files[-1])
        if not os.path.exists(target):
            matches = [f for f in FILES if os.path.basename(f) == files[-1]]
            if len(matches) != 1:
                continue
            target = matches[0]
        out[node.targets[0].id] = target
    return out


def errors_in(path, trees):
    tree = trees[path]
    wrong = []

    modules = loaded_modules(path, tree)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute) or not isinstance(node.ctx, ast.Load):
            continue
        if not isinstance(node.value, ast.Name) or node.value.id not in modules:
            continue
        target = modules[node.value.id]
        if node.attr not in top_names(trees[target]):
            wrong.append((node.lineno,
                        f"`{node.value.id}.{node.attr}` reads from `{target}`, "
                        f"but that name isn't there"))

    top = top_names(tree) | BUILTIN | {"__file__", "__name__", "__doc__"}
    for func in [u for u in ast.walk(tree)
                    if isinstance(u, (ast.FunctionDef, ast.AsyncFunctionDef))]:
        local = all_bound(func)
        for p in ast.walk(func):
            if not isinstance(p, ast.Name) or not isinstance(p.ctx, ast.Load):
                continue
            if is_constant(p.id) and p.id not in top and p.id not in local:
                wrong.append((p.lineno, f"`{p.id}` is read but set nowhere"))
    return wrong


def main():
    trees = {}
    for path in FILES:
        try:
            trees[path] = ast.parse(open(path, encoding="utf-8").read(), path)
        except SyntaxError as e:
            print(f"::error file={path},line={e.lineno}::{e.msg}")
            return 1
    bad = 0
    for path in FILES:
        for line, message in sorted(set(errors_in(path, trees))):
            print(f"::error file={path},line={line}::{message}. "
                  f"Shortening a comment must not delete the line with the value.")
            bad += 1
    print(f"names that must exist: {bad} errors")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
