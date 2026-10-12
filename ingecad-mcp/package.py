"""Create a source distribution without environments, IPC data or tokens."""
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

root = Path(__file__).resolve().parent
files = [root/name for name in ["server.py", "bridge_client.py", "install.py", "package.py", "requirements.txt", "requirements-lock.txt", "README.md", "LICENSE"]]
files += [root/"generate_catalog.py"]
files += list((root/"plugin").glob("*.py")) + list((root/"plugin").glob("*.json")) + list((root/"tests").glob("*.py"))
output = root/"ingecad-ai-mcp-0.3.2.zip"
with ZipFile(output, "w", ZIP_DEFLATED) as archive:
    for path in files:
        archive.write(path, str(Path("ingecad-mcp")/path.relative_to(root)))
print(output)
