"""Compile NSIS from manifest-controlled payload and explicit uninstall file list."""
import json
import os
import subprocess
from pathlib import Path

root = Path(__file__).resolve().parent
stage = root/"stage"
manifest = json.loads((stage/"bundle-manifest.json").read_text(encoding="utf-8"))
names = sorted([*manifest["files"], "bundle-manifest.json"])
install, uninstall, directories = [], [], set()
for name in names:
    rel = Path(name)
    directory = str(rel.parent).replace("/", "\\")
    install += ['SetOutPath "$INSTDIR'+('\\'+directory if directory != '.' else '')+'"', 'File "stage\\'+name.replace('/', '\\')+'"']
    uninstall.append('Delete "$INSTDIR\\'+name.replace('/', '\\')+'"')
    for parent in rel.parents:
        if str(parent) != '.':
            directories.add(str(parent).replace('/', '\\'))
uninstall += ['RMDir "$INSTDIR\\'+d+'"' for d in sorted(directories, key=lambda d: d.count('\\'), reverse=True)]
(root/"payload-files.nsh").write_text('\n'.join(install)+'\n', encoding="utf-8")
(root/"payload-uninstall.nsh").write_text('\n'.join(uninstall)+'\n', encoding="utf-8")
compiler = Path(os.environ["LOCALAPPDATA"])/"Programs"/"IngeCAD"/"build"/"windows"/"w64devkit"/"bin"/"makensis.exe"
with (root/"compile.log").open('w', encoding='utf-8') as log:
    result = subprocess.run([str(compiler), '-V3', '-WX', '-INPUTCHARSET', 'UTF8', str(root/"setup.nsi")], cwd=root, stdout=log, stderr=subprocess.STDOUT)
if result.returncode:
    raise RuntimeError((root/"compile.log").read_text(encoding='utf-8',errors='replace')[-7000:])
print(root/"dist"/"IngeCAD-AI-Setup-0.6.5-0.3.2-x64.exe")
