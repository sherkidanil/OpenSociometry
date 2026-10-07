"""Build and verify a portable platform archive from the public source tree."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
import urllib.parse
import urllib.request
import zipfile


ROOT = Path(__file__).resolve().parents[1]
VERSION = "v0.1.0"


def build(slug):
    command = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir",
               "--name", "OpenSociometry", "--add-data", "static" + os.pathsep + "static",
               "--hidden-import", "vendor.xlrd", "app.py"]
    subprocess.run(command, cwd=ROOT, check=True)
    bundle = ROOT / "dist" / "OpenSociometry"
    executable = bundle / ("OpenSociometry.exe" if sys.platform == "win32" else "OpenSociometry")
    if not executable.is_file():
        raise RuntimeError("Bundled executable is missing")
    with tempfile.TemporaryDirectory() as temp:
        env = os.environ.copy()
        env["SOCIOMETRY_DB"] = str(Path(temp) / "smoke.db")
        env["SOCIOMETRY_PORT"] = "9879"
        proc = subprocess.Popen([str(executable), "--no-browser"], env=env,
                                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        try:
            for _ in range(100):
                try:
                    with urllib.request.urlopen("http://127.0.0.1:9879/api/studies", timeout=1) as response:
                        if json.load(response) == []:
                            break
                except Exception:
                    time.sleep(0.2)
            else:
                raise RuntimeError("Bundled application did not start")
            if not Path(env["SOCIOMETRY_DB"]).is_file():
                raise RuntimeError("Bundled application did not create its local database")
        finally:
            proc.terminate()
            proc.wait(timeout=10)
    staging = ROOT / "release-stage" / "OpenSociometry-0.1.0"
    staging.mkdir(parents=True, exist_ok=True)
    shutil.copytree(bundle, staging / "OpenSociometry", dirs_exist_ok=True)
    shutil.copy2(ROOT / "README.md", staging / "README.md")
    launcher = "start.bat" if sys.platform == "win32" else "start.command"
    shutil.copy2(ROOT / launcher, staging / launcher)
    output = ROOT / f"OpenSociometry-{VERSION}-{slug}.zip"
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(staging.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(staging.parent))
    print("Verified bundle:", output.name, output.stat().st_size, "bytes")
    return output


def upload(asset):
    token = os.environ["GITHUB_TOKEN"]
    repository = os.environ["GITHUB_REPOSITORY"]
    headers = {"Authorization": "Bearer " + token, "Accept": "application/vnd.github+json",
               "User-Agent": "OpenSociometry-release"}
    endpoint = f"https://api.github.com/repos/{repository}/releases/tags/{VERSION}"
    with urllib.request.urlopen(urllib.request.Request(endpoint, headers=headers)) as response:
        release = json.load(response)
    if any(item["name"] == asset.name for item in release["assets"]):
        print("Already uploaded:", asset.name)
        return
    upload_url = release["upload_url"].split("{", 1)[0]
    url = upload_url + "?" + urllib.parse.urlencode({"name": asset.name})
    request = urllib.request.Request(url, data=asset.read_bytes(), method="POST",
                                     headers={**headers, "Content-Type": "application/zip"})
    with urllib.request.urlopen(request, timeout=300) as response:
        result = json.load(response)
    print("Uploaded:", result["browser_download_url"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--slug", required=True)
    args = parser.parse_args()
    try:
        upload(build(args.slug))
    except Exception:
        details = traceback.format_exc().replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
        print("::error::" + details)
        raise
