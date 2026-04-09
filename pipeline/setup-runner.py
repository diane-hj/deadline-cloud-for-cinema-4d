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

import boto3
from botocore.config import Config


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


def download_from_s3(s3_path, local_path):
    """Download a file from S3 with expected bucket owner verification."""
    bucket = os.environ.get("INSTALLER_BUCKET")
    if not bucket:
        print("ERROR: INSTALLER_BUCKET not set")
        sys.exit(1)

    expected_bucket_owner = os.environ.get("INSTALLER_BUCKET_EXPECTED_OWNER")
    if not expected_bucket_owner:
        raise ValueError("INSTALLER_BUCKET_EXPECTED_OWNER environment variable is required")
    if not (expected_bucket_owner.isdigit() and len(expected_bucket_owner) == 12):
        raise ValueError("INSTALLER_BUCKET_EXPECTED_OWNER must be a 12-digit AWS Account ID")

    config = Config(read_timeout=300, connect_timeout=60, retries={"max_attempts": 2})
    s3 = boto3.client("s3", config=config)

    print(f"Downloading s3://{bucket}/{s3_path} to {local_path}")
    s3.download_file(
        bucket, s3_path, str(local_path), ExtraArgs={"ExpectedBucketOwner": expected_bucket_owner}
    )


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

        # TODO: pywin32 may be needed on some environments. Uncomment if c4dpy fails with COM errors.
        # c4d_site_packages = install_dir / "resource" / "modules" / "python" / "libs" / "win64" / "lib" / "site-packages"
        # c4d_python = install_dir / "resource" / "modules" / "python" / "libs" / "win64" / "python.exe"
        # if c4d_python.exists():
        #     run([str(c4d_python), "-m", "ensurepip"], check=False)
        #     if not (c4d_site_packages / "pywin32.pth").exists():
        #         print("Installing pywin32 into C4D's Python...")
        #         run([str(c4d_python), "-m", "pip", "install", "pywin32==308", "-t", str(c4d_site_packages)])
        #         dlls_dir = install_dir / "resource" / "modules" / "python" / "libs" / "win64" / "dlls"
        #         pywin32_sys = c4d_site_packages / "pywin32_system32"
        #         if pywin32_sys.exists() and dlls_dir.exists():
        #             for dll in pywin32_sys.glob("*.dll"):
        #                 shutil.copy(str(dll), str(dlls_dir))
        #                 print(f"Copied {dll.name} to {dlls_dir}")


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
    else:
        print(f"Unsupported platform: {system}")
        sys.exit(1)

    print("Setup complete!")
