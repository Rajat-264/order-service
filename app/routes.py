from fastapi import APIRouter, Depends, Form, Request, HTTPException, Security,Query
from fastapi.responses import HTMLResponse, RedirectResponse,JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, ExpiredSignatureError, JWTError
from datetime import datetime
from starlette.status import HTTP_302_FOUND
import requests
from app.models import Order, CartItem
from app.database import SessionLocal
from starlette.status import HTTP_302_FOUND

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

# Secret key and algorithm
SECRET_KEY = "your-secret-key"
ALGORITHM = "HS256"
security = HTTPBearer()

# DB dependency
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Token validation
def get_current_user(token: HTTPAuthorizationCredentials = Security(security)):
    if not token or not token.credentials:
        raise HTTPException(status_code=403, detail="Invalid token")

    try:
        payload = jwt.decode(token.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        exp = payload.get("exp")
        if exp is None or datetime.utcfromtimestamp(exp) < datetime.utcnow():
            raise HTTPException(status_code=401, detail="Token expired")
        return payload
    except ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except JWTError:
        raise HTTPException(status_code=403, detail="Invalid token")

import os

PRODUCT_SERVICE_URL = os.environ.get("PRODUCT_SERVICE_URL", "http://localhost:8000/products")

@router.post("/orders")
def create_order(
    user_id: int = Query(...),
    product_id: int = Query(...),
    quantity: int = Query(...),
    db: Session = Depends(get_db),
    token: HTTPAuthorizationCredentials = Security(security)
):
    
    headers = {
        "Authorization": f"Bearer {token.credentials}"
    }
    # Fetch product info
    product_resp = requests.get(f"{PRODUCT_SERVICE_URL}/{product_id}",headers=headers)
    if product_resp.status_code != 200:
        raise HTTPException(status_code=404, detail="Product not found")

    product = product_resp.json()
    if product['stock'] < quantity:
        raise HTTPException(status_code=400, detail="Not enough stock")

    # Update product stock
    updated_stock = product['stock'] - quantity
    update_resp = requests.put(
        f"{PRODUCT_SERVICE_URL}/{product_id}",
        json={"name": product['name'], "price": product['price'], "stock": updated_stock},headers=headers
        
    )
    if update_resp.status_code not in (200, 202):
        raise HTTPException(status_code=500, detail="Failed to update stock")

    # Create order
    new_order = Order(user_id=user_id, product_id=product_id, quantity=quantity)
    db.add(new_order)
    db.commit()
    db.refresh(new_order)

    return {"message": "Order created", "order_id": new_order.id}

@router.post("/cart")
def add_to_cart(
    user_id: int = Form(...),
    product_id: int = Form(...),
    quantity: int = Form(...),
    db: Session = Depends(get_db)
):
    cart_item = CartItem(user_id=user_id, product_id=product_id, quantity=quantity)
    db.add(cart_item)
    db.commit()
    db.refresh(cart_item)
    
    return {
        "message": "Item added to cart successfully",
        "cart_item": {
            "id": cart_item.id,
            "user_id": cart_item.user_id,
            "product_id": cart_item.product_id,
            "quantity": cart_item.quantity
        }
    }


@router.get("/cart/json")
def get_cart_items(user_id: int, db: Session = Depends(get_db)):
    cart_items = db.query(CartItem).filter(CartItem.user_id == user_id).all()
    return JSONResponse(content=[
        {
            "id": item.id,
            "product_id": item.product_id,
            "quantity": item.quantity
        } for item in cart_items
    ])

@router.post("/cart/checkout")
def checkout_cart(
    user_id: int = Form(...),
    db: Session = Depends(get_db)
):
    items = db.query(CartItem).filter(CartItem.user_id == user_id).all()
    if not items:
        return {"message": "Cart is empty"}

    order_ids = []
    for item in items:
        order = Order(user_id=item.user_id, product_id=item.product_id, quantity=item.quantity)
        db.add(order)
        db.commit()
        order_ids.append(order.id)

    db.query(CartItem).filter(CartItem.user_id == user_id).delete()
    db.commit()
    return {"message": "Checkout complete", "order_ids": order_ids}

@router.post("/cart/remove")
def remove_item(
    cart_item_id: int = Form(...),
    user_id: int = Form(...),
    db: Session = Depends(get_db)
):
    db.query(CartItem).filter(CartItem.id == cart_item_id).delete()
    db.commit()
    return RedirectResponse(url=f"/cart?user_id={user_id}", status_code=HTTP_302_FOUND)