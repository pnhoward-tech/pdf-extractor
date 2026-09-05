# PyInstaller spec for a standalone Statement Extractor.
#
# Build it on the machine you intend to run it on — a frozen binary is not
# portable between operating systems:
#
#     pip install pyinstaller
#     pyinstaller desktop.spec
#
# The result is dist/statement-extractor (dist\statement-extractor.exe on
# Windows). It still needs poppler installed, and tesseract for scans; the app
# checks for both at startup and says how to install them.

from PyInstaller.utils.hooks import collect_submodules

hidden = (
    collect_submodules("uvicorn")
    + collect_submodules("statements.profiles")
    + ["anyio._backends._asyncio", "app.statements_api"]
)

analysis = Analysis(
    ["desktop.py"],
    pathex=["."],
    # The UI and the profile definitions are data, not code, so they have to be
    # carried explicitly.
    datas=[
        ("app/static", "app/static"),
        ("profiles", "profiles"),
    ],
    hiddenimports=hidden,
    hookspath=[],
    excludes=["tkinter", "matplotlib", "IPython", "pytest", "reportlab"],
    noarchive=False,
)

pyz = PYZ(analysis.pure)

exe = EXE(
    pyz,
    analysis.scripts,
    analysis.binaries,
    analysis.datas,
    [],
    name="statement-extractor",
    console=True,          # keeps the "Running at http://..." line visible
    upx=False,
    strip=False,
)
