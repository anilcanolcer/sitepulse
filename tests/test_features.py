import unittest
import _database
from unittest.mock import patch
from datetime import datetime,timezone
from app.insights import inspect_page
from app.scanner import ScanResult
from app import main
from app.database import Base,SessionLocal,engine
from app.models import Site,ScanSnapshot
from app.reports import create_report
from app.utilities import dispatch_payment_shield_webhook
import hashlib,hmac,json

HTML='''<html><head><title>Example</title><script src="https://cdn.example.org/a.js?token=secret"></script></head><body><img src="a.png"><form action="http://example.com/login"><input type="password"></form><iframe src="http://old.example.org/x"></iframe><a href="/contact">Contact</a><script src="/wp-content/plugins/sample/main.js"></script></body></html>'''

class FeatureTests(unittest.TestCase):
    def setUp(self):
        Base.metadata.drop_all(engine);Base.metadata.create_all(engine)

    def test_evidence_and_private_query_redaction(self):
        data=inspect_page(HTML,{},'https://example.com/')
        self.assertIn('password_form',[x['code'] for x in data['tasks']])
        self.assertIn('mixed',[x['code'] for x in data['tasks']])
        self.assertEqual(data['plugins'],['sample'])
        self.assertEqual(data['links']['internal'],1)
        self.assertNotIn('token',str(data['critical']))
        self.assertEqual(data['checks_total'],11)
        malformed=inspect_page('<script src="http://["></script><script src="data:text/javascript,secret"></script>',{},'https://example.com/')
        self.assertEqual(malformed['critical'],[])

    def test_daily_due_scan_and_snapshot_retention(self):
        from datetime import timedelta
        with SessionLocal() as db:
            due=Site(client_name='Due',url='https://due.example/',hostname='due.example',checked_at=datetime.now(timezone.utc)-timedelta(days=2))
            fresh=Site(client_name='Fresh',url='https://fresh.example/',hostname='fresh.example')
            db.add_all([due,fresh]);db.commit()
        result=ScanResult(url='https://due.example/',hostname='due.example',http_status=200,insights={'critical':['<script src="a.js">']})
        with patch.object(main.scanner,'scan',return_value=result) as scanner:
            main.check_due_sites()
            self.assertEqual(scanner.call_count,1)
        with SessionLocal() as db:
            site=db.query(Site).filter_by(client_name='Due').one()
            for _ in range(35):main.save_snapshot(db,site)
            db.commit()
            self.assertEqual(db.query(ScanSnapshot).filter_by(site_id=site.id).count(),30)

    def test_five_minute_probe_preserves_deep_analysis(self):
        from datetime import timedelta
        with SessionLocal() as db:
            site=Site(client_name='Probe',url='https://example.com/',hostname='example.com',insights={'score':90},availability_checked_at=datetime.now(timezone.utc)-timedelta(minutes=6))
            db.add(site);db.commit()
            original=site.checked_at
        result=ScanResult(url='https://example.com/',hostname='example.com',http_status=503,response_ms=80)
        with patch.object(main.scanner,'check_availability',return_value=result):
            main.check_availability_due()
        with SessionLocal() as db:
            site=db.query(Site).one()
            self.assertEqual(site.insights,{'score':90})
            self.assertEqual(site.checked_at.replace(tzinfo=timezone.utc),original.replace(tzinfo=timezone.utc))
            self.assertEqual(site.http_status,503)

    def test_snapshots_diff_and_cascade(self):
        with SessionLocal() as db:
            site=Site(client_name='Example',url='https://example.com/',hostname='example.com')
            db.add(site);db.flush()
            for critical in [['<script src="a.js">'],['<script src="b.js">']]:
                main.apply_scan(site,ScanResult(url=site.url,hostname=site.hostname,insights={'critical':critical}))
                main.save_snapshot(db,site);db.commit()
            data=main.timeline(site.id,db)
            self.assertEqual((data[0]['added'],data[0]['removed']),(1,1))
            self.assertEqual(len(data),2)
            db.delete(site);db.commit()
            self.assertEqual(db.query(ScanSnapshot).count(),0)

    def test_webhook_signed_exact_body_and_acknowledgement(self):
        with patch('app.utilities.requests.post') as post:
            post.return_value.status_code=200
            post.return_value.json.return_value={'state':'suspend'}
            dispatch_payment_shield_webhook('https://example.com/hook',1,'suspend','0','N/A','s'*32)
            kw=post.call_args.kwargs
            expected=hmac.new(('s'*32).encode(),kw['data'],hashlib.sha256).hexdigest()
            self.assertEqual(kw['headers']['X-SitePulse-Signature'],'sha256='+expected)
            self.assertIn('event_id',json.loads(kw['data']))
            post.return_value.json.return_value={'state':'resume'}
            with self.assertRaises(ValueError):
                dispatch_payment_shield_webhook('https://example.com/hook',1,'suspend','0','N/A','s'*32)

    def test_crawler_obeys_robots_and_never_guesses_paths(self):
        from app.crawler import crawl_site
        calls=[]
        def fetch(url):
            calls.append(url)
            if url.endswith('robots.txt'):return 200,1,'User-agent: *\nDisallow: /private',{},url
            return 200,1,'<html><a href="/private">Private</a><a href="/contact">Contact</a><a href="https://other.example/x">External</a></html>',{'Content-Type':'text/html'},url
        with patch('app.crawler.fetch_http',side_effect=fetch),patch('app.crawler.time.sleep'):
            result=crawl_site('https://example.com/')
        self.assertEqual(len(result['pages']),2)
        self.assertNotIn('https://example.com/private',calls)
        self.assertFalse(any('test.php' in x or 'other.example' in x for x in calls))

    def test_pdf_handles_turkish_and_untrusted_markup(self):
        data=create_report({'client_name':'Örnek <script>','url':'https://example.com/','checked_at':datetime.now(timezone.utc),'response_ms':0},[{'body':'Bakım <b>kaydı</b> tamamlandı.','created_at':'2026-11-08'}],'tr')
        self.assertTrue(data.startswith(b'%PDF'))

    def tearDown(self):
        engine.dispose()
