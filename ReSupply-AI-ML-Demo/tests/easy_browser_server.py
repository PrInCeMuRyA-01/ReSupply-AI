"""Isolated browser-test fixture. Uses temporary DBs and fake PayPal only."""
import os
from pathlib import Path
import tempfile

os.environ['PAYPAL_SANDBOX_CLIENT_ID']='TEST_BROWSER_CLIENT'
os.environ['PAYPAL_SANDBOX_CLIENT_SECRET']='TEST_BROWSER_SECRET'
os.environ['OPENAI_ENABLED']='false'
from check_settlement import code,FakeSettlement


class BrowserSettlement(FakeSettlement):
    def create(self,body,request_id):
        result=super().create(body,request_id)
        self.remotes[result['id']]['status']='APPROVED'
        return result


if __name__=='__main__':
    import uvicorn
    with tempfile.TemporaryDirectory(prefix='easy-browser-') as folder:
        code.DB_PATH=Path(folder)/'real.db';code.DEMO_DB_PATH=Path(folder)/'demo.db'
        fake=BrowserSettlement();code.SandboxPayPal=lambda:fake
        if os.environ.get('RESUPPLY_ML_DEMO_TEST')=='1':
            from prepare_ml_demo import prepare_ml_demo
            prepare_ml_demo(code)
        uvicorn.run(code.app,host='127.0.0.1',port=int(os.environ['RESUPPLY_TEST_PORT']),log_level='warning')
