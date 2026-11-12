"""Conservative Hindi/Hinglish/English commands; every endpoint is read-only."""
from decimal import Decimal, InvalidOperation
import re
import unicodedata
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from demand_forecast import history_snapshot, response_view
from shop_workspace import planning_source

ALIASES = {'ब्लू':'blue','रेड':'red','ग्रीन':'green','पेन':'pen','पेन्स':'pens','नोटबुक':'notebook',
           'बुक':'book','मिल्क':'milk','दूध':'milk','राइस':'rice','चावल':'rice','शुगर':'sugar','चीनी':'sugar'}
WORDS = {'zero':0,'one':1,'two':2,'three':3,'four':4,'five':5,'six':6,'seven':7,'eight':8,'nine':9,
         'ten':10,'eleven':11,'twelve':12,'thirteen':13,'fourteen':14,'fifteen':15,'sixteen':16,
         'seventeen':17,'eighteen':18,'nineteen':19,'twenty':20,'thirty':30,'forty':40,'fifty':50,
         'sixty':60,'seventy':70,'eighty':80,'ninety':90,'hundred':100,'thousand':1000,
         'दस':10,'बीस':20,'तीस':30,'चालीस':40,'पचास':50,'साठ':60,'सत्तर':70,'अस्सी':80,'नब्बे':90,'सौ':100,
         'dus':10,'bees':20,'tees':30,'chalis':40,'chaalis':40,'pachas':50,'pachaas':50,'sattar':70,'assi':80,'nabbe':90,'sau':100}
FILLER = set('ka ki ke kitna kitni kitne hai hain h ha kya mujhe mera mere batao bata bataiye dikhao dikha dikhana show tell me my the a an of is are what how much many please check current for in available units unit quantity count stock inventory forecast prediction predict sales sale demand next days day week seven 7 actual demo synthetic agle agla din dino hafte week kaunse kis kin products product items item low kam khatam out empty short remaining'.split()) | set('का की के कितना कितनी कितने है हैं क्या मुझे मेरा मेरे बताओ बता बताइए दिखाओ दिखा दिखाना स्टॉक स्टाक मात्रा फोरकास्ट पूर्वानुमान बिक्री मांग अगले अगला दिन दिनों हफ्ते कौनसे किन किस उत्पाद प्रोडक्ट प्रोडक्ट्स कम खत्म खाली'.split())
BUDGET_FILLER = set('budget dollar dollars usd dollarss purchase purchasing plan banao bana bna banaiye build make create show give for a an the my me please mujhe mera mere hume hum ka ki ke mein me mai ka plan bana do with under up to limit rakho set'.split()) | set('बजट डॉलर डॉलर्स खरीद खरीदारी प्लान योजना बनाओ बना बनाइए में का की के दो बनाना मुझे मेरा मेरे हमें कृपया रुपये'.split())


def normalize(text):
    text = unicodedata.normalize('NFKC',text).casefold()
    text = text.replace("what's","what is")
    text = ''.join(str(unicodedata.digit(c)) if c.isdecimal() else c for c in text)
    text = ''.join(c if c.isalnum() or c.isspace() or unicodedata.category(c).startswith('M') or c in '_.$₹€£,-' else ' ' for c in text)
    return ' '.join(text.split())


def name_key(text):
    return ' '.join(ALIASES.get(word,word) for word in re.split(r'[\s._,\-]+',normalize(text)) if word)


class CommandPreview(BaseModel):
    model_config = ConfigDict(extra='forbid')
    text: str = Field(min_length=1,max_length=400)
    product_id: int | None = Field(default=None,gt=0,le=9_223_372_036_854_775_807,strict=True)
    forecast_source: Literal['actual','demo'] = 'actual'
    lead_time_days: int = Field(default=3,ge=1,le=30,strict=True)
    coverage_days: int = Field(default=7,ge=1,le=30,strict=True)
    buffer_days: int = Field(default=2,ge=0,le=14,strict=True)


