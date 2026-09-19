# PyInstaller spec. One-folder, not one-file: a one-file build unpacks ~150 MB
# to a temp directory on every launch, which reads as a program that takes
# fifteen seconds to open.
import sys
from pathlib import Path

ROOT = Path(SPECPATH).parent

# Qt is large. Excluding what we never touch is the difference between a
# download people tolerate and one they do not.
EXCLUDES = [
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
    "PySide6.QtQuick", "PySide6.QtQuick3D", "PySide6.QtQml", "PySide6.Qt3DCore",
    "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets", "PySide6.QtCharts",
    "PySide6.QtDataVisualization", "PySide6.QtBluetooth", "PySide6.QtNfc",
    "PySide6.QtPositioning", "PySide6.QtWebSockets", "PySide6.QtWebChannel",
    "PySide6.QtPdf", "PySide6.QtPdfWidgets", "PySide6.QtDesigner", "PySide6.QtHelp",
    "PySide6.QtTest", "PySide6.QtSql", "matplotlib", "scipy", "pandas", "tkinter",
    "IPython", "PIL",
]

a = Analysis(
    [str(ROOT / "espec_burnin" / "__main__.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[(str(ROOT / "espec_burnin" / "resources"), "espec_burnin/resources")],
    # certifi is imported inside a function so the fallback only costs
    # anything when it is needed. Name it here so the frozen build
    # cannot end up without the CA bundle the fallback depends on.
    hiddenimports=["espec_burnin", "certifi"],
    excludes=EXCLUDES,
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="EspecBurnIn",
    console=False,
    icon=str(ROOT / "packaging" / "windows" / "espec.ico") if sys.platform == "win32" else None,
)
COLLECT(exe, a.binaries, a.datas, name="EspecBurnIn")
