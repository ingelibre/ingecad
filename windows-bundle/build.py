"""Assemble audited allowlisted app files plus relocatable CPython and dependency closure.
Run with the existing MCP venv, using local distribution RECORDs. No user state is copied.
"""
import hashlib
import importlib.metadata as metadata
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

ROOT = Path(__file__).resolve().parent
WORK = ROOT.parent
APP = Path(os.environ["LOCALAPPDATA"])/"Programs"/"IngeCAD"
STAGE = ROOT/"stage"
STAGE.mkdir(exist_ok=True)
DIST = ROOT/"dist"
DIST.mkdir(exist_ok=True)
IGNORED = {"__pycache__", ".pytest_cache", ".git", ".deps", ".libs"}


def copy_tree(source, target):
    for path in source.rglob("*"):
        rel = path.relative_to(source)
        if any(part in IGNORED for part in rel.parts) or path.suffix in {".pyc", ".pyo"}:
            continue
        if path.is_file():
            dest = target/rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, dest)


for folder in ["core", "formats", "i18n", "plugins", "render", "resources", "tools", "views", "docs"]:
    copy_tree(APP/folder, STAGE/folder)
for name in ["main.py", "LICENSE", "AUTHORS", "CHANGELOG.md", "requirements.txt"]:
    shutil.copy2(APP/name, STAGE/name)
for name in ["launch.pyw", "mcp_entry.py", "configure.py", "install_checks.py", "README-TH.txt"]:
    shutil.copy2(ROOT/name, STAGE/name)
copy_tree(WORK/"ingecad-mcp"/"plugin", STAGE/"plugins"/"ingecad_mcp")
for name in ["server.py", "bridge_client.py", "LICENSE", "README.md", "requirements-lock.txt"]:
    dest = STAGE/"mcp"/name
    dest.parent.mkdir(exist_ok=True)
    shutil.copy2(WORK/"ingecad-mcp"/name, dest)

runtime = STAGE/"runtime"
runtime.mkdir(exist_ok=True)
embed = ROOT/"downloads"/"python-3.12.10-embed-amd64.zip"
assert hashlib.sha256(embed.read_bytes()).hexdigest() == "4acbed6dd1c744b0376e3b1cf57ce906f9dc9e95e68824584c8099a63025a3c3"
with ZipFile(embed) as archive:
    archive.extractall(runtime)
(runtime/"python312._pth").write_text("python312.zip\n.\nsite-packages\n..\nimport site\n", encoding="utf-8")

app_site = APP/".venv"/"Lib"/"site-packages"
mcp_site = WORK/"ingecad-mcp"/".venv"/"Lib"/"site-packages"
available = {}
for folder in [app_site, mcp_site]:
    for d in metadata.distributions(path=[str(folder)]):
        name = canonicalize_name(d.metadata["Name"])
        if name in available and available[name][0].version != d.version:
            raise RuntimeError("Dependency version conflict: "+name)
        available[name] = (d, folder)
selected = {}
processed = set()
queue = [(name, ()) for name in ["PySide6", "ezdxf", "numpy", "Pillow", "pyproj", "mcp"]]
while queue:
    name, extras = queue.pop()
    name = canonicalize_name(name)
    context = (name, tuple(sorted(extras)))
    if context in processed:
        continue
    processed.add(context)
    dist, folder = available[name]
    selected[name] = (dist, folder)
    for raw in dist.requires or []:
        req = Requirement(raw)
        if req.marker and not any(req.marker.evaluate({"extra":extra, "python_version":"3.12", "python_full_version":"3.12.10"}) for extra in ("", *extras)):
            continue
        candidate = available[canonicalize_name(req.name)][0]
        if req.specifier and candidate.version not in req.specifier:
            raise RuntimeError("Unsatisfied requirement: "+raw)
        queue.append((req.name, tuple(req.extras)))
