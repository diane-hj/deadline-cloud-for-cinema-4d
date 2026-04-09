#!/usr/bin/env python3
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
"""Setup runner for Cinema 4D integration tests in CodeBuild."""

import argparse
import hashlib
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path


# Installer details from BealineCondaRecipe-Cinema4D conda recipes.
# S3 paths are relative to the INSTALLER_BUCKET (common-bealinerezpackage-resources-bucket).
C4D_INSTALLERS = {
    "2025": {
        "windows": {
            "s3_key": "cinema4d/2025/Cinema4D_2025_2025.3.3_Win.zip",
            "sha256": "fcf0ea40af73727f1bc1fb1a47ea0c2f3476f0652824d3b740181dc1a6123e09",
            "type": "zip",
        },
        "linux": {
            "s3_key": "cinema4d/2025/Cinema4D_2025_2025.3.1_Linux.zip",
            "sha256": "40b4a85d38dcdf5fa19fa19b03efde6494fe3e482b96836d5b736956133ff98f",
            "type": "zip",
        },
    },
    "2026": {
        "windows": {
            "s3_key": "cinema4d/2026/Cinema4D_2026_2026.0_Win.exe",
            "sha256": "412b069a00b39564aaaa7c1ccfa080d9e154669028e3521b96282c4dfcfd4024",
            "type": "exe",
        },
        "linux": {
            # linux-64-2026 conda recipe uses Cinema 4D 2025.3.1
            "s3_key": "cinema4d/2025/Cinema4D_2025_2025.3.1_Linux.zip",
            "sha256": "40b4a85d38dcdf5fa19fa19b03efde6494fe3e482b96836d5b736956133ff98f",
            "type": "zip",
        },
    },
}

# Where Cinema 4D gets installed/extracted to
C4D_INSTALL_PATHS = {
    "2025": {
        "windows": Path("C:/Program Files/Maxon Cinema 4D 2025"),
        "linux": Path("/opt/maxon/cinema4d-2025"),
    },
    "2026": {
        "windows": Path("C:/Program Files/Maxon Cinema 4D 2026"),
        "linux": Path("/opt/maxon/cinema4d-2026"),
    },
}


def run(cmd, check=True):
    """Run a shell command, exiting on failure if check is True."""
    print(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd)
    if check and result.returncode != 0:
        sys.exit(result.returncode)
    return result


def download_from_s3(s3_key, local_path):
    """Download a file from the DCC installer bucket."""
    bucket = os.environ.get("INSTALLER_BUCKET")
    if not bucket:
        print("ERROR: INSTALLER_BUCKET not set")
        sys.exit(1)
    run(["aws", "s3", "cp", f"s3://{bucket}/{s3_key}", str(local_path), "--no-progress"])


def verify_checksum(file_path, expected_checksum):
    """Verify SHA256 checksum of downloaded file."""
    print(f"Verifying checksum for {file_path}...")
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
    actual = sha256.hexdigest()
    if actual != expected_checksum:
        print("ERROR: Checksum mismatch!")
        print(f"  Expected: {expected_checksum}")
        print(f"  Actual:   {actual}")
        sys.exit(1)
    print("OK Checksum verified")


