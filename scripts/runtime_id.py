"""Write build.ini into a CC-Gen-Ultimate onedir bundle: its GPU edition and runtime fingerprint.

Usage: python scripts/runtime_id.py BUNDLE_DIR --edition cuda|legacy|xpu [--exe CC-Gen-Ultimate.exe]

An installed copy is two layers. The app layer is what changes in most releases: the exe and
ccgen.exe (each holds every Python module, PyInstaller's PYZ), the QML and assets in
_internal\\ccgen, the Agent Skill in _internal\\skills, the licence texts, and build.ini. The
runtime layer is everything else: PyTorch and CUDA, Qt, and the other libraries and their data in
_internal, plus ccgen_shell.dll. The fingerprint is the SHA-256 over the runtime
layer's file names, sizes, and contents. When a release's fingerprint matches an installed copy's,
the in-app updater installs the small patch installer (the app layer only,
installer/ccgenultimate_patch_installer.iss) instead of the whole edition.

Keep APP_LAYER in step with the [Files] of the patch installer.
"""

import argparse
import configparser
import hashlib
import os
import sys

BUILD_INFO = "build.ini"
EDITIONS = ("cuda", "legacy", "xpu")
# Paths relative to the bundle, lowercase, with "/" separators. A folder ends with "/".
# ccgen.exe, the command line, holds the Python modules as the app's exe does.
APP_LAYER_FILES = frozenset({BUILD_INFO, "ccgen.exe", "_internal/license", "_internal/third_party_notices.md"})
APP_LAYER_FOLDERS = ("_internal/ccgen/", "_internal/skills/")
_CHUNK = 4 * 1024 * 1024


def is_app_layer(relative: str, exe: str) -> bool:
    """True for a file the patch installer replaces; `relative` uses "/" separators."""
    name = relative.lower()
    return name == exe.lower() or name in APP_LAYER_FILES or name.startswith(APP_LAYER_FOLDERS)


def runtime_files(bundle: str, exe: str) -> list[str]:
    """The runtime layer's files, relative to the bundle with "/" separators, sorted."""
    found = []
    for folder, _dirs, files in os.walk(bundle):
        for name in files:
            relative = os.path.relpath(os.path.join(folder, name), bundle).replace(os.sep, "/")
            if not is_app_layer(relative, exe):
                found.append(relative)
    return sorted(found, key=str.lower)


def runtime_id(bundle: str, exe: str) -> str:
    """SHA-256 over each runtime file's lowercase path, size, and content hash."""
    digest = hashlib.sha256()
    for relative in runtime_files(bundle, exe):
        path = os.path.join(bundle, relative)
        content = hashlib.sha256()
        with open(path, "rb") as fh:
            while block := fh.read(_CHUNK):
                content.update(block)
        digest.update(f"{relative.lower()}\0{os.path.getsize(path)}\0{content.hexdigest()}\n".encode("utf-8"))
    return digest.hexdigest()


def write_build_info(bundle: str, edition: str, fingerprint: str) -> str:
    parser = configparser.ConfigParser()
    parser["build"] = {"edition": edition, "runtime_id": fingerprint}
    path = os.path.join(bundle, BUILD_INFO)
    with open(path, "w", encoding="utf-8", newline="\r\n") as fh:
        parser.write(fh)
    return path


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Record a bundle's GPU edition and runtime fingerprint.")
    parser.add_argument("bundle")
    parser.add_argument("--edition", required=True, choices=EDITIONS)
    parser.add_argument("--exe", default="CC-Gen-Ultimate.exe")
    args = parser.parse_args(argv)
    if not os.path.isfile(os.path.join(args.bundle, args.exe)):
        print(f"{args.exe} is not in {args.bundle}", file=sys.stderr)
        return 1
    fingerprint = runtime_id(args.bundle, args.exe)
    path = write_build_info(args.bundle, args.edition, fingerprint)
    print(f"Wrote {path}: edition {args.edition}, runtime {fingerprint}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
