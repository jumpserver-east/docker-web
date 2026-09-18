#!/usr/bin/env python3
"""Select matching dependency branches while preserving the triggering revision."""

import argparse
import subprocess
import sys


REPOSITORIES = {
    "lina": "https://github.com/jumpserver-east/lina.git",
    "luna": "https://github.com/jumpserver-east/luna.git",
    "web": "https://github.com/jumpserver-east/docker-web.git",
}


def resolve_branch(repository, source_branch):
    branch = source_branch.removeprefix("refs/heads/")
    base_branch = branch.partition("@")[2]
    candidates = list(dict.fromkeys(candidate for candidate in (branch, base_branch, "dev") if candidate))
    refs = [f"refs/heads/{candidate}" for candidate in candidates]
    result = subprocess.run(
        ["git", "ls-remote", "--heads", repository, *refs],
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    available_refs = {line.split("\t", 1)[1] for line in result.stdout.splitlines() if "\t" in line}
    for candidate, ref in zip(candidates, refs):
        if ref in available_refs:
            return candidate
    raise RuntimeError(f"No matching branch in {repository}; tried: {', '.join(candidates)}")


def resolve_refs(component, source_branch, source_ref, overrides=None):
    overrides = overrides or {}
    return {
        f"{name.upper()}_REF": (
            source_ref if name == component else
            overrides.get(name) or resolve_branch(repository, source_branch)
        )
        for name, repository in REPOSITORIES.items()
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--component", choices=REPOSITORIES)
    parser.add_argument("--source-branch", required=True)
    parser.add_argument("--source-ref")
    for component in REPOSITORIES:
        parser.add_argument(f"--{component}-ref", default="")
    args = parser.parse_args()
    if bool(args.component) != bool(args.source_ref):
        parser.error("--component and --source-ref must be supplied together")
    overrides = {name: getattr(args, f"{name}_ref") for name in REPOSITORIES}
    for value in [args.source_branch, args.source_ref, *overrides.values()]:
        if value and any(ord(character) < 32 or ord(character) == 127 for character in value):
            parser.error("Build references must not contain control characters")
    try:
        refs = resolve_refs(args.component, args.source_branch, args.source_ref, overrides)
    except (RuntimeError, subprocess.SubprocessError) as error:
        print(f"Failed to resolve build branches: {error}", file=sys.stderr)
        return 1
    for name, ref in refs.items():
        print(f"{name}={ref}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
