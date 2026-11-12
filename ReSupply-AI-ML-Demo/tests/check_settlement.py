"""Offline integration checks. No real PayPal requests or app database writes."""
import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import threading
from unittest.mock import patch
from uuid import uuid4

import check_paypal as base
from paypal_gateway import SandboxPayPal, PayPalFailure
from paypalserversdk.api_helper import APIHelper
from paypalserversdk.models.capture_request import CaptureRequest
from paypalserversdk.models.captured_payment import CapturedPayment
from paypalserversdk.models.payment_authorization import PaymentAuthorization

code, ok, request = base.code, base.ok, base.request


class FakeSettlement(base.FakePayPal):
    def __init__(self):
        super().__init__()
        self.captures, self.voids = [], []
        self.capture_keys, self.void_keys = {}, set()
        self.lose_capture = self.lose_void = self.unsettled_capture = self.unsettled_void = False
        self.fail_capture_get = self.fail_after_post = self.pending_capture = self.lag_order = False
        self.post_started = self.post_release = None

    def hold_remote(self, hold_id):
        for remote in self.remotes.values():
            unit = remote['purchase_units'][0]
            for hold in unit.get('payments', {}).get('authorizations', []):
                if hold['id'] == hold_id:
                    return remote, unit, hold
        raise PayPalFailure('Unknown hold.', confirmed=True)

    def wait_post(self):
        if self.post_started:
            self.post_started.set()
            assert self.post_release.wait(5)
            self.post_started = None

    def capture(self, hold_id, body, request_id):
        self.captures.append((hold_id, deepcopy(body), request_id))
        self.wait_post()
        if self.unsettled_capture:
            self.unsettled_capture = False
            raise PayPalFailure('Capture result not yet visible.')
        remote, unit, hold = self.hold_remote(hold_id)
        if request_id not in self.capture_keys:
            assert hold['status'] == 'CREATED'
            cap = {**deepcopy(body), 'id': f'C{len(self.capture_keys)+1:016d}',
                   'status': 'PENDING' if self.pending_capture else 'COMPLETED',
                   'create_time': datetime.now(timezone.utc).isoformat(),
                   'supplementary_data': {'related_ids': {'order_id': remote['id'], 'authorization_id': hold_id}},
                   'links': [{'rel':'up','href':f'https://api-m.sandbox.paypal.com/v2/payments/authorizations/{hold_id}'}]}
            self.capture_keys[request_id] = cap
            unit['payments']['captures'] = [cap]
            hold['status'] = 'CAPTURED'
        if self.lose_capture:
            self.lose_capture = False
            raise PayPalFailure('Capture response lost.')
        if self.fail_after_post:
            self.fail_after_post = False
            self.fail_get = True
        return deepcopy(self.capture_keys[request_id])

    def get(self, remote_id):
        remote = super().get(remote_id)
        if self.lag_order:
            remote['purchase_units'][0].get('payments', {}).pop('captures', None)
        return remote

    def get_capture(self, capture_id):
        if self.fail_capture_get:
            self.fail_capture_get = False
            raise PayPalFailure('Capture verification GET lost.')
        for capture in self.capture_keys.values():
            if capture['id'] == capture_id:
                return deepcopy(capture)
        raise PayPalFailure('Unknown capture.', confirmed=True)

    def void(self, hold_id, request_id):
        self.voids.append((hold_id, request_id))
        self.wait_post()
        if self.unsettled_void:
            self.unsettled_void = False
            raise PayPalFailure('Void result not yet visible.')
        _, _, hold = self.hold_remote(hold_id)
        if request_id not in self.void_keys:
            assert hold['status'] == 'CREATED'
            hold['status'] = 'VOIDED'
            self.void_keys.add(request_id)
        if self.lose_void:
            self.lose_void = False
            raise PayPalFailure('Void response lost.')
        return {}  # SDK handles PayPal's 204 empty response.


async def held(fake, draft):
    order = await base.approve(draft)
    receipt = await ok(f"/api/orders/{order['id']}/paypal/create", 'POST', {'expected_version':order['version']})
    fake.remotes[receipt['paypal_order_id']]['status'] = 'APPROVED'
    return await ok(f"/api/orders/{order['id']}/paypal/authorize", 'POST', {'paypal_order_id':receipt['paypal_order_id']})


