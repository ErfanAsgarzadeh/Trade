"""Check self-contained HTML, all matrix/trade rows and exported filter script."""
from pathlib import Path
from html.parser import HTMLParser
import json,re,base64
ROOT=Path(__file__).parent
class Check(HTMLParser):
    def __init__(self):super().__init__();self.table=None;self.rows={};self.images=0
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag=='table':self.table=a.get('id')
        if tag=='tr' and self.table:self.rows[self.table]=self.rows.get(self.table,0)+1
        if tag=='img':
            assert a['src'].startswith('data:image/png;base64,')
            assert base64.b64decode(a['src'].split(',',1)[1]).startswith(b'\x89PNG\r\n\x1a\n');self.images+=1
    def handle_endtag(self,tag):
        if tag=='table':self.table=None
text=(ROOT/'output/report_fa.html').read_text();parser=Check();parser.feed(text)
m=json.loads((ROOT/'output/matrix.json').read_text())
assert parser.rows['matrix']==m['cases']+1 and parser.rows['trades']==m['winner']['full']['trades']+1
assert parser.images==1 and '<html lang="fa" dir="rtl">' in text
for c in m['matrix']:assert c['id'] in text
assert not re.search(r'<(?:img|script)[^>]+src=["\']https?://',text)
(ROOT/'output/report_filter.js').write_text(re.search(r'<script>(.*?)</script>',text,re.S).group(1))
print('PASS: complete RTL report,',m['cases'],'matrix rows,',m['winner']['full']['trades'],'trade rows and inline PNG')
