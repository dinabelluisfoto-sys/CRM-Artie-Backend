import os
import httpx
from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session
from typing import List
import re # Para extraer números del texto

from database import engine, get_db
import models, schemas

# Asegurarnos de que las tablas existan
models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="API CRM Artie", description="Motor de gestión de pedidos con WhatsApp", version="1.2.0")

# --- MOTOR DE CÁLCULO DE LA SANJUANERITA ---
def procesar_pedido_gorras(texto_usuario: str):
    texto = texto_usuario.lower()
    cantidad = 0
    
    # 1. TRADUCTOR DE TEXTO A NÚMERO
    numeros_en_texto = re.findall(r'\d+', texto)
    num_base = int(numeros_en_texto[0]) if numeros_en_texto else 1
    
    if "docena" in texto:
        cantidad = num_base * 12
    elif "ciento" in texto or "cien" in texto:
        cantidad = num_base * 100
    elif numeros_en_texto:
        cantidad = int(numeros_en_texto[0])
    else:
        return None # No se entendió la cantidad
        
    # 2. REGLAS DE NEGOCIO (PRECIOS DE 2026)
    if cantidad < 12:
        precio_unitario = 25.00 # Precio sugerido al menudeo
    elif 12 <= cantidad < 24:
        precio_unitario = 280.00 / 12 # Proporcional a Q.280 la docena
    elif 24 <= cantidad < 300:
        precio_unitario = 17.99
    elif 300 <= cantidad < 500:
        precio_unitario = 16.00
    else: # 500 o más
        precio_unitario = 15.00
        
    subtotal = round(cantidad * precio_unitario, 2)
    envio = 47.00
    total = round(subtotal + envio, 2)
    
    return cantidad, subtotal, envio, total

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

# --- RUTA WEBHOOK (Para WhatsApp) - MODO DEBUG ---