async def scenario(check):
    with tempfile.TemporaryDirectory(prefix='resupply-settle-') as folder:
        code.DB_PATH = Path(folder) / 'resupply.db'
        fake = FakeSettlement()
        draft = await base.seed(fake)
        await check(fake, draft)


async def capture_receive(fake, draft):
    order = await held(fake, draft)
    path = f"/api/orders/{order['id']}"
    original = await ok('/api/products')
    sales = await ok('/api/sales')
    assert order['can_capture'] and order['can_void'] and not order['can_receive']
    receiving = {'expected_version':2, 'request_id':str(uuid4())}
    assert (await request(path+'/receive','POST',{**receiving,'quantity':1}))[0] == 422
    assert (await request(path+'/receive','POST',receiving))[0] == 409
    for payload in ({'expected_version':1}, {'expected_version':True}, {'expected_version':2,'amount':'0.01'}):
        assert (await request(path+'/paypal/capture','POST',payload))[0] in (409,422)
    assert not fake.captures
    # Immutable snapshot survives later supplier quote edits.
    await ok('/api/products/1/quotes','PUT',{'supplier_id':1,'unit_cost':'2.00','lead_time_days':3})
    paid = await ok(path+'/paypal/capture','POST',{'expected_version':2})
    assert paid['payment']['state']=='captured' and paid['payment']['capture_id']
    assert paid['can_receive'] and not paid['can_capture'] and not paid['can_void'] and not paid['can_cancel']
    assert fake.captures[0][1] == {'amount':{'currency_code':'USD','value':'10.00'},'final_capture':True,'invoice_id':order['number']+'-v2'}
    assert fake.captures[0][2] not in (fake.creates[0][1], fake.authorizations[0][1])
    await ok(path+'/paypal/capture','POST',{'expected_version':2})
    assert len(fake.captures)==1
    assert (await request(path+'/paypal/void','POST',{'expected_version':2}))[0]==409
    assert (await request(path+'/cancel','POST',{'expected_version':2}))[0]==409
    assert await ok('/api/products')==original and await ok('/api/sales')==sales
    code.initialize_database()
    assert (await ok(path))['payment']['capture_id']==paid['payment']['capture_id']
    received = await ok(path+'/receive','POST',receiving)
    assert not received['replayed'] and received['order']['status']=='received'
    receipt = received['order']['receipt']
    expected = draft['items'][0]['quantity']
    assert receipt['units']==expected and receipt['items'][0]['stock_after']==17+expected
    assert receipt['items'][0]['stock_before']==17 and not received['order']['can_receive']
    after = await ok('/api/products')
    assert after[0]['stock']==17+expected and after[0]['unit_cost']==original[0]['unit_cost']
    assert (await ok(path+'/receive','POST',receiving))['replayed']
    assert (await ok(path+'/receive','POST',{'expected_version':2,'request_id':str(uuid4())}))['replayed']
    assert await ok('/api/products')==after and await ok('/api/sales')==sales
    assert (await ok(path+'/paypal/sync','POST'))['status']=='received'
    await ok(path+'/paypal/capture','POST',{'expected_version':2})
    assert len(fake.captures)==1
    with code.database() as db:
        assert db.execute('SELECT COUNT(*) FROM stock_receipts').fetchone()[0]==1
        assert db.execute('SELECT COUNT(*) FROM stock_receipt_lines').fetchone()[0]==1
    # Stock received closes the open-product guard; a later sale can require another order.
    await ok('/api/sales','POST',{'product_id':1,'quantity':15,'request_id':str(uuid4())},status=201)
    fresh = await ok('/api/orders','POST',{'request_id':str(uuid4()),'budget':'30.00'},status=201)
    assert fresh['order']['id']!=order['id']
    assert (await request(f"/api/orders/{fresh['order']['id']}/receive",'POST',receiving))[0]==409


async def void_cancel(fake, draft):
    order = await held(fake,draft)
    path=f"/api/orders/{order['id']}"
    before=await ok('/api/products')
    cancelled=await ok(path+'/paypal/void','POST',{'expected_version':2})
    assert cancelled['status']=='cancelled' and cancelled['payment']['state']=='voided'
    assert cancelled['version']==3 and not cancelled['can_capture'] and not cancelled['can_receive']
    await ok(path+'/paypal/void','POST',{'expected_version':2})
    assert len(fake.voids)==1 and not fake.captures
    assert (await ok(path+'/paypal/sync','POST'))['payment']['state']=='voided'
    assert (await request(path+'/paypal/capture','POST',{'expected_version':2}))[0]==409
    assert await ok('/api/products')==before
    fresh=await ok('/api/orders','POST',{'request_id':str(uuid4()),'budget':'10.00'},status=201)
    assert fresh['order']['id']!=order['id']


