"""Build self-contained desktop DMGs and a Windows portable archive."""
import argparse
import io
import json
import os
from pathlib import Path
import platform
import plistlib
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
VERSION = "v0.2.0"


def smoke(executable):
    """Exercise the shipped interpreter, Excel import, chart and durable database."""
    with tempfile.TemporaryDirectory() as temp:
        database = Path(temp) / "smoke.db"
        ready = Path(temp) / "ready.json"
        env = dict(os.environ, SOCIOMETRY_DB=str(database), SOCIOMETRY_PORT="0",
                   SOCIOMETRY_READY_FILE=str(ready), SOCIOMETRY_PARENT_PID=str(os.getpid()))
        if sys.platform == "darwin":
            env["PATH"] = "/usr/bin:/bin"
        study_id = None
        for launch in range(2):
            if ready.exists():
                ready.unlink()
            proc = subprocess.Popen([str(executable), "--no-browser"], env=env,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            try:
                for _ in range(300):
                    if ready.exists():
                        break
                    if proc.poll() is not None:
                        raise RuntimeError("Bundled server exited: " + proc.stderr.read().decode(errors="replace"))
                    time.sleep(0.1)
                else:
                    raise RuntimeError("Bundled server did not announce its URL")
                url = json.loads(ready.read_text())["url"]
                with urllib.request.urlopen(url + "api/studies", timeout=10) as response:
                    studies = json.load(response)
                if launch:
                    if [study["id"] for study in studies] != [study_id]:
                        raise RuntimeError("Bundled database did not survive restart")
                    continue
                if studies or not database.is_file():
                    raise RuntimeError("Bundle must start with an empty, writable local database")
                with urllib.request.urlopen(url + "vendor/plotly.min.js", timeout=10) as response:
                    if len(response.read()) < 1000000:
                        raise RuntimeError("Bundled offline Plotly asset is missing")
                with urllib.request.urlopen(url + "templates/choices.xlsx", timeout=10) as response:
                    workbook = response.read()
                boundary = "OpenSociometryBundleSmoke"
                payload = ("--%s\r\nContent-Disposition: form-data; name=\"study\"\r\n\r\n" % boundary).encode()
                payload += json.dumps({"name": "Synthetic bundle verification"}).encode() + b"\r\n"
                payload += ("--%s\r\nContent-Disposition: form-data; name=\"file\"; filename=\"choices.xlsx\"\r\n"
                            "Content-Type: application/vnd.openxmlformats-officedocument.spreadsheetml.sheet\r\n\r\n" % boundary).encode()
                payload += workbook + ("\r\n--%s--\r\n" % boundary).encode()
                request = urllib.request.Request(url + "api/studies/import", data=payload,
                    headers={"Content-Type": "multipart/form-data; boundary=" + boundary}, method="POST")
                with urllib.request.urlopen(request, timeout=10) as response:
                    study_id = json.load(response)["id"]
                with urllib.request.urlopen(url + "api/studies/%d" % study_id, timeout=10) as response:
                    study = json.load(response)
                if not study["members"]:
                    raise RuntimeError("Bundled Excel import did not import participants")
                criterion_id = study["criteria"][0]["id"]
                with urllib.request.urlopen(url + "api/criteria/%d/status-chart.png" % criterion_id, timeout=45) as response:
                    raw = response.read()
                    if response.headers.get_content_type() != "image/png" or not raw.startswith(b"\x89PNG"):
                        raise RuntimeError("Bundled Matplotlib chart failed")
                from PIL import Image
                with Image.open(io.BytesIO(raw)) as image:
                    if min(image.info.get("dpi", (0, 0))) < 299:
                        raise RuntimeError("Bundled chart has no 300 DPI metadata")
            finally:
                if proc.poll() is None:
                    proc.terminate()
                proc.communicate(timeout=10)
    print("Verified packaged runtime: offline assets, Excel, 300 DPI, database restart")


def app_icon(destination):
    # Render the existing network logo at Dock resolution without shipping extra tools.
    from PIL import Image, ImageDraw
    image = Image.new("RGBA", (2048, 2048))
    draw = ImageDraw.Draw(image)
    scale, offset = 56, 128
    point = lambda x, y: (offset + x * scale, offset + y * scale)
    green, ink = "#b1ec52", "#15181e"
    draw.rounded_rectangle((128, 128, 1920, 1920), radius=504, fill=green)
    for start, end in [((10, 11), (22, 11)), ((10, 11), (16, 22)), ((22, 11), (16, 22))]:
        draw.line([point(*start), point(*end)], fill=ink, width=112)
    for x, y in [(10, 11), (22, 11), (16, 22)]:
        cx, cy = point(x, y)
        radius = 202
        draw.ellipse((cx-radius, cy-radius, cx+radius, cy+radius), fill=ink)
    cx, cy = point(16, 22)
    radius = 79
    draw.ellipse((cx-radius, cy-radius, cx+radius, cy+radius), fill=green)
    image.resize((1024, 1024), Image.Resampling.LANCZOS).save(destination, format="ICNS")


def macos_dmg(bundle, slug):
    staging = ROOT / "release-stage" / slug
    if staging.exists():
        shutil.rmtree(staging)
    application = staging / "OpenSociometry.app"
    contents = application / "Contents"
    resources = contents / "Resources"
    executable = contents / "MacOS" / "OpenSociometry"
    executable.parent.mkdir(parents=True)
    resources.mkdir()
    shutil.copytree(bundle, resources / "server", symlinks=True)
    architecture = "arm64" if slug == "macos-arm64" else "x86_64"
    subprocess.run(["xcrun", "swiftc", "-O", "-target", architecture + "-apple-macos14.0",
                    str(ROOT / "macos" / "OpenSociometry.swift"), "-o", str(executable),
                    "-framework", "AppKit", "-framework", "WebKit"], check=True)
    app_icon(resources / "OpenSociometry.icns")
    info = {"CFBundleName": "OpenSociometry", "CFBundleDisplayName": "OpenSociometry",
            "CFBundleExecutable": "OpenSociometry", "CFBundleIdentifier": "net.opensociometry.desktop",
            "CFBundlePackageType": "APPL", "CFBundleShortVersionString": VERSION.lstrip("v"),
            "CFBundleVersion": "2", "CFBundleIconFile": "OpenSociometry.icns",
            "LSMinimumSystemVersion": "14.0", "NSHighResolutionCapable": True,
            "NSPrincipalClass": "NSApplication", "NSAppTransportSecurity": {"NSAllowsLocalNetworking": True}}
    with (contents / "Info.plist").open("wb") as file:
        plistlib.dump(info, file)
    subprocess.run(["codesign", "--force", "--deep", "--sign", "-", str(application)], check=True)
    subprocess.run(["codesign", "--verify", "--deep", "--strict", str(application)], check=True)
    (staging / "Applications").symlink_to("/Applications")
    (staging / "Установка.txt").write_text(
        "Перетащите OpenSociometry.app в Applications и откройте приложение.\n"
        "Python устанавливать не нужно. Требуется macOS 14 или новее.\n\n"
        "Этот выпуск пока не подписан Developer ID и не нотариализован Apple.\n"
        "Если macOS заблокировала открытие, перейдите в Системные настройки →\n"
        "Конфиденциальность и безопасность и разрешите открытие OpenSociometry.\n\n"
        "Данные: ~/Library/Application Support/OpenSociometry/sociometry.db\n"
        "Замена приложения при обновлении сохраняет эту базу.\n"
        "В меню OpenSociometry есть пункт «Открыть папку данных».\n"
        "Из предыдущих версий перенесите социометрии через JSON: скачать резервную\n"
        "копию в старой версии, затем восстановить на главной странице новой.\n", encoding="utf-8")
    output = ROOT / f"OpenSociometry-{VERSION}-{slug}.dmg"
    subprocess.run(["hdiutil", "create", "-volname", "OpenSociometry " + VERSION.lstrip("v"),
                    "-srcfolder", str(staging), "-ov", "-format", "UDZO", "-fs", "HFS+", str(output)], check=True)
    subprocess.run(["hdiutil", "verify", str(output)], check=True)
    return output


def windows_zip(bundle, slug):
    staging = ROOT / "release-stage" / ("OpenSociometry-" + VERSION.lstrip("v"))
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    shutil.copytree(bundle, staging / "OpenSociometry")
    shutil.copy2(ROOT / "README.md", staging / "README.md")
    shutil.copy2(ROOT / "start.bat", staging / "start.bat")
    output = ROOT / f"OpenSociometry-{VERSION}-{slug}.zip"
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(staging.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(staging.parent))
    return output


def build(slug):
    expected = "windows-x64" if sys.platform == "win32" else "macos-arm64" if platform.machine() == "arm64" else "macos-intel"
    if slug != expected:
        raise RuntimeError("Build on the target operating system and architecture: " + expected)
    command = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir",
               "--name", "OpenSociometry", "--add-data", "static" + os.pathsep + "static",
               "--hidden-import", "vendor.xlrd", "app.py"]
    subprocess.run(command, cwd=ROOT, check=True)
    bundle = ROOT / "dist" / "OpenSociometry"
    executable = bundle / ("OpenSociometry.exe" if sys.platform == "win32" else "OpenSociometry")
    smoke(executable)
    output = macos_dmg(bundle, slug) if sys.platform == "darwin" else windows_zip(bundle, slug)
    print("Verified bundle:", output.name, output.stat().st_size, "bytes")
    return output


