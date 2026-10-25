"""
make_notices.py - writes THIRD_PARTY_NOTICES.txt from the license files of the packages installed on this computer
(Pillow and NumPy, including the libraries bundled inside their Windows packages).
Run it again after upgrading a package, before building the EXE:   python make_notices.py
"""
from importlib import metadata
from pathlib import Path

PACKAGES = ["pillow", "numpy"]
HEADER = """THIRD-PARTY NOTICES
===================

This program (Photo Triage & Rating Tools) uses the open-source software listed below.
Each component remains under its own license, reproduced in full after this list. The program's own
license is separate (see LICENSE).

Components
----------
- Pillow {pillow} - image reading and processing - https://python-pillow.org
- NumPy {numpy} - numeric computation - https://numpy.org
- Python (the interpreter, and the Tkinter/Tcl/Tk interface toolkit) - Python Software Foundation License
  and the Tcl/Tk license - https://docs.python.org/3/license.html
- PyInstaller - used only to build the EXE; its bootloader is included in the EXE under the GPL with the
  special exception that permits distributing the resulting program under any license - https://pyinstaller.org

The text of the Python and Tcl/Tk licenses is available at the address above and ships with every Python
installation (see the LICENSE.txt file in the Python folder).
"""


def main():
    versions, parts = {}, []
    for name in PACKAGES:
        dist = metadata.distribution(name)
        versions[name] = dist.version
        files = [f for f in (dist.files or []) if "licen" in f.name.lower() or f.name.upper().startswith("COPYING")]
        files.sort(key=lambda f: (len(f.parts), str(f)))
        for f in files:
            text = Path(dist.locate_file(f)).read_text(encoding="utf-8", errors="replace").strip()
            parts.append(f"\n\n{'=' * 78}\n{name} {dist.version}: {f.as_posix()}\n{'=' * 78}\n\n{text}\n")
    out = Path(__file__).resolve().parent / "THIRD_PARTY_NOTICES.txt"
    out.write_text(HEADER.format(**versions) + "".join(parts), encoding="utf-8")
    print(f"נכתב: {out}  ({out.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