async def lost_capture(fake,draft):
    await held(fake,draft)
    fake.lose_capture=True
    assert (await request('/api/orders/1/paypal/capture','POST',{'expected_version':2}))[0]==502
    state=await ok('/api/orders/1')
    assert state['payment']['state']=='capture_unknown' and not state['can_void']
    assert (await request('/api/orders/1/paypal/void','POST',{'expected_version':2}))[0]==409
    recovered=await ok('/api/orders/1/paypal/sync','POST')
    assert recovered['payment']['state']=='captured'
    await ok('/api/orders/1/paypal/capture','POST',{'expected_version':2})
    assert len(fake.captures)==1


async def lost_verification(fake,draft):
    await held(fake,draft)
    fake.fail_capture_get=True
    assert (await request('/api/orders/1/paypal/capture','POST',{'expected_version':2}))[0]==502
    saved=await ok('/api/orders/1')
    assert saved['payment']['capture_id'] and saved['payment']['state']=='capture_unknown'
    fake.lag_order=True
    assert (await ok('/api/orders/1/paypal/sync','POST'))['payment']['state']=='captured'
    assert len(fake.captures)==1


async def unsettled_capture(fake,draft):
    await held(fake,draft)
    fake.unsettled_capture=True
    assert (await request('/api/orders/1/paypal/capture','POST',{'expected_version':2}))[0]==502
    state=await ok('/api/orders/1/paypal/sync','POST')
    assert state['payment']['state']=='capture_unknown' and state['can_capture'] and not state['can_void']
    assert (await request('/api/orders/1/paypal/void','POST',{'expected_version':2}))[0]==409
    await ok('/api/orders/1/paypal/capture','POST',{'expected_version':2})
    assert len(fake.capture_keys)==1 and fake.captures[0][2]==fake.captures[1][2]


async def lagged_capture(fake,draft):
    await held(fake,draft)
    fake.lose_capture=True;fake.lag_order=True
    assert (await request('/api/orders/1/paypal/capture','POST',{'expected_version':2}))[0]==502
    assert (await ok('/api/orders/1/paypal/sync','POST'))['payment']['state']=='capture_unknown'
    assert (await request('/api/orders/1/paypal/capture','POST',{'expected_version':2}))[0]==409
    assert len(fake.captures)==1
    fake.lag_order=False
    assert (await ok('/api/orders/1/paypal/sync','POST'))['payment']['state']=='captured'


async def pending_capture(fake,draft):
    await held(fake,draft)
    fake.pending_capture=True
    before=await ok('/api/products')
    pending=await ok('/api/orders/1/paypal/capture','POST',{'expected_version':2})
    assert pending['payment']['state']=='capture_pending' and not pending['can_receive']
    assert (await request('/api/orders/1/receive','POST',{'expected_version':2,'request_id':str(uuid4())}))[0]==409
    assert (await request('/api/orders/1/paypal/void','POST',{'expected_version':2}))[0]==409
    assert (await request('/api/orders/1/paypal/capture','POST',{'expected_version':2}))[0]==409
    assert await ok('/api/products')==before
    next(iter(fake.capture_keys.values()))['status']='COMPLETED'
    assert (await ok('/api/orders/1/paypal/sync','POST'))['can_receive']


async def lost_void(fake,draft):
    await held(fake,draft)
    fake.lose_void=True
    assert (await request('/api/orders/1/paypal/void','POST',{'expected_version':2}))[0]==502
    state=await ok('/api/orders/1')
    assert state['payment']['state']=='void_unknown' and not state['can_capture']
    recovered=await ok('/api/orders/1/paypal/sync','POST')
    assert recovered['status']=='cancelled' and recovered['payment']['state']=='voided'
    assert len(fake.voids)==1 and not fake.captures


