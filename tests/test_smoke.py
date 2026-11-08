"""Exercise persistence and API logic without external network services."""
import _database
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.database import Base, SessionLocal, engine
from app import main
from app.models import Site, MaintenanceLog
from app.scanner import structure_hash

class SitePulseTest(unittest.TestCase):
    def setUp(self):
        Base.metadata.drop_all(engine)
        Base.metadata.create_all(engine)

    def test_onboarding_notes_and_cascade(self):
        result = SimpleNamespace(url='https://example.com/', hostname='example.com', http_status=200, response_ms=42, domain_expires_at=datetime.now(timezone.utc) + timedelta(days=10), ssl_expires_at=None, structure_hash='a'*32, registrar=None, error=None)
        with patch.object(main.scanner, 'scan', return_value=result), SessionLocal() as db:
            site = main.onboard(main.Onboarding(client_name='Example', url='example.com'), db)
            self.assertEqual(main.dashboard(db)['expiring_domains'], 1)
            main.add_log(site['id'], main.Note(body='Updated plugins'), db)
            self.assertEqual(main.details(site['id'], db)['logs'][0]['body'], 'Updated plugins')
            db.delete(db.get(Site, site['id']))
            db.commit()
            self.assertEqual(db.query(MaintenanceLog).count(), 0)

    def test_structure_fingerprint_tracks_nesting(self):
        self.assertNotEqual(structure_hash('<div><p></p></div>'), structure_hash('<div></div><p></p>'))

if __name__ == '__main__':
    unittest.main()