def setup_windows(versions):
    """Install Cinema 4D on Windows for each version."""
    # Enable long paths to avoid MAX_PATH (260 char) limit on CodeBuild
    run(["reg", "add", "HKLM\\SYSTEM\\CurrentControlSet\\Control\\FileSystem",
         "/v", "LongPathsEnabled", "/t", "REG_DWORD", "/d", "1", "/f"], check=False)

    for version in versions:
        install_dir = C4D_INSTALL_PATHS[version]["windows"]
        marker = install_dir / ".installed"

        if marker.exists():
            print(f"Cinema 4D {version} already installed at {install_dir}")
            continue

        print(f"Installing Cinema 4D {version}...")
        installer_info = C4D_INSTALLERS[version]["windows"]
        local_installer = Path(f"C:/Temp/{Path(installer_info['s3_key']).name}")
        local_installer.parent.mkdir(parents=True, exist_ok=True)

        download_from_s3(installer_info["s3_key"], local_installer)
        verify_checksum(local_installer, installer_info["sha256"])

        if installer_info["type"] == "zip":
            # 2025: Portable/zero-install — extract and move cinema4d folder
            extract_dir = Path(f"C:/Temp/c4d_{version}")
            run([
                "powershell", "-Command",
                f"Expand-Archive -Path '{local_installer}' -DestinationPath '{extract_dir}' -Force",
            ])
            # The zip contains a cinema4d subfolder — move it to install path
            extracted_c4d = next(extract_dir.glob("*/"), None)
            if extracted_c4d:
                install_dir.parent.mkdir(parents=True, exist_ok=True)
                run([
                    "powershell", "-Command",
                    f"Move-Item -Path '{extracted_c4d}' -Destination '{install_dir}' -Force",
                ])
            run(["powershell", "-Command", f"Remove-Item -Path '{extract_dir}' -Recurse -Force"], check=False)
        elif installer_info["type"] == "exe":
            # 2026: Actual installer — run with unattended mode
            print(f"Running installer: {local_installer}")
            result = subprocess.run(
                [str(local_installer), "--mode", "unattended", "--unattendedmodeui", "none", "--prefix", str(install_dir)],
                capture_output=True, text=True,
            )
            print(f"Installer exit code: {result.returncode}")
            print(f"Installer stdout: {result.stdout}")
            print(f"Installer stderr: {result.stderr}")

        local_installer.unlink(missing_ok=True)

        if install_dir.exists():
            print(f"SUCCESS: Cinema 4D {version} installed at {install_dir}")
            print(f"Contents: {list(install_dir.iterdir())[:20]}")
            marker.touch()
        else:
            # Debug: find where Cinema 4D actually installed
            print(f"ERROR: Cinema 4D {version} not found at {install_dir}")
            print("Searching for Cinema 4D installation...")
            run(["powershell", "-Command", "Get-ChildItem 'C:\\Program Files\\Maxon*' -ErrorAction SilentlyContinue"], check=False)
            run(["powershell", "-Command", "Get-ChildItem 'C:\\Program Files' | Where-Object { $_.Name -like '*Cinema*' -or $_.Name -like '*Maxon*' }"], check=False)
            run(["powershell", "-Command", "Get-ChildItem 'C:\\' -Directory | Where-Object { $_.Name -like '*Cinema*' -or $_.Name -like '*Maxon*' }"], check=False)
            run(["powershell", "-Command", "Get-ChildItem $env:LOCALAPPDATA -Directory -ErrorAction SilentlyContinue | Where-Object { $_.Name -like '*Maxon*' }"], check=False)
            sys.exit(1)

    # Smoke test disabled — c4dpy may require interactive Maxon login
    # Actual tests use Commandline.exe via the adaptor instead

    # Configure RLM licensing by appending to config.txt
    rlm_license = os.environ.get("RLM_LICENSE")
    if rlm_license:
        for version in versions:
            install_dir = C4D_INSTALL_PATHS[version]["windows"]
            config_txt = install_dir / "resource" / "config.txt"
            if config_txt.exists():
                content = config_txt.read_text()
                if "g_licenseServerRLM" not in content:
                    with open(config_txt, "a") as f:
                        f.write(f"\ng_licenseServerRLM={rlm_license}\n")
                    print(f"Configured RLM licensing ({rlm_license}) in {config_txt}")
                else:
                    print(f"RLM licensing already configured in {config_txt}")
            else:
                print(f"WARNING: config.txt not found at {config_txt}")

        # Install pywin32 and deadline package into C4D's Python
        c4d_site_packages = install_dir / "resource" / "modules" / "python" / "libs" / "win64" / "lib" / "site-packages"
        c4d_python = install_dir / "resource" / "modules" / "python" / "libs" / "win64" / "python.exe"
        if c4d_python.exists():
            run([str(c4d_python), "-m", "ensurepip"], check=False)
            if not (c4d_site_packages / "pywin32.pth").exists():
                print("Installing pywin32 into C4D's Python...")
                run([str(c4d_python), "-m", "pip", "install", "pywin32==308", "-t", str(c4d_site_packages)])
                # Copy pywin32 DLLs to the dlls folder
                dlls_dir = install_dir / "resource" / "modules" / "python" / "libs" / "win64" / "dlls"
                pywin32_sys = c4d_site_packages / "pywin32_system32"
                if pywin32_sys.exists() and dlls_dir.exists():
                    for dll in pywin32_sys.glob("*.dll"):
                        shutil.copy(str(dll), str(dlls_dir))
                        print(f"Copied {dll.name} to {dlls_dir}")
            # Install deadline-cloud-for-cinema-4d into C4D's Python so c4dpy can find it
            print("Installing deadline-cloud-for-cinema-4d into C4D's Python...")
            run([str(c4d_python), "-m", "pip", "install", "-e", ".", "-t", str(c4d_site_packages)], check=False)

    # Set encoding for C4D Python
    os.environ["PYTHONIOENCODING"] = "utf-8"


