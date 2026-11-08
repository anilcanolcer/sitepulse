"""Windows desktop launcher: local SQLite, loopback API, and a native window."""
import os
import socket
import sys
import threading
import time
import traceback
import tempfile
from pathlib import Path

test_data = tempfile.TemporaryDirectory() if '--self-test' in sys.argv else None
data_dir = Path(test_data.name) if test_data else Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'SitePulse'
data_dir.mkdir(parents=True, exist_ok=True)
os.environ['DATABASE_URL'] = 'sqlite:///' + (data_dir / 'sitepulse.db').as_posix()
os.environ['SITEPULSE_DESKTOP'] = '1'

try:
    import uvicorn
    import webview
    from app.main import app
except Exception:
    (data_dir / 'startup-error.log').write_text(traceback.format_exc(), encoding='utf-8')
    raise

def main():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(('127.0.0.1', 0))
    sock.listen(128)
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=port, log_level='warning'))
    thread = threading.Thread(target=server.run, kwargs={'sockets': [sock]}, daemon=True)
    thread.start()
    for _ in range(200):
        if server.started:
            break
        if not thread.is_alive():
            raise RuntimeError('The local SitePulse server could not start.')
        time.sleep(0.05)
    else:
        raise RuntimeError('The local SitePulse server timed out during startup.')
    webview.create_window('SitePulse', f'http://127.0.0.1:{port}/', width=1280, height=800, min_size=(800, 600))
    try:
        webview.start()
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        sock.close()

if __name__ == '__main__':
    if test_data:
        from app.database import Base, engine
        Base.metadata.create_all(bind=engine)
        engine.dispose()
        test_data.cleanup()
    else:
        main()
