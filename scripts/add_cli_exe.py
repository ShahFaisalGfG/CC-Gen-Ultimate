"""Add the console ccgen.exe to the app's onedir PyInstaller spec, sharing its _internal folder.

    python add_cli_exe.py SPEC --script main.py --version-file ccgen.version.txt [--name ccgen]

pyi-makespec writes the spec for CC-Gen-Ultimate.exe (scripts\\bundle.ps1 passes it the app's
options). This adds a second Analysis and EXE for the command line, built with the same data,
hooks, and hidden imports, and puts both executables in the one COLLECT, so ccgen.exe sits beside
CC-Gen-Ultimate.exe and loads the same DLLs and models from _internal. Each exe keeps its own copy
of the Python code (a few tens of MB); the libraries, which are gigabytes, are shared.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

_ANALYSIS = re.compile(r"^a = Analysis\(\n    \[(?P<script>'[^']+')\],\n(?P<rest>.*?)^\)\n", re.S | re.M)
_EXE = re.compile(r"^exe = EXE\(\n(?P<body>.*?)^\)\n", re.S | re.M)
_COLLECT = "coll = COLLECT(\n    exe,\n    a.binaries,\n    a.datas,\n"


def add_cli(spec: str, script: str, version_file: str, name: str = "ccgen") -> str:
    """The spec text with the command line's Analysis, EXE, and COLLECT entries added."""
    if "cli_exe = EXE(" in spec:
        raise ValueError("The spec already has the command line.")
    analysis = _ANALYSIS.search(spec)
    exe = _EXE.search(spec)
    if analysis is None or exe is None or _COLLECT not in spec:
        raise ValueError("The spec isn't the one pyi-makespec writes for a onedir build.")
    cli_analysis = f"cli_a = Analysis(\n    [{script!r}],\n{analysis.group('rest')})\ncli_pyz = PYZ(cli_a.pure)\n"
    body = exe.group("body")
    body = body.replace("    pyz,\n    a.scripts,\n", "    cli_pyz,\n    cli_a.scripts,\n", 1)
    body = re.sub(r"^    name='[^']*',$", f"    name={name!r},", body, count=1, flags=re.M)
    body = re.sub(r"^    console=False,$", "    console=True,", body, count=1, flags=re.M)
    body = re.sub(r"^    version='[^']*',$", "", body, flags=re.M)
    body = body.rstrip("\n") + f"\n    version={version_file!r},\n"
    for needed in ("cli_pyz,", "cli_a.scripts,", f"name={name!r},", "console=True,"):
        if needed not in body:
            raise ValueError(f"The app's EXE entry has no {needed.split('=')[0].rstrip(',')} to change.")
    cli_exe = f"cli_exe = EXE(\n{body})\n"
    collect = _COLLECT + "    cli_exe,\n    cli_a.binaries,\n    cli_a.datas,\n"
    spec = spec.replace(_COLLECT, collect, 1)
    insert_at = spec.index("coll = COLLECT(")
    return spec[:insert_at] + cli_analysis + cli_exe + spec[insert_at:]


def main(argv: list[str] | None = None) -> int:
    """Rewrite the spec file in place."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("spec", type=Path)
    parser.add_argument("--script", required=True, type=Path, help="the command line's entry script")
    parser.add_argument("--version-file", required=True, type=Path, help="ccgen.exe's version details")
    parser.add_argument("--name", default="ccgen")
    args = parser.parse_args(argv)
    try:
        text = args.spec.read_text(encoding="utf-8")
        updated = add_cli(text, args.script.resolve().as_posix(), args.version_file.resolve().as_posix(), args.name)
        args.spec.write_text(updated, encoding="utf-8")
    except (OSError, ValueError) as error:
        print(f"Couldn't add {args.name}.exe to {args.spec}: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
