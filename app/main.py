import os
import hmac
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, String, Boolean, Numeric, ForeignKey, select, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, Session, sessionmaker

TZ = ZoneInfo("Europe/Moscow")
def today():
    return datetime.now(TZ).date().isoformat()

class Base(DeclarativeBase):
    pass

class Supplier(Base):
    __tablename__ = "suppliers"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)

class Product(Base):
    __tablename__ = "products"
    id: Mapped[int] = mapped_column(primary_key=True)
    sku_key: Mapped[str] = mapped_column(String(600), unique=True)
    brand: Mapped[str] = mapped_column(String(100))
    model: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(100))
    memory: Mapped[str] = mapped_column(String(100))
    color: Mapped[str] = mapped_column(String(100))
    sim: Mapped[str] = mapped_column(String(100))
    approved: Mapped[bool] = mapped_column(Boolean, default=False)
    hidden: Mapped[bool] = mapped_column(Boolean, default=False)

class Offer(Base):
    __tablename__ = "offers"
    __table_args__ = (UniqueConstraint("supplier_id","product_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    cost: Mapped[Decimal] = mapped_column(Numeric(14,2))
    confirmed_date: Mapped[str] = mapped_column(String(10))
    active: Mapped[bool] = mapped_column(Boolean, default=True)

class Markup(Base):
    __tablename__ = "markups"
    __table_args__ = (UniqueConstraint("scope","target"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    scope: Mapped[str] = mapped_column(String(20))
    target: Mapped[str] = mapped_column(String(200))
    amount: Mapped[Decimal] = mapped_column(Numeric(14,2))

class ProductIn(BaseModel):
    brand: str = Field(min_length=1)
    model: str = Field(min_length=1)
    category: str = Field(min_length=1)
    memory: str = ""
    color: str = ""
    sim: str = ""

class OfferIn(BaseModel):
    product: ProductIn
    cost: Decimal = Field(gt=0)

class BatchIn(BaseModel):
    complete: bool
    confirmed_today: bool
    offers: list[OfferIn]

class NameIn(BaseModel):
    name: str = Field(min_length=1)

class FlagIn(BaseModel):
    value: bool

class AmountIn(BaseModel):
    amount: Decimal = Field(ge=0)

def key_for(p: ProductIn):
    return "|".join(v.strip().casefold() for v in (p.brand,p.model,p.category,p.memory,p.color,p.sim))

db_url = os.getenv("DATABASE_URL", "sqlite:///./volt.db")
engine = create_engine(db_url, connect_args={"check_same_thread":False} if db_url.startswith("sqlite") else {}, pool_pre_ping=True)
Sessions = sessionmaker(engine)
app = FastAPI(title="VOLT Control",version="0.1.0")
Base.metadata.create_all(engine)

def session():
    with Sessions() as s:
        yield s

def admin(x_api_key: str | None = Header(None)):
    secret = os.getenv("API_KEY","")
    if not secret or secret == "REPLACE_WITH_LONG_RANDOM_SECRET" or not x_api_key or not hmac.compare_digest(secret,x_api_key):
        raise HTTPException(401,"Admin authorization required")

@app.get("/health")
def health():
    return {"ok":True,"demo_data":False}

@app.post("/admin/suppliers",dependencies=[Depends(admin)])
def add_supplier(body:NameIn,s:Session=Depends(session)):
    if s.scalar(select(Supplier).where(Supplier.name==body.name)):
        raise HTTPException(409,"Supplier already exists")
    obj=Supplier(name=body.name);s.add(obj);s.commit();s.refresh(obj)
    return {"id":obj.id,"name":obj.name}

@app.post("/admin/suppliers/{supplier_id}/batch",dependencies=[Depends(admin)])
def apply_batch(supplier_id:int,body:BatchIn,s:Session=Depends(session)):
    if not s.get(Supplier,supplier_id):
        raise HTTPException(404,"Supplier not found")
    if not body.complete or not body.confirmed_today:
        raise HTTPException(422,"Batch must be complete and confirmed today")
    keys=[key_for(x.product) for x in body.offers]
    if len(keys)!=len(set(keys)):
        raise HTTPException(422,"Duplicate SKU in batch")
    for entry,key in zip(body.offers,keys):
        p=s.scalar(select(Product).where(Product.sku_key==key))
        if p is None:
            p=Product(sku_key=key,**entry.product.model_dump(),approved=False,hidden=False)
            s.add(p);s.flush()
        o=s.scalar(select(Offer).where(Offer.supplier_id==supplier_id,Offer.product_id==p.id))
        if o is None:
            s.add(Offer(supplier_id=supplier_id,product_id=p.id,cost=entry.cost,confirmed_date=today(),active=True))
        else:
            o.cost=entry.cost;o.confirmed_date=today();o.active=True
    for o in s.scalars(select(Offer).where(Offer.supplier_id==supplier_id,Offer.active.is_(True))).all():
        if s.get(Product,o.product_id).sku_key not in keys:
            o.active=False
    s.commit()
    return {"accepted":len(keys),"publication":"pending_admin_approval"}

@app.get("/admin/products",dependencies=[Depends(admin)])
def products(s:Session=Depends(session)):
    result=[]
    for p in s.scalars(select(Product).order_by(Product.id)):
        item={"id":p.id,"brand":p.brand,"model":p.model,"category":p.category,"memory":p.memory,"color":p.color,"sim":p.sim,"approved":p.approved,"hidden":p.hidden}
        if not p.approved or p.hidden:
            item["status"]="hidden"
        else:
            offers=s.scalars(select(Offer.cost).where(Offer.product_id==p.id,Offer.active.is_(True),Offer.confirmed_date==today())).all()
            if not offers:
                item["status"]="on_request"
                item["price"]="По запросу"
            else:
                markup=Decimal("0")
                for scope,target in (("sku",str(p.id)),("model",p.model),("category",p.category)):
                    rule=s.scalar(select(Markup).where(Markup.scope==scope,Markup.target==target))
                    if rule:
                        markup=rule.amount
                        break
                item["status"]="priced"
                item["price"]=str(min(offers)+markup)
        result.append(item)
    return result

@app.get("/admin/reviews",dependencies=[Depends(admin)])
def reviews(s:Session=Depends(session)):
    return [{"id":p.id,"brand":p.brand,"model":p.model,"sim":p.sim,"reason":"New SKU requires approval"} for p in s.scalars(select(Product).where(Product.approved.is_(False))).all()]

@app.patch("/admin/products/{product_id}/approve",dependencies=[Depends(admin)])
def approve(product_id:int,body:FlagIn,s:Session=Depends(session)):
    p=s.get(Product,product_id)
    if p is None: raise HTTPException(404,"Product not found")
    p.approved=body.value;s.commit()
    return {"id":p.id,"approved":p.approved}

@app.patch("/admin/products/{product_id}/hide",dependencies=[Depends(admin)])
def hide(product_id:int,body:FlagIn,s:Session=Depends(session)):
    p=s.get(Product,product_id)
    if p is None: raise HTTPException(404,"Product not found")
    p.hidden=body.value;s.commit()
    return {"id":p.id,"hidden":p.hidden}

@app.put("/admin/markups/{scope}/{target}",dependencies=[Depends(admin)])
def markup(scope:str,target:str,body:AmountIn,s:Session=Depends(session)):
    if scope not in ("sku","model","category"):
        raise HTTPException(422,"Invalid scope")
    obj=s.scalar(select(Markup).where(Markup.scope==scope,Markup.target==target))
    if obj:obj.amount=body.amount
    else:s.add(Markup(scope=scope,target=target,amount=body.amount))
    s.commit()
    return {"ok":True}

# Preview-only: never persists parsed candidates or marks a price list complete.
from app.price_parser import parse_lines

class ParsePreviewIn(BaseModel):
    text: str = Field(min_length=1, max_length=500000)

@app.post("/admin/price-lists/preview", dependencies=[Depends(admin)])
def preview_price_list(body: ParsePreviewIn):
    return parse_lines(body.text)
