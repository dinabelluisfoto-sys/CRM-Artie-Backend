import os
import httpx
from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session
from typing import List

from database import engine, get_db
import models, schemas

# Asegurarnos de que las tablas existan
models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="API CRM Artie", description="Motor de gestión de pedidos con WhatsApp", version="1.2.0")

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
    
    # Cálculo del total
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

# --- RUTA WEBHOOK (Para WhatsApp) ---

# --- RUTA WEBHOOK (Para WhatsApp) - MODO DEBUG ---

@app.get("/webhook")
async def verificar_webhook(request: Request):
    # 1. Obtener el token de las variables de entorno
    token_servidor = os.getenv("VERIFY_TOKEN")
    
    # 2. Obtener lo que envía Meta
    mode = request.query_params.get("hub.mode")
    token_meta = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")

    # 3. Imprimir en los logs de Railway para que tú puedas ver qué pasa
    print(f"DEBUG: Meta envió modo: {mode}")
    print(f"DEBUG: Meta envió token: {token_meta}")
    print(f"DEBUG: Token guardado en Railway: {token_servidor}")

    # 4. Verificación
    if mode == "subscribe" and token_meta == token_servidor:
        print("DEBUG: ¡ÉXITO! Los tokens coinciden.")
        return PlainTextResponse(content=challenge, status_code=200)
    
    print("DEBUG: ¡ERROR! Los tokens NO coinciden o el modo es incorrecto.")
    raise HTTPException(status_code=403, detail="Token de verificación inválido")

@app.post("/webhook")
async def recibir_mensajes(request: Request):
    data = await request.json()
    print("=== NUEVO EVENTO DE WHATSAPP ===")
    
    try:
        # 1. Navegar por el JSON para extraer los datos vitales
        entry = data.get("entry", [])[0]
        changes = entry.get("changes", [])[0]
        value = changes.get("value", {})
        
        # 2. Verificar si es un mensaje de texto (y no una confirmación de lectura)
        if "messages" in value:
            mensaje_info = value["messages"][0]
            numero_cliente = mensaje_info["from"]
            texto_cliente = mensaje_info["text"]["body"]
            
            print(f"✅ Mensaje recibido de {numero_cliente}: {texto_cliente}")
            
            # 3. Enviar respuesta automática a ese mismo número
            respuesta = "¡Hola! Soy Artie 🤖. Mi creador Allan me acaba de encender. ¡Pronto estaré procesando tus pedidos para la lavandería!"
            await enviar_mensaje_whatsapp(numero_cliente, respuesta)
            
    except Exception as e:
        print(f"Error procesando el mensaje o es un evento distinto: {e}")
        
    # Siempre debemos responder 200 OK a Meta rápido para que no nos bloquee
    return {"status": "ok"}

# --- MOTOR DE ENVÍO DE MENSAJES ---
async def enviar_mensaje_whatsapp(numero_destino: str, texto: str):
    token = os.getenv("WHATSAPP_TOKEN")
    phone_id = os.getenv("PHONE_NUMBER_ID")
    
    # URL oficial de la API de Meta (Usando v25.0 como en tu panel)
    url = f"https://graph.facebook.com/v25.0/{phone_id}/messages"
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "messaging_product": "whatsapp",
        "to": numero_destino,
        "type": "text",
        "text": {"body": texto}
    }
    
    # Usamos httpx para hacer la petición web a los servidores de Meta
    async with httpx.AsyncClient() as client:
        response = await client.post(url, headers=headers, json=payload)
        print(f"Estado de envío a Meta: {response.status_code}")
        if response.status_code != 200:
            print("Error detallado de Meta:", response.json())