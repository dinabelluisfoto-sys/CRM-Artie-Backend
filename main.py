import os
import httpx
from fastapi import FastAPI, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from database import engine, get_db
import models, schemas
from typing import List

# Asegurarnos de que las tablas existan
models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="API CRM Artie", description="Motor de gestión de pedidos con WhatsApp", version="1.2.0")

# --- CONFIGURACIÓN ---
VERIFY_TOKEN = "artie_secret_token_12345" # Cámbialo por algo único

# --- RUTAS DE CRM (Clientes y Pedidos) ---

@app.get("/")
def ruta_raiz():
    return {"mensaje": "Motor CRM Artie activo y monitoreando."}

@app.post("/clientes/", response_model=schemas.ClienteResponse)
def crear_cliente(cliente: schemas.ClienteCreate, db: Session = Depends(get_db)):
    cliente_existente = db.query(models.Cliente).filter(models.Cliente.telefono == cliente.telefono).first()
    if cliente_existente:
        return cliente_existente
    nuevo_cliente = models.Cliente(nombre=cliente.nombre, telefono=cliente.telefono, nit=cliente.nit)
    db.add(nuevo_cliente)
    db.commit()
    db.refresh(nuevo_cliente)
    return nuevo_cliente

@app.post("/pedidos/", response_model=schemas.PedidoResponse)
def crear_pedido(pedido: schemas.PedidoCreate, db: Session = Depends(get_db)):
    cliente = db.query(models.Cliente).filter(models.Cliente.id == pedido.cliente_id).first()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente no encontrado.")
    total = (pedido.cantidad * 17.99) + 47.00
    nuevo_pedido = models.Pedido(
        cliente_id=pedido.cliente_id,
        cantidad=pedido.cantidad,
        total_quetzales=total,
        estatus="NUEVO",
        link_logo=pedido.link_logo
    )
    db.add(nuevo_pedido)
    db.commit()
    db.refresh(nuevo_pedido)
    return nuevo_pedido

@app.get("/pedidos/", response_model=List[schemas.PedidoResponse])
def listar_pedidos(db: Session = Depends(get_db)):
    return db.query(models.Pedido).all()

# --- RUTA WEBHOOK (Para WhatsApp) ---

@app.get("/webhook/")
async def verify_webhook(request: Request):
    query_params = request.query_params
    if query_params.get("hub.mode") == "subscribe" and query_params.get("hub.verify_token") == VERIFY_TOKEN:
        return int(query_params.get("hub.challenge"))
    raise HTTPException(status_code=403, detail="Token de verificación inválido")

@app.post("/webhook/")
async def handle_webhook(request: Request):
    data = await request.json()
    # Aquí imprimirás los mensajes que lleguen de WhatsApp
    print(data) 
    return {"status": "ok"}