for name, (dist, folder) in selected.items():
    for entry in dist.files or []:
        relative = Path(str(entry))
        if relative.is_absolute() or ".." in relative.parts or "__pycache__" in relative.parts or relative.suffix == ".pyc":
            continue
        source = folder/relative
        if source.is_file():
            dest = runtime/"site-packages"/relative
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, dest)
(STAGE/"dependency-versions.txt").write_text("\n".join(sorted(d.metadata["Name"]+"=="+d.version for d,_ in selected.values()))+"\n", encoding="utf-8")

vendor = STAGE/"vendor"/"libredwg"/"bin"
vendor.mkdir(parents=True, exist_ok=True)
for name in ["dwg2dxf.exe", "dxf2dwg.exe"]:
    shutil.copy2(APP/"vendor"/"libredwg"/name, vendor/name)
source_dir = APP/"build"/"windows"/"libredwg-0.14.8597"
sources = STAGE/"sources"
sources.mkdir(exist_ok=True)
# Corresponding patched source is derived from the original source tar, replacing only
# original members from the retained working tree. No .o, machine config, or build cache.
with tarfile.open(APP/"build"/"windows"/"libredwg.tar.xz", "r:xz") as original, tarfile.open(sources/"libredwg-0.14.8597-patched.tar.xz", "w:xz") as patched:
    for member in original.getmembers():
        if not member.isfile():
            continue
        rel = Path(member.name).parts[1:]
        local = source_dir.joinpath(*rel)
        if not local.is_file():
            raise RuntimeError("Missing corresponding source: "+member.name)
        patched.add(local, arcname=member.name, recursive=False)
for name in ["utf8.manifest", "utf8.rc"]:
    shutil.copy2(APP/"build"/"windows"/name, sources/name)
shutil.copy2(ROOT/"rebuild-libredwg.sh", sources/"rebuild-libredwg.sh")
shutil.copy2(source_dir/"COPYING", STAGE/"LIBREDWG-LICENSE.txt")
shutil.copy2(ROOT/"THIRD-PARTY-NOTICES.txt", STAGE/"THIRD-PARTY-NOTICES.txt")
shutil.copy2(ROOT/"launcher.c", sources/"launcher.c")
toolchain = APP/"build"/"windows"/"w64devkit"/"bin"
with tempfile.TemporaryDirectory(prefix="ingecad-launcher-") as temp:
    temp = Path(temp)
    shutil.copy2(ROOT/"launcher.c", temp/"launcher.c")
    shutil.copy2(APP/"resources"/"icons"/"ingecad.ico", temp/"ingecad.ico")
    (temp/"launcher.rc").write_text('1 ICON "ingecad.ico"\n', encoding="utf-8")
    subprocess.run([str(toolchain/"windres.exe"), "launcher.rc", "-O", "coff", "-o", "launcher-res.o"], cwd=temp, check=True)
    subprocess.run([str(toolchain/"gcc.exe"), "-Os", "-s", "-municode", "-mwindows", "launcher.c", "launcher-res.o", "-o", "IngeCAD.exe"], cwd=temp, check=True)
    shutil.copy2(temp/"IngeCAD.exe", STAGE/"IngeCAD.exe")

manifest = {"bundle_version":"0.3.2", "ingecad":"0.6.5", "ingecad_commit":"b58499c6ca1ce9c106b69bb29e8d6ffcb1e9676c", "python":"3.12.10", "libredwg":"0.14.8597 patched", "platform":"Windows x64", "files":{}}
for p in sorted(STAGE.rglob("*")):
    if p.is_file() and p.name not in {"bundle-manifest.json", "connection.json", "install-check.json"} and "MCP-config" not in p.parts:
        manifest["files"][p.relative_to(STAGE).as_posix()] = hashlib.sha256(p.read_bytes()).hexdigest()
(STAGE/"bundle-manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
print(json.dumps({"dependencies":len(selected), "files":len(manifest["files"]), "bytes":sum(p.stat().st_size for p in STAGE.rglob('*') if p.is_file())}))
