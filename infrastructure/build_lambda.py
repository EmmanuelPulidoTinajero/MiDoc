"""Construye un paquete Linux/Python 3.12 limpio sin modificar backend/src."""
import os
import shutil
import subprocess
import sys
from pathlib import Path


root = Path(__file__).resolve().parent.parent
source = root / "backend" / "src"
target = root / "backend" / ".lambda-build"
requirements = root / "backend" / "requirements.txt"

if target.exists():
    shutil.rmtree(target)
target.mkdir(parents=True)
for path in source.glob("*.py"):
    shutil.copy2(path, target / path.name)
shutil.copy2(source / "schema.sql", target / "schema.sql")
subprocess.run([
    sys.executable, "-m", "pip", "install", "--platform", "manylinux2014_x86_64",
    "--implementation", "cp", "--python-version", "312", "--only-binary=:all:",
    "--upgrade", "--no-compile", "-r", str(requirements), "-t", str(target),
], check=True)
print(f"Paquete Lambda preparado en {target}")
