"""Extract visible methods from the primary paper without its embedded figures."""
from html.parser import HTMLParser
from pathlib import Path
import re
import urllib.request

ROOT=Path(r'D:\LocalCodex\research')
ROOT.mkdir(exist_ok=True)
class Text(HTMLParser):
    def __init__(self):
        super().__init__();self.skip=0;self.parts=[]
    def handle_starttag(self,tag,attrs):
        if tag in ('script','style'):self.skip+=1
        if tag in ('p','div','h1','h2','h3','h4','li','figcaption','tr'):self.parts.append('\n')
    def handle_endtag(self,tag):
        if tag in ('script','style'):self.skip=max(0,self.skip-1)
    def handle_data(self,data):
        if not self.skip:self.parts.append(data)

url='https://transformer-circuits.pub/2026/emotions/index.html'
raw=urllib.request.urlopen(url,timeout=90).read().decode()
parser=Text();parser.feed(raw)
lines=[re.sub(r'\s+',' ',x).strip() for x in ''.join(parser.parts).splitlines()]
lines=[x for x in lines if x]
(ROOT/'emotion-paper-text.txt').write_text('\n'.join(lines),encoding='utf-8')
print('Primary URL:',url,'HTML bytes:',len(raw),'visible lines:',len(lines))
for i,line in enumerate(lines):
    if re.search(r'steering strength|steering coefficient|scale.*steer|norm.*steer|steer.*norm|coefficient|0\.05',line,re.I):
        print(i+1,line[:3500])
for name,url in {
    'server-readme-552f18f91.md':'https://raw.githubusercontent.com/ggml-org/llama.cpp/552f18f91/tools/server/README.md',
}.items():
    (ROOT/name).write_bytes(urllib.request.urlopen(url,timeout=60).read())
