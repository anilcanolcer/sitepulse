import atexit
import os
import tempfile
from pathlib import Path
temporary = tempfile.TemporaryDirectory()
os.environ['DATABASE_URL'] = 'sqlite:///' + (Path(temporary.name)/'test.db').as_posix()
def cleanup():
    from app.database import engine
    engine.dispose()
    temporary.cleanup()
atexit.register(cleanup)
