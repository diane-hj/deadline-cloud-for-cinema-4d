# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.

"""
Builds a self-contained adaptor bundle directory that can be uploaded as a job attachment.

The bundle contains:
  - The adaptor source code (deadline/cinema4d_adaptor/*)
  - Runtime dependencies (openjd-adaptor-runtime and its transitive deps)
  - A wrapper script (cinema4d-openjd) to launch the adaptor

Usage:
    python scripts/adaptor_bundle.py [--output <dir>]

The output defaults to ./adaptor_bundle/ in the repo root.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


def _get_repo_root() -> Path:
    return Path(__file__).parents[1].resolve()


def _get_adaptor_deps() -> list[str]:
    """Return the pip requirements for the adaptor runtime dependencies."""
    # We need openjd-adaptor-runtime (the adaptor framework) and its transitive deps.
    # We read the version constraint from pyproject.toml to stay in sync.
    repo_root = _get_repo_root()
    if sys.version_info >= (3, 11):
        import tomllib
        mode = "rb"
    else:
        import tomli as tomllib  # type: ignore[no-redef]
        mode = "rb"

    with open(repo_root / "pyproject.toml", mode) as f:
        pyproject = tomllib.load(f)

    deps = pyproject["project"]["dependencies"]
    # Only include openjd-adaptor-runtime — the adaptor's only runtime dep
    # that isn't already available on the worker via conda or the adaptor source itself.
    adaptor_deps = []
    for dep in deps:
        dep_name = dep.strip().split(" ", maxsplit=1)[0].split(";", maxsplit=1)[0]
        # Include openjd-adaptor-runtime and deadline (needed by adaptor)
        if dep_name.startswith("openjd") or dep_name.startswith("deadline"):
            # Strip platform markers for the pip install
            pip_req = dep.strip().split(";", maxsplit=1)[0].replace(" ", "")
            # Strip [gui] extra — the adaptor doesn't need GUI dependencies
            pip_req = pip_req.split("[")[0] + pip_req.split("]")[-1] if "[" in pip_req else pip_req
            adaptor_deps.append(pip_req)
    return adaptor_deps


def build_adaptor_bundle(output_dir: Path) -> Path:
    """
    Build a self-contained adaptor bundle directory.

    Args:
        output_dir: Directory to create the bundle in. Will be cleaned if it exists.

    Returns:
        Path to the created bundle directory.
    """
    repo_root = _get_repo_root()

    # Clean and create output directory
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)

    # 1. Install runtime dependencies into the bundle
    deps = _get_adaptor_deps()
    if deps:
        pip_args = [
            sys.executable, "-m", "pip", "install",
            "--target", str(output_dir),
            "--only-binary=:all:",
            *deps,
        ]
        subprocess.run(pip_args, check=True)

    # 2. Copy the adaptor source code into the bundle.
    #    The adaptor lives at src/deadline/cinema4d_adaptor/
    #    We need to preserve the namespace package structure: deadline/cinema4d_adaptor/
    adaptor_src = repo_root / "src" / "deadline" / "cinema4d_adaptor"
    adaptor_dst = output_dir / "deadline" / "cinema4d_adaptor"

    # The deadline/ namespace package dir may already exist from pip-installed deps.
    # Don't overwrite its __init__.py (it's a namespace package — no __init__.py).
    if adaptor_dst.exists():
        shutil.rmtree(adaptor_dst)
    shutil.copytree(str(adaptor_src), str(adaptor_dst))

    # Ensure deadline/ is a namespace package (no __init__.py)
    deadline_init = output_dir / "deadline" / "__init__.py"
    if deadline_init.exists():
        deadline_init.unlink()

    # Create a _version.py if it doesn't exist (it's generated at build time by hatch-vcs)
    version_file = adaptor_dst / "_version.py"
    if not version_file.exists():
        version_file.write_text(
            '# Auto-generated for adaptor bundle\n'
            'version = "0.0.0.dev0"\n'
            'version_tuple = (0, 0, 0, "dev0")\n'
        )

    # 3. Create a wrapper script so `cinema4d-openjd` can be invoked from the bundle.
    _create_wrapper_scripts(output_dir)

    return output_dir


def _create_wrapper_scripts(bundle_dir: Path) -> None:
    """Create cinema4d-openjd wrapper scripts for Linux/Mac and Windows."""
    bin_dir = bundle_dir / "bin"
    bin_dir.mkdir(exist_ok=True)

    # Unix wrapper
    unix_wrapper = bin_dir / "cinema4d-openjd"
    unix_wrapper.write_text(
        '#!/bin/bash\n'
        'SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"\n'
        'BUNDLE_DIR="$(dirname "$SCRIPT_DIR")"\n'
        'export PYTHONPATH="${BUNDLE_DIR}:${PYTHONPATH:-}"\n'
        'exec python3 -m deadline.cinema4d_adaptor.Cinema4DAdaptor "$@"\n'
    )
    unix_wrapper.chmod(0o755)

    # Windows wrapper
    win_wrapper = bin_dir / "cinema4d-openjd.cmd"
    win_wrapper.write_text(
        '@echo off\r\n'
        'set "SCRIPT_DIR=%~dp0"\r\n'
        'set "BUNDLE_DIR=%SCRIPT_DIR%.."\r\n'
        'set "PYTHONPATH=%BUNDLE_DIR%;%PYTHONPATH%"\r\n'
        'python -m deadline.cinema4d_adaptor.Cinema4DAdaptor %*\r\n'
    )


def main():
    parser = argparse.ArgumentParser(description="Build Cinema 4D adaptor bundle for job attachment")
    parser.add_argument(
        "--output",
        type=Path,
        default=_get_repo_root() / "adaptor_bundle",
        help="Output directory for the bundle (default: ./adaptor_bundle/)",
    )
    args = parser.parse_args()
    bundle_path = build_adaptor_bundle(args.output)
    print(f"Adaptor bundle created at: {bundle_path}")


if __name__ == "__main__":
    main()
