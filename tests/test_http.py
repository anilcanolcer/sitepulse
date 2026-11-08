import unittest
import _database
from unittest.mock import patch
from fastapi.testclient import TestClient
from sqlalchemy import text,inspect
from app import main
from app.database import engine,Base
from app.scanner import ScanResult
from app.insights import inspect_page

class HttpTests(unittest.TestCase):
    def setUp(self):
        Base.metadata.drop_all(engine);Base.metadata.create_all(engine)

    def test_upgrade_endpoints_report_and_secret_redaction(self):
        with engine.begin() as connection:
            for field in ('insights','shield_url','shield_secret','shield_state'):
                connection.execute(text(f'ALTER TABLE sites DROP COLUMN {field}'))
        result=ScanResult(url='https://example.com/',hostname='example.com',http_status=200,insights=inspect_page('<html lang="tr"><title>Örnek</title></html>',{},'https://example.com/'))
        with patch.object(main.scanner,'scan',return_value=result), TestClient(main.app) as client:
            self.assertEqual(client.get('/assets/sitepulse-mark.svg').status_code,200)
            self.assertIn('shield_secret',{c['name'] for c in inspect(engine).get_columns('sites')})
            self.assertEqual(client.get('/api/dashboard').status_code,200)
            response=client.post('/api/sites/onboarding',json={'client_name':'Örnek','url':'example.com'})
            self.assertEqual(response.status_code,201)
            site=response.json();sid=site['id']
            self.assertNotIn('shield_secret',site)
            self.assertEqual(client.post(f'/api/sites/{sid}/logs',json={'body':'Güncelleme kaydı'}).status_code,201)
            self.assertEqual(len(client.get(f'/api/sites/{sid}').json()['logs']),1)
            self.assertEqual(len(client.get(f'/api/sites/{sid}/timeline').json()),1)
            self.assertTrue(client.get(f'/api/sites/{sid}/report.pdf?lang=tr').content.startswith(b'%PDF'))
            self.assertEqual(client.post(f'/api/sites/{sid}/shield',json={'action':'suspend'}).status_code,422)
            self.assertEqual(client.post(f'/api/sites/{sid}/shield/config',json={'url':'https://localhost/hook','secret':'s'*32}).status_code,422)
            with patch.object(main,'normalize_target',return_value=('https://example.com/wp-json/sitepulse/v1/shield','example.com')):
                self.assertEqual(client.post(f'/api/sites/{sid}/shield/config',json={'url':'https://example.com/wp-json/sitepulse/v1/shield','secret':'s'*32}).status_code,200)
            self.assertNotIn('s'*32,client.get(f'/api/sites/{sid}').text)
            with patch.object(main,'normalize_target'),patch('app.utilities.dispatch_payment_shield_webhook'):
                self.assertEqual(client.post(f'/api/sites/{sid}/shield',json={'action':'resume'}).status_code,200)
            self.assertEqual(client.get('/api/sites/9999').status_code,404)
            self.assertEqual(client.post(f'/api/sites/{sid}/logs',json={'body':'   '}).status_code,422)
