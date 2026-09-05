#!/usr/bin/env python3
"""Kontrola: shim nad Drive znesie nápor a GDAL sa spamätá zo strateného spojenia.

Keď `socketserver`-u pretečie predvolená fronta piatich spojení, jadro SYN
zahodí bez chyby na oboch stranách a GDAL po dvoch minútach vypíše
`response_code=0`, čo vyzerá ako chyba Drive.

Staticky z AST `drive/serve.py`: dosť veľká fronta a `gdal_env()` nastavuje
opakovanie požiadaviek.
"""
import ast, sys

SRC = "workers/drive/serve.py"
tree = ast.parse(open(SRC).read())
bad = 0

def num(node):
    """Konštanta, alebo `socket.SOMAXCONN`."""
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
    print(f"::error file={SRC}::`Server.request_queue_size` je "
          f"{queue if queue is not None else 'predvolených 5'} – "
          f"pri šiestich súbežných gdalwarpoch taká fronta pretečie "
          f"a jadro SYN ticho zahodí (beh 31338803278). Nechaj tam "
          f"`socket.SOMAXCONN`.")
    bad += 1
else:
    print(f"{SRC}: fronta spojení {queue} ✓")

# Bazén na sťahovanie úsekov musí byť jeden na proces. Keď sa vyrába
# v `_send_multipart`, nie je to strop, ale násobenie: pri `--jobs 6`
# je z „12 vlákien" 72 a rastie to s tým, čo sa ladí kvôli rýchlosti.
for node in ast.walk(tree):
    if (isinstance(node, ast.FunctionDef)
            and node.name == "_send_multipart"):
        for inner in ast.walk(node):
            if (isinstance(inner, ast.Call)
                    and getattr(inner.func, "id", "")
                    == "ThreadPoolExecutor"):
                print(f"::error file={SRC}::`_send_multipart` si "
                      f"vyrába vlastný ThreadPoolExecutor – potom "
                      f"FETCH_WORKERS neohraničuje nič. Ber ho "
                      f"z `fetch_pool()`.")
                bad += 1

# A GDAL musí mať povolené opakovanie a krátky čas na spojenie –
# inak čaká, kým sa nevzdá jadro, a jedno stratené spojenie
# z desaťtisícov je koncom hodinovej práce.
env_src = open(SRC).read()
for key in ("GDAL_HTTP_MAX_RETRY", "GDAL_HTTP_CONNECTTIMEOUT"):
    if key not in env_src:
        print(f"::error file={SRC}::`gdal_env()` nenastavuje {key} "
              f"– GDAL predvolene neopakuje nič.")
        bad += 1
    else:
        print(f"{SRC}: {key} ✓")

# Časť sklonu sa musí dať skúsiť znova. Jedna stratená časť zo 47
# nesmie zhodiť beh, ktorý má zvyšok hotový.
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
    print("::error file=workers/contours-rocks/slope-chunks.py::`--tries` chýba "
          "alebo je menšie než 2 – jedna stratená časť potom zhodí "
          "celý beh (31338803278).")
    bad += 1
else:
    print(f"workers/contours-rocks/slope-chunks.py: pokusov na časť {tries} ✓")

sys.exit(1 if bad else 0)
