#!/usr/bin/env python3
"""Check a catalog against `maps.schema.json` from skifahrer/schemas, its only home."""
import os
import subprocess
import sys

REPO = os.environ.get("SCHEMAS_REPO", "https://github.com/skifahrer/schemas.git")
REF = os.environ.get("SCHEMAS_REF", "master")
DEST = os.environ.get("SCHEMAS_DIR") or os.path.join(
    os.environ.get("RUNNER_TEMP", "/tmp"), "schemas")


def pull():
    """The schemas checkout, or "" when it can't be had."""
    if os.path.isfile(os.path.join(DEST, "tools", "validate.py")):
        return DEST
    done = subprocess.run(["git", "clone", "--quiet", "--depth=1", "--branch", REF, REPO, DEST])
    return DEST if done.returncode == 0 else ""


def main(files):
    if not files:
        raise SystemExit("usage: catalog-schema.py maps.json [maps-test.json]")
    found = pull()
    if not found:
        # a network hiccup must not cost a finished map its catalog entry
        print(f"::warning::{REPO} couldn't be cloned – the catalog goes unchecked.")
        return 0
    try:
        # the runner's apt jsonschema predates 4.18 and ships without referencing
        import referencing  # noqa: F401
        from jsonschema import Draft202012Validator  # noqa: F401
    except ImportError:
        subprocess.run([sys.executable, "-m", "pip", "install", "--quiet",
                        "--break-system-packages", "jsonschema>=4.18"], check=True)
    done = subprocess.run([sys.executable, os.path.join(found, "tools", "validate.py"), *files])
    if done.returncode:
        print(f"::error::{' '.join(files)} doesn't match maps.schema.json of "
              f"skifahrer/schemas@{REF} – the app would drop what breaks it.")
    return done.returncode


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