def upload(asset):
    token = os.environ["GITHUB_TOKEN"]
    repository = os.environ["GITHUB_REPOSITORY"]
    headers = {"Authorization": "Bearer " + token, "Accept": "application/vnd.github+json",
               "User-Agent": "OpenSociometry-release"}
    # The tag endpoint exposes published releases; the authenticated list includes drafts.
    endpoint = f"https://api.github.com/repos/{repository}/releases?per_page=100"
    with urllib.request.urlopen(urllib.request.Request(endpoint, headers=headers)) as response:
        release = next((item for item in json.load(response) if item["tag_name"] == VERSION), None)
    if release is None:
        raise RuntimeError("Create the release draft before uploading packages: " + VERSION)
    existing = next((item for item in release["assets"] if item["name"] == asset.name), None)
    if existing:
        request = urllib.request.Request(existing["url"], method="DELETE", headers=headers)
        with urllib.request.urlopen(request) as response:
            if response.status != 204:
                raise RuntimeError("Unable to replace an earlier release asset")
    upload_url = release["upload_url"].split("{", 1)[0]
    url = upload_url + "?" + urllib.parse.urlencode({"name": asset.name})
    content_type = "application/x-apple-diskimage" if asset.suffix == ".dmg" else "application/zip"
    request = urllib.request.Request(url, data=asset.read_bytes(), method="POST",
                                     headers={**headers, "Content-Type": content_type})
    with urllib.request.urlopen(request, timeout=300) as response:
        result = json.load(response)
    print("Uploaded:", result["browser_download_url"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--slug", required=True)
    parser.add_argument("--build-only", action="store_true", help="Verify locally without uploading")
    args = parser.parse_args()
    try:
        asset = build(args.slug)
        if not args.build_only:
            upload(asset)
    except Exception:
        details = traceback.format_exc().replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
        print("::error::" + details)
        raise
