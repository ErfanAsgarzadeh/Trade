"""Check complete HTML matrix and inline image without remote assets."""
from html.parser import HTMLParser
from pathlib import Path
import json,base64,re
ROOT=Path(__file__).parent
class Check(HTMLParser):
    def __init__(self):super().__init__();self.matrix=False;self.rows=0;self.images=0
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag=='table' and a.get('id')=='matrix':self.matrix=True
        if tag=='tr' and self.matrix:self.rows+=1
        if tag=='img':
            assert a['src'].startswith('data:image/png;base64,')
            assert base64.b64decode(a['src'].split(',',1)[1]).startswith(b'\x89PNG\r\n\x1a\n')
            self.images+=1
    def handle_endtag(self,tag):
        if tag=='table':self.matrix=False
text=(ROOT/'output/report_fa.html').read_text();p=Check();p.feed(text)
assert p.rows==433 and p.images==1
m=json.loads((ROOT/'output/matrix.json').read_text())
for row in m['matrix']:assert row['id'] in text
assert '<html lang="fa" dir="rtl">' in text
assert not re.search(r'<(?:img|script)[^>]+(?:src|href)=["\']https?://',text)
script=re.search(r'<script>(.*?)</script>',text,re.S).group(1)
(ROOT/'output/report_filter.js').write_text(script)
print('PASS: 432 matrix rows, UTF-8 RTL, self-contained image and complete identifiers')
