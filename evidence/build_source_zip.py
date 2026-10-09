"""Build a clean source/evidence ZIP without environments, secrets, or caches."""

import os
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "dist" / "EPD-source.zip"
EXCLUDED_DIRS = {".git", ".venv", "venv", "__pycache__", "staticfiles", "dist"}
EXCLUDED_FILES = {".env", "db.sqlite3"}


def include_file(path):
    if path.name in EXCLUDED_FILES or path.suffix == ".pyc" or path.suffix == ".sqlite3":
        return False
    if path.name.startswith(".env.") and path.name != ".env.example":
        return False
    if any(part.endswith("-profile") or part == "chrome-profile" for part in path.parts):
        return False
    return path.is_file()


def build():
    OUTPUT.parent.mkdir(exist_ok=True)
    with ZipFile(OUTPUT, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
        for directory, child_dirs, filenames in os.walk(ROOT):
            child_dirs[:] = [name for name in child_dirs if name not in EXCLUDED_DIRS]
            for filename in filenames:
                path = Path(directory) / filename
                if include_file(path):
                    archive.write(path, path.relative_to(ROOT).as_posix())

    with ZipFile(OUTPUT) as archive:
        names = archive.namelist()
        forbidden = [name for name in names if ".env" == Path(name).name or "db.sqlite3" in name or "/venv/" in f"/{name}"]
        if forbidden:
            raise RuntimeError(f"Unsafe files found in source ZIP: {forbidden}")
    print(f"Created {OUTPUT} with {len(names)} files ({OUTPUT.stat().st_size} bytes)")


if __name__ == "__main__":
    build()
