import asyncio
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import miniapp
from app.main import app, Product, Supplier, Offer
from app.integrated_collector import Base as CollectorBase, SupplierMessage, SupplierSource, persist
from tests.test_miniapp import signed


def setup(monkeypatch):
    monkeypatch.setenv('VOLT_MINIAPP_ENABLED','1')
    monkeypatch.setenv('TG_BOT_TOKEN','bot-token')
    monkeypatch.setenv('VOLT_OWNER_TG_ID','123')
    engine = create_engine('sqlite://', connect_args={'check_same_thread':False}, poolclass=StaticPool)
    miniapp.Base.metadata.create_all(engine)
    CollectorBase.metadata.create_all(engine)
    db = sessionmaker(engine)
    monkeypatch.setattr(miniapp, 'Sessions', db)
    with db() as session:
        session.add(miniapp.ReaderAccount(slot=1, telegram_id='1234', display_name='Reader', encrypted_session='x', chats_json='[]'))
        session.add(SupplierSource(account='miniapp-1234', chat_id=1, is_hi_catalog=True))
        session.commit()
    return engine, db


def msg(mid,text,date,out=False,edit_date=None):
    return SimpleNamespace(id=mid,raw_text=text,date=date,out=out,edit_date=edit_date)


def test_automatic_staging_is_idempotent_and_never_confirms_prices(monkeypatch):
    engine, db = setup(monkeypatch)
    now = datetime.now(timezone.utc)
    source='miniapp-1234'
    text='🎧AirPods 4 - 8400\n(От 10шт ) - 8300\n17 Pro 256 Silver (eSIM) - 99000\nSamsung Galaxy S25 eSIM - 70000\n16 Pro 256 CPO - 76000'
    m=msg(1,text,now)
    persist(db,source,1,m)
    miniapp.stage_incoming_product(source,1,m,now)
    miniapp.stage_incoming_product(source,1,m,now)
    with db() as session:
        products=session.scalars(select(Product)).all()
        assert len(products)==1 and products[0].category=='Наушники' and not products[0].approved
        assert len(session.scalars(select(miniapp.IncomingProduct)).all())==1
        assert session.scalars(select(Supplier)).all()==[]
        assert session.scalars(select(Offer)).all()==[]
    other=msg(2,'🎧AirPods 5 - 10600',now-timedelta(days=1))
    outgoing=msg(3,'🎧AirPods 5 - 10600',now,out=True)
    unknown=msg(4,'🎧AirPods 5 - 10600',now)
    for chat, item in [(1,other),(1,outgoing),(2,unknown)]:
        persist(db,source,chat,item)
        miniapp.stage_incoming_product(source,chat,item,now)
    with db() as session:
        assert len(session.scalars(select(Product)).all())==1
    engine.dispose()


def test_incoming_source_exposed_only_to_owner_and_confirmed_explicitly(monkeypatch):
    engine, db=setup(monkeypatch)
    now=datetime.now(timezone.utc)
    m=msg(10,'🎧AirPods 4 - 8400',now)
    persist(db,'miniapp-1234',1,m)
    miniapp.stage_incoming_product('miniapp-1234',1,m,now)
    client=TestClient(app)
    assert client.get('/miniapp/api/product-sources').status_code==401
    headers={'X-Telegram-Init-Data':signed()}
    data=client.get('/miniapp/api/product-sources',headers=headers).json()
    assert len(data)==1 and data[0]['price']=='8400.00' and data[0]['slot']==1
    source=data[0]
    path=f"/miniapp/api/accounts/1/messages/{source['message_id']}/import-line"
    payload={'line':source['line'],'message_hash':source['message_hash'],'supplier_name':'Real supplier','confirmed_today':True}
    assert client.post(path,json=payload,headers=headers).status_code==200
    with db() as session:
        product=session.scalar(select(Product))
        assert not product.approved
        assert session.scalar(select(Offer)).cost == 8400
    # After the original message changes, its old price is not shown as current.
    with db() as session:
        session.get(SupplierMessage,source['message_id']).text='changed'
        session.commit()
    assert client.get('/miniapp/api/product-sources',headers=headers).json()==[]
    assert client.post(path,json=payload,headers=headers).status_code==409
    engine.dispose()
