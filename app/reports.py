"""Client report built from measured observations and attributed maintenance notes."""
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape
from datetime import datetime, timezone
import reportlab
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

TEXT = {
 'en': {'report':'Website care report','scope':'Evidence from the latest page response. This report is not a complete security audit. Recorded work is supplied by the maintainer and has not been independently verified.','overview':'Latest observations','domain':'Domain renewal','ssl':'SSL certificate expiry','status':'HTTP status','time':'Response time','unknown':'Unavailable','plan':'Suggested maintenance','notes':'Recorded maintenance work','none':'No maintenance notes recorded.','clear':'No findings from the implemented page checks.','score':'Page checklist','scoreHint':'Passed checks, equally weighted. This is not a security guarantee.','evidence':'Evidence','checked':'Last checked','tasks':{'mixed':'Review page resources that use insecure connections.','password_form':'Move the password form destination to an encrypted connection.','noindex':'Confirm whether exclusion from search engines is intentional.','headers':'Review browser protection settings with the maintainer.','title':'Add a clear page title.','description':'Add a concise page description.','alt':'Review image alternatives for accessibility.','language':'Specify the document language.','form_destination':'Verify the approved service receiving form submissions.'}},
 'tr': {'report':'Web sitesi bakım raporu','scope':'Son sayfa yanıtından elde edilen gözlemler. Bu rapor kapsamlı bir güvenlik denetimi değildir. Bakım kayıtları bakım sorumlusu tarafından girilmiştir; bağımsız olarak doğrulanmamıştır.','overview':'Son gözlemler','domain':'Alan adı yenileme','ssl':'SSL sertifikası bitişi','status':'HTTP durumu','time':'Yanıt süresi','unknown':'Bilgi yok','plan':'Önerilen bakım işleri','notes':'Kaydedilmiş bakım çalışmaları','none':'Henüz bakım notu kaydedilmedi.','clear':'Uygulanan sayfa kontrollerinde bulgu yok.','score':'Sayfa kontrol listesi','scoreHint':'Eşit ağırlıklı, geçen kontrollerin oranıdır. Güvenlik garantisi değildir.','evidence':'Kanıt','checked':'Son kontrol','tasks':{'mixed':'Güvensiz bağlantı kullanan sayfa kaynaklarını inceleyin.','password_form':'Parola formunu şifreli bağlantı üzerinden gönderin.','noindex':'Arama motorlarından gizleme tercihinin bilinçli olduğunu doğrulayın.','headers':'Tarayıcı koruma ayarlarını bakım sorumlusuyla değerlendirin.','title':'Açıklayıcı bir sayfa başlığı ekleyin.','description':'Kısa bir sayfa açıklaması ekleyin.','alt':'Erişilebilirlik için görsellerin alternatif metinlerini inceleyin.','language':'Belge dilini belirtin.','form_destination':'Form verilerini alan servisin onaylı olduğunu doğrulayın.'}}
}

def create_report(site, logs, language='tr') -> bytes:
    t=TEXT['tr' if language=='tr' else 'en']
    font_dir=Path(reportlab.__file__).parent/'fonts'
    if 'Pulse' not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont('Pulse',str(font_dir/'Vera.ttf')))
        pdfmetrics.registerFont(TTFont('PulseBold',str(font_dir/'VeraBd.ttf')))
    styles=getSampleStyleSheet()
    styles.add(ParagraphStyle('PulseBody',fontName='Pulse',fontSize=9,leading=14,textColor=colors.HexColor('#344841'),spaceAfter=8,wordWrap='CJK'))
    styles.add(ParagraphStyle('PulseTitle',fontName='PulseBold',fontSize=25,leading=31,textColor=colors.HexColor('#193c34'),spaceAfter=12))
    styles.add(ParagraphStyle('PulseHeading',fontName='PulseBold',fontSize=13,leading=18,textColor=colors.HexColor('#193c34'),spaceBefore=18,spaceAfter=10))
    def p(value,style='PulseBody'):return Paragraph(escape(str(value)),styles[style])
    def date(value):return str(value)[:10] if value else t['unknown']
    buffer=BytesIO()
    doc=SimpleDocTemplate(buffer,pagesize=(595,842),rightMargin=45,leftMargin=45,topMargin=48,bottomMargin=50,title='SitePulse - '+str(site['client_name']))
    story=[p('SitePulse.','PulseTitle'),p(t['report'],'PulseHeading'),p(site['client_name'],'PulseTitle'),p(site['url']),p(t['checked']+': '+str(site.get('checked_at') or t['unknown'])),Spacer(1,8),p(t['scope'])]
    story.append(p(t['overview'],'PulseHeading'))
    rows=[[p(t['domain']),p(date(site.get('domain_expires_at')))],[p(t['ssl']),p(date(site.get('ssl_expires_at')))],[p(t['status']),p(site.get('http_status') or t['unknown'])],[p(t['time']),p(str(site['response_ms'])+' ms' if site.get('response_ms') is not None else t['unknown'])]]
    table=Table(rows,colWidths=[230,275]);table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,-1),colors.HexColor('#f1f5ee')),('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),12),('RIGHTPADDING',(0,0),(-1,-1),12),('TOPPADDING',(0,0),(-1,-1),9),('BOTTOMPADDING',(0,0),(-1,-1),7)]));story.append(table)
    insight=site.get('insights') or {}
    if 'score' in insight:
        story.extend([p(f"{t['score']}: {insight['score']}/100 ({insight['checks_passed']}/{insight['checks_total']})",'PulseHeading'),p(t['scoreHint'])])
    story.append(p(t['plan'],'PulseHeading'))
    for task in insight.get('tasks',[]):
        story.extend([p(t['tasks'].get(task['code'],task['code'])),p(t['evidence']+': '+task['evidence'])])
    if not insight.get('tasks'):story.append(p(t['clear'] if insight else t['unknown']))
    story.append(p(t['notes'],'PulseHeading'))
    for log in logs:
        story.extend([p(date(log['created_at']),'PulseHeading'),p(log['body'])])
    if not logs:story.append(p(t['none']))
    def footer(canvas,doc):
        canvas.setFont('Pulse',8);canvas.setFillColor(colors.HexColor('#568759'));canvas.drawString(45,28,'SitePulse | '+datetime.now(timezone.utc).strftime('%Y-%m-%d UTC'));canvas.drawRightString(550,28,str(doc.page))
    doc.build(story,onFirstPage=footer,onLaterPages=footer)
    return buffer.getvalue()
