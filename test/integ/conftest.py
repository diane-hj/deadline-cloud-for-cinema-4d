# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.

import pytest
import os
import site
import sys

from pathlib import Path

# Default install paths per version and platform
_C4D_DEFAULT_PATHS = {
    "2025": {
        "win32": Path(r"C:\Program Files\Maxon Cinema 4D 2025"),
        "linux": Path("/opt/maxon/cinema4d-2025"),
    },
    "2026": {
        "win32": Path(r"C:\Program Files\Maxon Cinema 4D 2026"),
        "linux": Path("/opt/maxon/cinema4d-2026"),
    },
}


@pytest.fixture
def cinema4d_location() -> Path:
    if "C4D_LOCATION" in os.environ:
        return Path(os.environ["C4D_LOCATION"])

    version = os.environ.get("C4D_VERSION")
    platform_key = "win32" if sys.platform == "win32" else "linux"

    if version and version in _C4D_DEFAULT_PATHS:
        default_path = _C4D_DEFAULT_PATHS[version][platform_key]
        if default_path.exists():
            print(f"Using default Cinema 4D {version} path: {default_path}")
            return default_path

    raise EnvironmentError(
        "Cinema 4D location not found. Set C4D_LOCATION or C4D_VERSION environment variable."
    )


@pytest.fixture(autouse=True)
def _set_c4d_python_path():
    """Set C4DPYTHONPATH311 so c4dpy can find packages installed in the hatch venv.

    c4dpy uses Cinema 4D's bundled Python, not the hatch venv's Python.
    Without this, c4dpy cannot find the 'deadline' package (editable install in src/)
    or its dependencies like PySide6 (installed in the venv's site-packages).
    C4DPYTHONPATH311 is Cinema 4D's mechanism for adding extra Python paths.
    """
    # Include the project src/ dir (for editable install) and site-packages (for dependencies like PySide6)
    project_src = str(Path(__file__).parent.parent.parent / "src")
    all_paths = [project_src] + site.getsitepackages()
    existing = os.environ.get("C4DPYTHONPATH311", "")
    new_paths = os.pathsep.join(p for p in all_paths if p and p not in existing)
    os.environ["C4DPYTHONPATH311"] = f"{new_paths}{os.pathsep}{existing}" if existing else new_paths
    print(f"C4DPYTHONPATH311={os.environ.get('C4DPYTHONPATH311')}")


@pytest.fixture
def test_scenes_folder_location() -> Path:
    return Path(__file__).parent / "test_scenes"
