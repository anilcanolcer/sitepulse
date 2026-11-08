# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
import ssl
from PyInstaller.utils.hooks import collect_all
root = Path(SPECPATH)
data, binaries, hidden = collect_all('whois')
runtime_ca = Path(ssl.__file__).with_name('codex-rejected-cas.pem')
if runtime_ca.exists():
    data.append((str(runtime_ca), '.'))
hidden += ['uvicorn.logging', 'uvicorn.loops.auto', 'uvicorn.protocols.http.auto', 'uvicorn.protocols.websockets.auto', 'uvicorn.lifespan.on', 'sqlalchemy.dialects.sqlite', 'webview.platforms.edgechromium']
a = Analysis([str(root / 'desktop.py')], pathex=[str(root)], binaries=binaries, datas=data + [(str(root / 'frontend'), 'frontend')], hiddenimports=hidden, hookspath=[], hooksconfig={}, runtime_hooks=[], excludes=[], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name='SitePulse', debug=False, strip=False, upx=False, console=False)
