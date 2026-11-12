"""Direct page routes/assets and initial screen visibility in both shops."""
import asyncio
from html.parser import HTMLParser
from pathlib import Path
import tempfile

import check_demo_shop as base
from shop_workspace import demo_scope


class Pages(HTMLParser):
    def __init__(self):super().__init__();self.ids=[];self.screens=[];self.body={};self.links=[];self.assets=[]
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if 'id' in a:self.ids.append(a['id'])
        if tag=='body':self.body=a
        if 'data-screen' in a:self.screens.append((a['data-screen'],'hidden' in a))
        if tag=='a' and 'data-view' in a:self.links.append(a['href'])
        if tag=='script' and 'src' in a:self.assets.append(a['src'])
        if tag=='link' and a.get('rel')=='stylesheet':self.assets.append(a['href'])


async def run():
    with tempfile.TemporaryDirectory(prefix='resupply-pages-') as folder:
        code=base.code
        code.DB_PATH=Path(folder)/'real.db';code.DEMO_DB_PATH=Path(folder)/'demo.db'
        code.initialize_database()
        with demo_scope():code.initialize_database()
        before=(base.snapshot(code.DB_PATH),base.snapshot(code.DEMO_DB_PATH))
        routes={'/':'overview','/inventory':'inventory','/sales':'sales','/sales-history':'history',
            '/forecast':'forecast','/suppliers':'suppliers','/purchasing':'purchasing','/orders':'orders',
            '/assistant':'assistant','/demo-guide':'demo-guide'}
        for prefix,mode in [('', 'real'),('/demo','demo')]:
            for route,view in routes.items():
                status,headers,body=await base.raw_request(prefix+route)
                assert status==200 and headers[b'x-resupply-workspace']==mode.encode()
                doc=Pages();doc.feed(body.decode())
                assert doc.body['data-start-view']==view and doc.body['data-api-prefix']==prefix
                assert len(doc.ids)==len(set(doc.ids)) and len(doc.screens)==10
                assert [name for name,hidden in doc.screens if not hidden]==[view]
                assert all(link.startswith(prefix+'/') for link in doc.links)
                assert prefix+'/assets/app-ui.css' in doc.assets and prefix+'/assets/app-ui.js' in doc.assets
            for asset in ('app-ui.css','app-ui.js'):
                status,headers,body=await base.raw_request(prefix+'/assets/'+asset)
                assert status==200 and body and headers[b'x-resupply-workspace']==mode.encode()
        assert (base.snapshot(code.DB_PATH),base.snapshot(code.DEMO_DB_PATH))==before
        print('PASS: 20 direct real/demo page routes, single visible screen, scoped nav/style/script URLs, unique IDs and all DB tables unchanged.')


if __name__=='__main__':asyncio.run(run())
