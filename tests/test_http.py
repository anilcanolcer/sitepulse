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
            for field in ('insights','shield_url','shield_secret','shield_state','availability_checked_at','hosting_expires_at','monthly_fee','currency'):
                connection.execute(text(f'ALTER TABLE sites DROP COLUMN {field}'))
            for field in ('kind','status','completed_at'):
                connection.execute(text(f'ALTER TABLE maintenance_logs DROP COLUMN {field}'))
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

    def test_task_assignment_completion_and_care_fields(self):
        from datetime import date,timedelta
        result=ScanResult(url='https://example.com/',hostname='example.com',http_status=200)
        with patch.object(main.scanner,'scan',return_value=result),TestClient(main.app) as client:
            response=client.post('/api/sites/onboarding',json={'client_name':'Example','url':'example.com','hosting_expires_on':str(date.today()+timedelta(days=10)),'monthly_fee':'1500.50','currency':'TRY'})
            self.assertEqual(response.status_code,201)
            sid=response.json()['id']
            self.assertEqual(float(response.json()['monthly_fee']),1500.50)
            self.assertEqual(client.get('/api/dashboard').json()['expiring_hosting'],1)
            note=client.post(f'/api/sites/{sid}/logs',json={'body':'Observed a missing header','kind':'task'}).json()
            duplicate=client.post(f'/api/sites/{sid}/logs',json={'body':'Observed a missing header','kind':'task'}).json()
            self.assertEqual(note['id'],duplicate['id'])
            self.assertEqual(note['status'],'open')
            completed=client.patch(f'/api/sites/{sid}/logs/{note["id"]}',json={'status':'done'})
            self.assertEqual(completed.status_code,200)
            self.assertIsNotNone(completed.json()['completed_at'])
            self.assertEqual(client.patch(f'/api/sites/9999/logs/{note["id"]}',json={'status':'done'}).status_code,404)
            reopened=client.patch(f'/api/sites/{sid}/logs/{note["id"]}',json={'status':'open'}).json()
            self.assertIsNone(reopened['completed_at'])
            self.assertEqual(client.patch(f'/api/sites/{sid}/care',json={'monthly_fee':'-1'}).status_code,422)
            updated=client.patch(f'/api/sites/{sid}/care',json={'hosting_expires_on':None,'monthly_fee':'25','currency':'EUR'})
            self.assertEqual(updated.status_code,200)
            self.assertEqual(updated.json()['currency'],'EUR')
            self.assertIsNone(updated.json()['hosting_expires_at'])

    def test_desktop_preferences_survive_origin_change(self):
        with patch.dict('os.environ',{'SITEPULSE_DESKTOP':'1'}):
            with TestClient(main.app,base_url='http://127.0.0.1:49100') as client:
                self.assertTrue(client.get('/api/preferences').json()['enabled'])
                self.assertEqual(client.patch('/api/preferences',json={'theme':'dark','language':'tr'}).status_code,200)
                self.assertEqual(client.patch('/api/preferences',json={'theme':'blue','language':'tr'}).status_code,422)
            with TestClient(main.app,base_url='http://127.0.0.1:49200') as reopened:
                self.assertEqual(reopened.get('/api/preferences').json()['theme'],'dark')
                self.assertEqual(reopened.get('/api/preferences').json()['language'],'tr')