def amount_from_command(text):
    if re.search(r'₹|€|£|\b(?:inr|rupees?|rupee|rupaye|rs|eur|euro|cents?|paisa|percent|percentage)\b|रुप|पैस|प्रतिशत',text):
        return None,'This app previews USD budgets. Say an amount in dollars, for example: 50 dollar budget ka plan banao.'
    values = []
    spans = []
    for match in re.finditer(r'(?<![\w.])[-+]?(?:\d+(?:,\d{3})*(?:\.\d+)?|\.\d+)(?![\w.])',text):
        try:values.append(Decimal(match.group().replace(',','')))
        except InvalidOperation:return None,'Use one clear dollar amount.'
        spans.append(match.span())
    words = text.split()
    groups = [];group=[]
    for word in words+['END']:
        if word in WORDS:group.append(word)
        elif group:groups.append(group);group=[]
    for group in groups:
        total=current=0;last=None;valid=True
        for word in group:
            value=WORDS[word]
            if value==100:current=max(1,current)*100
            elif value==1000:total+=max(1,current)*1000;current=0
            else:
                if last is not None and last<20 and value<100:valid=False
                if last is not None and last>=20 and last<100 and value>=10 and value<100:valid=False
                current+=value
            last=value
        if not valid:return None,'Number words are unclear. Type the dollar amount as digits.'
        values.append(Decimal(total+current))
    if len(values)!=1:return None,'Use one dollar amount, for example: 50 dollar budget ka plan banao. Set delivery/coverage/buffer in the planner controls.'
    value=values[0]
    if not value.is_finite() or value<0 or value>1_000_000 or value.as_tuple().exponent < -2:
        return None,'Budget must be between $0.00 and $1,000,000.00, with at most 2 decimal places.'
    rest=text
    for start,end in reversed(spans):rest=rest[:start]+' '+rest[end:]
    leftover=[word for word in rest.replace('$',' ').split() if word not in WORDS and word not in BUDGET_FILLER]
    if leftover:return None,'This command previews the whole-shop budget. Use: 50 dollar budget ka plan banao.'
    return value.quantize(Decimal('.01')),None


def product_match(products, words, selected):
    query=name_key(' '.join(word for word in words if word not in FILLER))
    if not query:
        chosen=next((p for p in products if p['id']==selected),None)
        return chosen,[] if chosen else products,'Choose a product or include its name/SKU.'
    exact=[p for p in products if query in {name_key(p['sku']),name_key(p['name'])}]
    candidates=exact or [p for p in products if set(query.split()).issubset(set(name_key(p['name']).split())) or set(query.split()).issubset(set(name_key(p['sku']).split()))]
    if len(candidates)==1:return candidates[0],[],''
    if candidates and selected is not None:
        chosen=next((p for p in candidates if p['id']==selected),None)
        if chosen:return chosen,[],''
    return None,candidates or products,'Several products match. Choose one to preview.' if candidates else 'Product name/SKU did not match. Correct the text or choose a product below.'