async def unsettled_void(fake,draft):
    await held(fake,draft)
    fake.unsettled_void=True
    assert (await request('/api/orders/1/paypal/void','POST',{'expected_version':2}))[0]==502
    state=await ok('/api/orders/1/paypal/sync','POST')
    assert state['can_void'] and not state['can_capture']
    assert (await request('/api/orders/1/paypal/capture','POST',{'expected_version':2}))[0]==409
    await ok('/api/orders/1/paypal/void','POST',{'expected_version':2})
    assert len(fake.void_keys)==1 and fake.voids[0][1]==fake.voids[1][1]


async def capture_race(fake,draft):
    await held(fake,draft)
    fake.post_started=threading.Event();fake.post_release=threading.Event()
    pending=asyncio.create_task(request('/api/orders/1/paypal/capture','POST',{'expected_version':2}))
    assert await asyncio.to_thread(fake.post_started.wait,3)
    for endpoint in ('capture','void','sync'):
        body=None if endpoint=='sync' else {'expected_version':2}
        assert (await request('/api/orders/1/paypal/'+endpoint,'POST',body))[0]==409
    assert (await ok('/api/products'))[0]['stock']==17
    fake.post_release.set()
    assert (await pending)[0]==200
    assert len(fake.captures)==1 and not fake.voids


async def void_race(fake,draft):
    await held(fake,draft)
    fake.post_started=threading.Event();fake.post_release=threading.Event()
    pending=asyncio.create_task(request('/api/orders/1/paypal/void','POST',{'expected_version':2}))
    assert await asyncio.to_thread(fake.post_started.wait,3)
    assert (await request('/api/orders/1/paypal/capture','POST',{'expected_version':2}))[0]==409
    fake.post_release.set()
    assert (await pending)[0]==200
    assert len(fake.voids)==1 and not fake.captures


async def receive_race(fake,draft):
    await held(fake,draft)
    await ok('/api/orders/1/paypal/capture','POST',{'expected_version':2})
    fake.get_started=threading.Event();fake.get_release=threading.Event()
    body={'expected_version':2,'request_id':str(uuid4())}
    pending=asyncio.create_task(request('/api/orders/1/receive','POST',body))
    assert await asyncio.to_thread(fake.get_started.wait,3)
    assert (await request('/api/orders/1/receive','POST',{'expected_version':2,'request_id':str(uuid4())}))[0]==409
    fake.get_release.set()
    assert (await pending)[0]==200
    assert (await ok('/api/orders/1/receive','POST',body))['replayed']
    assert (await ok('/api/products'))[0]['stock']==17+draft['units']


async def stale_capture_worker(fake,draft):
    await held(fake,draft)
    fake.get_started=threading.Event();fake.get_release=threading.Event()
    pending=asyncio.create_task(request('/api/orders/1/paypal/capture','POST',{'expected_version':2}))
    assert await asyncio.to_thread(fake.get_started.wait,3)
    with code.database() as db:
        db.execute('UPDATE paypal_checkouts SET operation_started_at=?',( (datetime.now(timezone.utc)-timedelta(minutes=4)).isoformat(),))
    # This GET replaces the expired lease before the old worker can send a mutation.
    fake.get_started=None
    await ok('/api/orders/1/paypal/sync','POST')
    fake.get_release.set()
    assert (await pending)[0]==409
    assert not fake.captures


async def mismatch_blocks_receiving(fake,draft):
    await held(fake,draft)
    await ok('/api/orders/1/paypal/capture','POST',{'expected_version':2})
    before=await ok('/api/products')
    cap=next(iter(fake.capture_keys.values()))
    cap['invoice_id']='WRONG-ORDER'
    assert (await request('/api/orders/1/receive','POST',{'expected_version':2,'request_id':str(uuid4())}))[0]==409
    assert await ok('/api/products')==before
    assert (await ok('/api/orders/1'))['payment']['state']=='review_required'
    cap['invoice_id']=(await ok('/api/orders/1'))['number']+'-v2'
    assert (await ok('/api/orders/1/paypal/sync','POST'))['can_receive']
    cap['supplementary_data']['related_ids']['authorization_id']='OTHERAUTH123'
    assert (await request('/api/orders/1/paypal/sync','POST'))[0]==409
    assert await ok('/api/products')==before


