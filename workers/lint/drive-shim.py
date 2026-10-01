#!/usr/bin/env python3
"""The Drive shim withstands load and GDAL recovers from a lost connection.

When `socketserver`'s default queue of five overflows, the kernel drops the SYN
without an error on either side and GDAL prints `response_code=0` two minutes
later, which looks like a Drive error. Checked statically from `drive/serve.py`.
"""
import ast, sys

SRC = "workers/drive/serve.py"
tree = ast.parse(open(SRC).read())
bad = 0

def num(node):
    """A constant, or `socket.SOMAXCONN`."""
    if isinstance(node, ast.Constant) and isinstance(node.value, int):
        return node.value
    if isinstance(node, ast.Attribute) and node.attr == "SOMAXCONN":
        return 4096
    return None

queue = None
for node in ast.walk(tree):
    if not (isinstance(node, ast.ClassDef) and node.name == "Server"):
        continue
    for stmt in node.body:
        if (isinstance(stmt, ast.Assign) and stmt.targets
                and getattr(stmt.targets[0], "id", "")
                == "request_queue_size"):
            queue = num(stmt.value)
if queue is None or queue < 64:
    print(f"::error file={SRC}::`Server.request_queue_size` is "
          f"{queue if queue is not None else 'the default 5'} – with six "
          f"concurrent gdalwarps such a queue overflows and the kernel quietly "
          f"drops the SYN. Keep `socket.SOMAXCONN` there.")
    bad += 1
else:
    print(f"{SRC}: connection queue {queue} ✓")

# one fetch pool per process; made per `_send_multipart` it multiplies instead of capping
for node in ast.walk(tree):
    if (isinstance(node, ast.FunctionDef)
            and node.name == "_send_multipart"):
        for inner in ast.walk(node):
            if (isinstance(inner, ast.Call)
                    and getattr(inner.func, "id", "")
                    == "ThreadPoolExecutor"):
                print(f"::error file={SRC}::`_send_multipart` makes "
                      f"its own ThreadPoolExecutor – then FETCH_WORKERS "
                      f"caps nothing. Take it from `fetch_pool()`.")
                bad += 1

# GDAL needs retries and a short connect timeout, or one lost connection ends hours of work
env_src = open(SRC).read()
for key in ("GDAL_HTTP_MAX_RETRY", "GDAL_HTTP_CONNECTTIMEOUT"):
    if key not in env_src:
        print(f"::error file={SRC}::`gdal_env()` doesn't set {key} "
              f"– GDAL retries nothing by default.")
        bad += 1
    else:
        print(f"{SRC}: {key} ✓")

# a slope part must be retryable; one lost part mustn't fail a run with the rest done
tries = None
for node in ast.walk(ast.parse(open("workers/contours-rocks/slope-chunks.py").read())):
    if (isinstance(node, ast.Call)
            and getattr(node.func, "attr", "") == "add_argument"
            and node.args
            and getattr(node.args[0], "value", "") == "--tries"):
        for kw in node.keywords:
            if kw.arg == "default":
                tries = getattr(kw.value, "value", None)
if not isinstance(tries, int) or tries < 2:
    print("::error file=workers/contours-rocks/slope-chunks.py::`--tries` is missing "
          "or below 2 – one lost part then fails the whole run.")
    bad += 1
else:
    print(f"workers/contours-rocks/slope-chunks.py: tries per part {tries} ✓")

sys.exit(1 if bad else 0)