def assistant_router(database,shop_today,calculate_restock,calculate_purchase_plan):
    router=APIRouter(prefix='/api/assistant',tags=['Voice and text assistant'])

    @router.post('/preview')
    def preview(data:CommandPreview):
        text=normalize(data.text)
        result={'status':'unsupported','intent':None,'message':'Try stock, saved forecast, or a USD budget plan. One command at a time.','items':[]}
        if not text:return result
        words=text.split()
        forbidden=r'\b(?:delete|remove|update|sell|sold|record|capture|void|pay|payment|approve|cancel|receive|buy|order|train)\b|बेच|बिक|पेमेंट|भुगतान|डिलीट|हटाओ|ऑर्डर'
        if re.search(forbidden,text):
            return {**result,'message':'This voice version supports stock checks, saved forecasts and budget previews. Use the existing forms for sales, orders and payments.'}
        stock=bool(re.search(r'\b(?:stock|inventory)\b|स्टॉक|स्टाक',text))
        forecast=bool(re.search(r'\b(?:forecast|prediction|predict)\b|फोरकास्ट|पूर्वानुमान',text))
        budget=bool(re.search(r'\bbudget\b|बजट',text))
        if sum((stock,forecast,budget))!=1:return result
        with database() as db:
            db.execute('BEGIN')
            products=[dict(p) for p in db.execute('SELECT id,sku,name,stock FROM products ORDER BY id')]
            if budget:
                amount,error=amount_from_command(text)
                if error:return {**result,'intent':'budget','message':error}
                plan=calculate_purchase_plan(calculate_restock(db,data.lead_time_days,data.coverage_days,data.buffer_days),amount)
                return {'status':'ready','intent':'budget','message':f'USD product-cost budget ${amount}: a read-only purchase preview for all products.',
                        'plan':plan.model_dump(mode='json'),'items':[]}
            if not products:return {**result,'status':'not_ready','message':'Add a product before checking stock or saved forecasts.'}
            if forecast:
                mentioned=[mode for mode in ('actual','demo') if re.search(r'\b'+mode+r'\b',text)]
                if len(mentioned)>1 or mentioned and mentioned[0]!=data.forecast_source:
                    return {**result,'intent':'forecast','message':'Match the Saved forecast source selector to your command: Actual shop records or Demo / synthetic.'}
            low=stock and bool(re.search(r'\b(?:low|kam|khatam|empty|short)\b|कम|खत्म|खाली',text))
            product,candidates,message=product_match(products,words,data.product_id)
            # A generic low-stock query covers all products, independent of the
            # optional product dropdown. A named query must resolve explicitly.
            residual=name_key(' '.join(word for word in words if word not in FILLER))
            if low and not residual:
                product=None;candidates=[]
            elif product is None:
                return {'status':'needs_product','intent':'forecast' if forecast else 'stock','message':message,
                        'items':[{k:p[k] for k in ('id','sku','name')} for p in candidates]}
            if low:
                restock=calculate_restock(db,data.lead_time_days,data.coverage_days,data.buffer_days)
                items=[p.model_dump(mode='json') for p in restock.items if p.status in ('out_of_stock','delivery_risk','restock') and (not product or p.product_id==product['id'])]
                return {'status':'ready','intent':'low_stock','message':'Current restock estimates, using reviewed '+planning_source()+' forecasts or the sales-average fallback. Delivery, coverage and buffer use the planner controls.', 'items':items}
            if stock:return {'status':'ready','intent':'stock','message':f"{product['name']} ({product['sku']}): {product['stock']} units in stock.",'product':product,'items':[]}
            today=shop_today()
            snapshot=history_snapshot(db,product['id'],data.forecast_source,today)
            saved=db.execute('SELECT * FROM demand_forecast_runs WHERE product_id=? AND source=? ORDER BY id DESC LIMIT 1',(product['id'],data.forecast_source)).fetchone()
            view=response_view(db,snapshot,saved)
            if not view['report']:
                return {'status':'not_ready','intent':'forecast','product':product,'source':data.forecast_source,'message':view['reason']+' Train from the ML demand forecast section first.','items':[]}
            if not view['report_current']:
                return {'status':'not_ready','intent':'forecast','product':product,'source':data.forecast_source,'message':'Saved forecast is outdated. Train again in ML demand forecast before using its values.','items':[]}
            r=view['report']
            return {'status':'ready','intent':'forecast','product':product,'source':data.forecast_source,'run_id':view['run_id'],
                    'message':f"{'DEMO synthetic' if r['demo'] else 'Actual-data'} forecast: {r['selected_total_units']} units expected over the next 7 days.",
                    'total_units':r['selected_total_units'],'selected_method':r['selected_method'],'model_mae':r['evaluation']['model_mae'],
                    'baseline_mae':r['evaluation']['baseline_mae'],'items':r['items']}

    return router