@app.get("/webhook")
async def verificar_webhook(request: Request):
    # 1. Obtener el token de las variables de entorno
    token_servidor = os.getenv("VERIFY_TOKEN")
    
    # 2. Obtener lo que envía Meta
    mode = request.query_params.get("hub.mode")
    token_meta = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")

    # 3. Imprimir en los logs de Railway
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
async def recibir_mensajes(request: Request, db: Session = Depends(get_db)):
    data = await request.json()
    
    try:
        entry = data.get("entry", [])[0]
        changes = entry.get("changes", [])[0]
        value = changes.get("value", {})
        
        # Si recibimos un mensaje válido
        if "messages" in value:
            mensaje_info = value["messages"][0]
            numero_cliente = mensaje_info["from"]
            
            # Extraemos el texto (si mandan imagen u otra cosa, evitamos que truene)
            texto_cliente = mensaje_info.get("text", {}).get("body", "").strip().lower()
            
            # 1. Buscar a este número en nuestra base de datos
            cliente = db.query(models.Cliente).filter(models.Cliente.telefono == numero_cliente).first()
            
            # 2. Si no existe, es un lead nuevo, lo guardamos
            if not cliente:
                cliente = models.Cliente(
                    nombre="Pendiente", 
                    telefono=numero_cliente, 
                    nit="CF", 
                    bot_activo=True, 
                    paso_embudo="inicio"
                )
                db.add(cliente)
                db.commit()
                db.refresh(cliente)
                
            # 3. EL BOTÓN DE PÁNICO (Fase 2 de tu estrategia)
            if cliente.bot_activo == False:
                print(f"🤫 Artie en silencio. El cliente {numero_cliente} está en manos de un humano.")
                return {"status": "ok"}
            # --- NUEVO: PALABRAS CLAVE DE REINICIO ---
            palabras_reinicio = ["hola", "menu", "menú", "cancelar", "reiniciar", "salir"]
            if texto_cliente in palabras_reinicio:
                cliente.paso_embudo = "inicio"
                db.commit()
                # Al cambiarlo a "inicio", el código seguirá hacia abajo y mostrará el menú principal
                
            # 4. EL EMBUDO DE VENTAS (Fase 1)
            if cliente.paso_embudo == "inicio":
                respuesta = "¡Hola! 👋 Bienvenido a La Sanjuanerita. Soy Artie, tu asistente virtual.\n\n¿Listo para destacar tu marca?\n1️⃣ Iniciar mi Pedido\n2️⃣ Ver Precios y Ofertas\n\n*(Responde con el número)*"
                await enviar_mensaje_whatsapp(numero_cliente, respuesta)
                
                cliente.paso_embudo = "esperando_opcion"
                db.commit()
                
            elif cliente.paso_embudo == "esperando_opcion":
                if texto_cliente == "1":
                    respuesta = "¡Excelente decisión! ✨\n\nPara calcular tu mejor precio, **¿cuántas gorras tienes en mente?**\n*(Ej: 1 Docena, 50 unidades, 1 Ciento...)*"
                    await enviar_mensaje_whatsapp(numero_cliente, respuesta)
                    
                    cliente.paso_embudo = "pidiendo_cantidad"
                    db.commit()
                elif texto_cliente == "2":
                    respuesta = "Actualmente manejamos Gorras Trucker desde Q.17.99 c/u (precio mayorista). ¿Deseas iniciar tu pedido respondiendo '1'?"
                    await enviar_mensaje_whatsapp(numero_cliente, respuesta)
                else:
                    respuesta = "Por favor, responde únicamente con el número 1 o 2 para continuar."
                    await enviar_mensaje_whatsapp(numero_cliente, respuesta)
                    
            elif cliente.paso_embudo == "pidiendo_cantidad":
                calculo = procesar_pedido_gorras(texto_cliente)
                
                if calculo:
                    cantidad, subtotal, envio, total = calculo
                    
                    # Formateamos los números para que se vean bonitos
                    str_subtotal = f"{subtotal:,.2f}"
                    str_total = f"{total:,.2f}"
                    
                    respuesta = f"Entendido: **{cantidad} Gorras** 🧢\n"
                    respuesta += f"💰 *Tu Inversión: Q. {str_total} (Subtotal: Q.{str_subtotal} + Q.47 envío)*\n\n"
                    respuesta += "Ahora, dale personalidad. Mira el catálogo 👆 y elige:\n\n"
                    respuesta += "🤍 *Neutros:* Blanco, Negro, Gris Claro, Gris Oscuro.\n"
                    respuesta += "💙 *Azules:* Marino, Rey, Celeste.\n"
                    respuesta += "🌈 *Vivos:* Rosa, Amarillo Mango, Verde Oscuro, Morado.\n"
                    respuesta += "🌸 *Pastel:* Rosa Millenial.\n\n"
                    respuesta += "**¿Cuál es tu color favorito?** (Escríbelo abajo)"
                    
                    await enviar_mensaje_whatsapp(numero_cliente, respuesta)
                    
                    cliente.paso_embudo = "pidiendo_color"
                    db.commit()
                else:
                    respuesta = "No logré entender la cantidad 😅. Por favor, escríbela con números (ej: 60, o 1 docena)."
                    await enviar_mensaje_whatsapp(numero_cliente, respuesta)
            
    except Exception as e:
        print(f"Error procesando el webhook: {e}")
        
    return {"status": "ok"}


# --- MOTOR DE ENVÍO DE MENSAJES ---
async def enviar_mensaje_whatsapp(numero_destino: str, texto: str):
    token = os.getenv("WHATSAPP_TOKEN")
    phone_id = os.getenv("PHONE_NUMBER_ID")
    
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
    
    async with httpx.AsyncClient() as client:
        response = await client.post(url, headers=headers, json=payload)
        print(f"Estado de envío a Meta: {response.status_code}")
        if response.status_code != 200:
            print("Error detallado de Meta:", response.json())