def setup_linux(versions):
    """Install Cinema 4D on Linux for each version."""
    for version in versions:
        install_dir = C4D_INSTALL_PATHS[version]["linux"]
        marker = install_dir / ".installed"

        if marker.exists():
            print(f"Cinema 4D {version} already installed at {install_dir}")
            # Verify c4dpy exists, otherwise reinstall
            c4dpy = install_dir / "c4dpy"
            if not c4dpy.exists():
                print(f"c4dpy not found, removing marker and reinstalling...")
                marker.unlink()
            else:
                continue

        print(f"Installing Cinema 4D {version}...")
        installer_info = C4D_INSTALLERS[version]["linux"]
        local_installer = Path(f"/tmp/{Path(installer_info['s3_key']).name}")

        download_from_s3(installer_info["s3_key"], local_installer)
        verify_checksum(local_installer, installer_info["sha256"])

        # Both 2025 and 2026 Linux use zip (portable/zero-install)
        # Extract and move the cinema4d folder to install path
        extract_dir = Path("/tmp/c4d_extract")
        run(["unzip", "-o", str(local_installer), "-d", str(extract_dir)])

        # Find the extracted cinema4d directory (e.g., cinema4dr2025.301/)
        extracted_dirs = [d for d in extract_dir.iterdir() if d.is_dir()]
        if extracted_dirs:
            install_dir.parent.mkdir(parents=True, exist_ok=True)
            if install_dir.exists():
                shutil.rmtree(install_dir)
            shutil.move(str(extracted_dirs[0]), str(install_dir))

        # Patch RPATHs for shared libraries (from conda recipe)
        for so_file in install_dir.glob("lib64/*.so.*"):
            run(["patchelf", "--add-rpath", "$ORIGIN/.", str(so_file)], check=False)
        for xso_file in install_dir.glob("bin/corelibs/*.xso64"):
            run(["patchelf", "--add-rpath", "$ORIGIN/../../lib64", str(xso_file)], check=False)

        shutil.rmtree(extract_dir, ignore_errors=True)
        local_installer.unlink(missing_ok=True)

        if install_dir.exists():
            print(f"SUCCESS: Cinema 4D {version} installed at {install_dir}")
            print(f"Contents: {list(install_dir.iterdir())[:20]}")
            bin_dir = install_dir / "bin"
            if bin_dir.exists():
                print(f"bin/ contents: {list(bin_dir.iterdir())[:20]}")
            # Create c4dpy symlink pointing to bin/Commandline for test compatibility
            c4dpy_link = install_dir / "c4dpy"
            commandline = install_dir / "bin" / "Commandline"
            if commandline.exists() and not c4dpy_link.exists():
                c4dpy_link.symlink_to(commandline)
                print(f"Created symlink: {c4dpy_link} -> {commandline}")
            marker.touch()
        else:
            print(f"ERROR: Cinema 4D {version} not found at {install_dir}")
            sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Setup Cinema 4D test environment")
    parser.add_argument("--versions", nargs="+", required=True, help="Cinema 4D versions to install (e.g., 2025 2026)")
    args = parser.parse_args()

    system = platform.system()
    print(f"Setting up {system} with Cinema 4D {', '.join(args.versions)}")

    for v in args.versions:
        if v not in C4D_INSTALLERS:
            print(f"ERROR: Unsupported version {v}. Supported: {list(C4D_INSTALLERS.keys())}")
            sys.exit(1)

    if system == "Windows":
        setup_windows(args.versions)
    elif system == "Linux":
        setup_linux(args.versions)
    else:
        print(f"Unsupported platform: {system}")
        sys.exit(1)

    print("Setup complete!")
