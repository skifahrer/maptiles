#!/usr/bin/env python3
"""The run's settings block for the summary – the form and `env:`, ready to repeat the run.

Usage:
    python3 workers/plan/summary-inputs.py \\
        --inputs="$INPUTS_JSON" --workflow=.github/workflows/build-map-region.yml \\
        --with-env
"""
import argparse
import json
import os
import sys

import yaml


def defaults(path):
    """Input defaults straight from the workflow → {field: value}."""
    with open(path) as f:
        doc = yaml.safe_load(f)
    # YAML loads `on:` as True
    on = doc[[k for k in doc if k is True or k == "on"][0]]
    inputs = (on.get("workflow_dispatch") or {}).get("inputs") or {}
    return {k: text(v.get("default", "")) for k, v in inputs.items()}


def env_table(path):
    """Workflow `env:` → rows with the value the run really has; secrets never shown."""
    with open(path) as f:
        doc = yaml.safe_load(f)
    rows = []
    for k, raw in (doc.get("env") or {}).items():
        raw = text(raw)
        # the run summary of a public repo is public
        if "secrets." in raw:
            rows.append((k, "*(secret – not shown)*"))
            continue
        v = os.environ.get(k)
        if v is None:
            rows.append((k, f"`{raw}` *(from the file)*" if raw else "*(empty)*"))
        else:
            rows.append((k, f"`{v}`" if v else "*(empty)*"))
    return rows


def text(v):
    """A value as text, the way the run sees it (a boolean input is "true", not "True")."""
    if isinstance(v, bool):
        return "true" if v else "false"
    return str(v).strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--inputs", default="",
                    help="JSON of the run's input values (toJSON(inputs))")
    ap.add_argument("--workflow", default=".github/workflows/build-map-region.yml")
    ap.add_argument("--with-env", action="store_true",
                    help="also add the workflow's `env:` table (settings "
                         "not in the form)")
    args = ap.parse_args()

    try:
        values = json.loads(args.inputs or "{}")
    except json.JSONDecodeError as e:
        print(f"::warning::The run's settings couldn't be read ({e}).",
              file=sys.stderr)
        values = {}

    try:
        deflt = defaults(args.workflow)
    except (OSError, KeyError, TypeError) as e:
        print(f"::warning::The defaults couldn't be read ({e}).",
              file=sys.stderr)
        deflt = {}

    rows, changed = [], []
    for k, v in values.items():
        v = text(v)
        d = deflt.get(k)
        if d is None:
            state = "—"
        elif v == d:
            state = "default"
        else:
            state = "**not the default**"
            changed.append(k)
        rows.append("| `{}` | {} | {} |".format(
            k, f"`{v}`" if v else "*(empty)*", state))

    out = []
    if rows:
        out += ["## The form this run came from", "",
                "| field | value | |", "|---|---|---|"] + rows + [""]
        if changed:
            out += ["The *Run workflow* form always opens with the defaults, "
                    "so repeating the run needs these set again: "
                    + ", ".join(f"**{k}**" for k in changed) + ".", ""]
        elif deflt:
            out += ["All defaults – such a run repeats with a plain "
                    "*Run workflow*, nothing to change.", ""]

    if args.with_env:
        try:
            env = env_table(args.workflow)
        except (OSError, KeyError, TypeError) as e:
            print(f"::warning::The workflow's `env:` couldn't be read ({e}).",
                  file=sys.stderr)
            env = []
        if env:
            out += ["## Workflow settings (`env:`)", "",
                    "Not in the form – changed by editing "
                    f"`{args.workflow}`.", "",
                    "| setting | value |", "|---|---|"]
            out += [f"| `{k}` | {v} |" for k, v in env] + [""]

    print("\n".join(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
