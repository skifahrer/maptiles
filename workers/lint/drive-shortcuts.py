#!/usr/bin/env python3
"""A Drive folder listing must resolve shortcuts, not skip them."""
import importlib.util
import io
import os
import sys
import types
from contextlib import redirect_stdout

_HERE = os.path.dirname(os.path.abspath(__file__))
_WORKERS = os.path.dirname(_HERE)


def load():
    """`folder.py` without anything asking Drive."""
    spec = importlib.util.spec_from_file_location(
        "folder_under_test", os.path.join(_WORKERS, "drive", "folder.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def fake(folder, targets):
    """A folder as Drive returns it: a real file and two shortcuts."""
    page = {"files": [
        {"id": "r1", "name": "_Readme.txt", "size": "3805",
         "mimeType": "text/plain", "ownedByMe": False},
        {"id": "s1", "name": "N49E020.zip", "mimeType": folder.SHORTCUT_MIME,
         "ownedByMe": False,
         "shortcutDetails": {"targetId": "t1",
                             "targetMimeType": "application/zip"}},
        # a shortcut whose target is deleted – Drive then sends no `targetId`
        {"id": "s2", "name": "N49E021.zip", "mimeType": folder.SHORTCUT_MIME,
         "ownedByMe": False, "shortcutDetails": {}},
    ]}
    folder.auth = types.SimpleNamespace(
        api_get=lambda creds, path: page,
        file_info=lambda creds, fid: targets[fid])


def main():
    folder = load()
    target = {"id": "t1", "name": "N49E020.zip", "size": "10952932",
              "mimeType": "application/zip", "ownedByMe": True}
    fake(folder, {"t1": target})

    bad = []
    files, skipped = folder.listing(None, "fake")
    names = {f["name"]: f for f in files}

    if "N49E020.zip" not in names:
        bad.append("the shortcut wasn't resolved – `listing` dropped the tile "
                   "though its target exists (the bug this check exists for)")
    else:
        item = names["N49E020.zip"]
        if item["id"] != "t1":
            bad.append(f"`{item['id']}` (the shortcut) would be downloaded "
                       f"instead of target `t1` – a shortcut can't be downloaded")
        if item["size"] != 10952932:
            bad.append(f"size {item['size']} isn't the target's (should be 10952932)")
        if not item["owned"]:
            bad.append("`owned` isn't taken from the target – the daily download "
                       "cap hangs on the TARGET's owner, not the shortcut's")

    if not any("without a target" in s for s in skipped):
        bad.append("a broken shortcut (no `targetId`) wasn't skipped with an "
                   "explanation – the caller wouldn't know what the folder lacks")

    # a target of another name: a tile's name promises its area
    fake(folder, {"t1": dict(target, name="N48E020.zip")})
    log = io.StringIO()
    with redirect_stdout(log):
        folder.listing(None, "fake")
    if "::warning::" not in log.getvalue():
        bad.append("a shortcut to a file of ANOTHER name didn't warn – a tile "
                   "with another degree's data would result and nobody would know")

    for error in bad:
        print(f"::error file=workers/drive/folder.py::{error}")
    print(f"Drive shortcuts: {len(bad)} errors")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