async def receipt_rollback(fake,draft):
    await ok('/api/orders/1/cancel','POST',{'expected_version':1})
    await ok('/api/products','POST',{'sku':'B','name':'Second product','stock':20,'unit_cost':'0.05'},status=201)
    await ok('/api/sales','POST',{'product_id':2,'quantity':3,'request_id':str(uuid4())},status=201)
    quote=await ok('/api/products/2/quotes','PUT',{'supplier_id':1,'unit_cost':'0.05','lead_time_days':2},status=201)
    await ok('/api/products/2/supplier-selection','PUT',{'quote_id':quote['id']})
    order=(await ok('/api/orders','POST',{'request_id':str(uuid4()),'budget':'20.00'},status=201))['order']
    order=(await ok('/api/orders/2/approve','POST',{'request_id':str(uuid4()),'expected_version':1,'spending_limit':'20.00'}))['order']
    remote=await ok('/api/orders/2/paypal/create','POST',{'expected_version':2})
    fake.remotes[remote['paypal_order_id']]['status']='APPROVED'
    await ok('/api/orders/2/paypal/authorize','POST',{'paypal_order_id':remote['paypal_order_id']})
    await ok('/api/orders/2/paypal/capture','POST',{'expected_version':2})
    await ok('/api/products/2/stock','PATCH',{'stock':1_000_000})
    before=await ok('/api/products')
    body={'expected_version':2,'request_id':str(uuid4())}
    assert (await request('/api/orders/2/receive','POST',body))[0]==409
    assert await ok('/api/products')==before
    with code.database() as db:
        assert db.execute('SELECT COUNT(*) FROM stock_receipts').fetchone()[0]==0
        assert db.execute('SELECT COUNT(*) FROM stock_receipt_lines').fetchone()[0]==0
        assert code.checkout_row(db,2)['operation_token'] is None
    await ok('/api/products/2/stock','PATCH',{'stock':0})
    assert not (await ok('/api/orders/2/receive','POST',body))['replayed']


def sdk_contract():
    gateway=SandboxPayPal.__new__(SandboxPayPal)
    calls=[]
    def capture(options):
        calls.append(('capture', options))
        assert isinstance(options['body'], CaptureRequest)
        body=json.loads(APIHelper.json_serialize(options['body']))
        assert body['final_capture'] is True and body['amount']['value']=='10.00'
        return SimpleNamespace(body=CapturedPayment.from_dictionary({'id':'C123','status':'COMPLETED',
            'amount':body['amount'],'final_capture':True,'invoice_id':'SDK-INVOICE',
            'links':[{'rel':'up','href':'https://api.sandbox.paypal.com/v2/payments/authorizations/A123'}]}))
    def void(options):
        calls.append(('void',options));return SimpleNamespace(body=None)
    gateway.client=SimpleNamespace(payments=SimpleNamespace(capture_authorized_payment=capture,void_payment=void,
        get_authorized_payment=lambda options: SimpleNamespace(body=PaymentAuthorization.from_dictionary({'id':options['authorization_id'],'status':'CREATED'})),
        get_captured_payment=lambda options: SimpleNamespace(body=CapturedPayment.from_dictionary({'id':options['capture_id'],'invoice_id':'SDK-INVOICE','final_capture':True}))))
    key=str(uuid4());other=str(uuid4())
    assert gateway.capture('A123',{'amount':{'currency_code':'USD','value':'10.00'},'final_capture':True},key)['id']=='C123'
    assert gateway.void('A123',other)=={}
    assert gateway.get_authorization('A123')['id']=='A123' and gateway.get_capture('C123')['id']=='C123'
    assert gateway.get_capture('C123')['final_capture'] is True and gateway.get_capture('C123')['invoice_id']=='SDK-INVOICE'
    assert calls[0][1]['authorization_id']=='A123' and calls[0][1]['paypal_request_id']==key
    assert calls[1][1]['paypal_request_id']==other


async def run():
    sdk_contract()
    for check in (capture_receive,void_cancel,lost_capture,lost_verification,unsettled_capture,lagged_capture,
                  pending_capture,lost_void,unsettled_void,capture_race,void_race,receive_race,
                  stale_capture_worker,mismatch_blocks_receiving,receipt_rollback):
        await scenario(check)
        print('PASS:',check.__name__)
    print('PASS: full capture/void, GET recovery, opposing-action protection, immutable totals, one-time receipt and atomic inventory rollback.')


if __name__=='__main__':
    asyncio.run(run())
