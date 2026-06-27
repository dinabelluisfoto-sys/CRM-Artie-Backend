import os
import asyncio
import httpx
from fastapi import FastAPI, Depends, HTTPException, Request, BackgroundTasks
from fastapi.responses import PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware  # <-- IMPORTANTE: Control de accesos web
from sqlalchemy.orm import Session
from typing import List
import re 
from fastapi.staticfiles import StaticFiles

from database import engine, get_db
import models, schemas

# Asegurarnos de que las tablas existan
models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="API CRM Artie", description="Motor de gestión de pedidos con WhatsApp", version="1.2.0")

# =====================================================================
# --- PUENTE DE PERMISOS (CORS) PARA EL FRONTEND DE ALSYS ---
# =====================================================================
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Permite que tu index.html local lea los datos de Railway
    allow_credentials=True,
    allow_methods=["*"],  # Permite GET, POST, etc.
    allow_headers=["*"],
)
# --- CONFIGURACIÓN DE ARCHIVOS ESTÁTICOS PARA LAS IMÁGENES ---
# Esto creará una carpeta automática en tu servidor para tus catálogos
if not os.path.exists("static"):
    os.makedirs("static")
app.mount("/static", StaticFiles(directory="static"), name="static")


# --- MOTOR DE CÁLCULO DE LA SANJUANERITA ---
def procesar_pedido_gorras(texto_usuario: str):
    texto = texto_usuario.lower()
    cantidad = 0
    
    numeros_en_texto = re.findall(r'\d+', texto)
    num_base = int(numeros_en_texto[0]) if numeros_en_texto else 1
    
    if "docena" in texto:
        cantidad = num_base * 12
    elif "ciento" in texto or "cien" in texto:
        cantidad = num_base * 100
    elif numeros_en_texto:
        cantidad = int(numeros_en_texto[0])
    else:
        return None 
        
    # --- LÓGICA DE PRECIOS EXACTA AL CLIENTE ---
    envio = 47.00
    
    if cantidad < 12:
        precio_unitario = 25.00
        subtotal = cantidad * precio_unitario
    elif cantidad == 12:
        # Precio cerrado por docena exacta
        precio_unitario = 23.33
        subtotal = 280.00
    elif 13 <= cantidad < 24:
        # Por si piden por ejemplo 15 o 18 gorras, se mantiene la tasa de la docena
        precio_unitario = 23.33
        subtotal = cantidad * precio_unitario
    elif 24 <= cantidad < 300:
        precio_unitario = 17.99
        subtotal = cantidad * precio_unitario
    elif 300 <= cantidad < 500:
        precio_unitario = 16.00
        subtotal = cantidad * precio_unitario
    else: 
        precio_unitario = 15.00
        subtotal = cantidad * precio_unitario
        
    subtotal = round(subtotal, 2)
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

# --- RUTA PARA EL DASHBOARD ---
@app.get("/api/dashboard/")
def obtener_datos_dashboard(db: Session = Depends(get_db)):
    pedidos = db.query(models.Pedido, models.Cliente).join(models.Cliente, models.Pedido.cliente_id == models.Cliente.id).order_by(models.Pedido.id.desc()).all()
    
    resultados = []
    for pedido, cliente in pedidos:
        resultados.append({
            "pedido_id": pedido.id,
            "fecha": pedido.fecha_pedido.strftime("%Y-%m-%d %H:%M") if pedido.fecha_pedido else "N/A", 
            "cliente_nombre": cliente.nombre,
            "telefono": cliente.telefono,
            "nit": cliente.nit,
            "cantidad": pedido.cantidad,
            "total_q": float(pedido.total_quetzales),
            "estatus": pedido.estatus,
            "bot_activo": cliente.bot_activo
        })
    return resultados

# --- RUTA PARA ENCENDER/APAGAR A ARTIE ---
@app.post("/api/toggle_bot/{telefono}")
def toggle_bot(telefono: str, db: Session = Depends(get_db)):
    cliente = db.query(models.Cliente).filter(models.Cliente.telefono == telefono).first()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    
    cliente.bot_activo = not cliente.bot_activo
    db.commit()
    
    estado_nuevo = "ON" if cliente.bot_activo else "OFF"
    return {"mensaje": f"Artie ahora está {estado_nuevo} para el número {telefono}"}

# --- RUTA WEBHOOK (Para WhatsApp) ---

@app.get("/webhook")
async def verificar_webhook(request: Request):
    token_servidor = os.getenv("VERIFY_TOKEN")
    
    mode = request.query_params.get("hub.mode")
    token_meta = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")

    if mode == "subscribe" and token_meta == token_servidor:
        return PlainTextResponse(content=challenge, status_code=200)
    
    raise HTTPException(status_code=403, detail="Token de verificación inválido")

@app.post("/webhook")
async def recibir_mensajes(request: Request, background_tasks: BackgroundTasks):
    data = await request.json()
    
    # Esta función hará todo el trabajo pesado en segundo plano sin hacer esperar a Meta
    async def procesar_flujo():
        # Creamos una conexión a la base de datos exclusiva para esta tarea
        db = next(get_db()) 
        try:
            entry = data.get("entry", [])[0]
            changes = entry.get("changes", [])[0]
            value = changes.get("value", {})
            
            if "messages" in value:
                mensaje_info = value["messages"][0]
                numero_cliente = mensaje_info["from"]
                tipo_mensaje = mensaje_info.get("type")
                
                texto_cliente = ""
                if tipo_mensaje == "text":
                    texto_cliente = mensaje_info.get("text", {}).get("body", "").strip().lower()
                elif tipo_mensaje == "image":
                    texto_cliente = "[imagen adjunta]"
                
                cliente = db.query(models.Cliente).filter(models.Cliente.telefono == numero_cliente).first()
                
                if not cliente:
                    cliente = models.Cliente(nombre="Pendiente", telefono=numero_cliente, nit="CF", bot_activo=True, paso_embudo="inicio")
                    db.add(cliente)
                    db.commit()
                    db.refresh(cliente)

                msg_cliente = models.Mensaje(cliente_id=cliente.id, remitente="cliente", tipo_mensaje="texto" if tipo_mensaje == "text" else "imagen", contenido=texto_cliente)
                db.add(msg_cliente)
                db.commit()

                # --- MOTOR DE RESPUESTA INTERNO ---
                # --- MOTOR DE RESPUESTA INTERNO ---
                async def responder_bot(texto_respuesta: str, imagen_url: str = None):
                    # 1. Enviar primero la imagen (si existe)
                    if imagen_url:
                        await enviar_imagen_whatsapp(numero_cliente, imagen_url)
                        msg_img = models.Mensaje(cliente_id=cliente.id, remitente="bot", tipo_mensaje="imagen", contenido=imagen_url)
                        db.add(msg_img)
                        db.commit()
                        
                        # 🔥 Aumentamos la pausa a 3 segundos para imágenes pesadas
                        await asyncio.sleep(3)
                        
                    # 2. Enviar después el texto
                    await enviar_mensaje_whatsapp(numero_cliente, texto_respuesta)
                    msg_bot = models.Mensaje(cliente_id=cliente.id, remitente="bot", tipo_mensaje="texto", contenido=texto_respuesta)
                    db.add(msg_bot)
                    db.commit()

                palabras_reinicio = ["hola", "menu", "menú", "cancelar", "reiniciar", "salir"]
                if texto_cliente in palabras_reinicio:
                    cliente.bot_activo = True  
                    cliente.paso_embudo = "inicio"
                    db.commit()
                    
                if cliente.bot_activo == False:
                    print(f"🤫 Artie en silencio. Mensaje de {numero_cliente} para el agente humano.", flush=True)
                    return 
                    
                # --- EMBUDO DE VENTAS ---
                if cliente.paso_embudo == "inicio":
                    respuesta = "¡Hola! 👋 Bienvenido a La Sanjuanerita. Soy Artie, tu asistente virtual.\n\n¿Listo para destacar tu marca?\n1️⃣ Iniciar mi Pedido\n2️⃣ Ver Precios y Ofertas\n\n*(Responde con el número)*"
                    await responder_bot(respuesta)
                    cliente.paso_embudo = "esperando_opcion"
                    db.commit()
                    
                elif cliente.paso_embudo == "esperando_opcion":
                    if texto_cliente == "1":
                        # OPCIÓN 1: Va directo a pedir, pero le mostramos los precios primero
                        respuesta = "¡Excelente decisión! ✨ Para que elijas la mejor opción, aquí tienes nuestra escala de precios:\n\n"
                        respuesta += "📌 *Escala por volumen:*\n"
                        respuesta += "📦 *1 Docena (12)*: Q.280 en total\n"
                        respuesta += "📦 *24 a 299 gorras*: Q.17.99 c/u\n"
                        respuesta += "📦 *300 a 499 gorras*: Q.16.00 c/u\n"
                        respuesta += "📦 *500+ gorras*: Q.15.00 c/u\n\n"
                        respuesta += "💡 **¿Cuántas gorras tienes en mente para tu pedido?**\n"
                        respuesta += "*(Ej: 1 Docena, 50 unidades, 1 Ciento...)*"
                        
                        link_precios = "https://crm-artie-backend-production.up.railway.app/static/precios.jpg"
                        await responder_bot(respuesta, imagen_url=link_precios)
                        
                        cliente.paso_embudo = "pidiendo_cantidad"
                        db.commit()
                        
                    elif texto_cliente == "2":
                        # OPCIÓN 2: Quería ver precios. Se los mostramos y lo invitamos a pedir de una vez.
                        respuesta = "☝️ *Aquí tienes nuestra lista oficial de precios mayoristas.*\n\n"
                        respuesta += "📌 *Escala por volumen:*\n"
                        respuesta += "📦 *1 Docena (12)*: Q.280 en total\n"
                        respuesta += "📦 *24 a 299 gorras*: Q.17.99 c/u\n"
                        respuesta += "📦 *300 a 499 gorras*: Q.16.00 c/u\n"
                        respuesta += "📦 *500+ gorras*: Q.15.00 c/u\n\n"
                        respuesta += "💡 **¿Cuántas gorras te gustaría pedir?**\n"
                        respuesta += "*(Responde directamente con la cantidad. Ej: 50, 1 Docena, 1 Ciento...)*"
                        
                        link_precios = "https://crm-artie-backend-production.up.railway.app/static/precios.jpg"
                        await responder_bot(respuesta, imagen_url=link_precios)
                        
                        # Magia UX: Avanzamos el embudo también aquí para ahorrarle un paso al cliente
                        cliente.paso_embudo = "pidiendo_cantidad"
                        db.commit()
                        
                    else:
                        respuesta = "Por favor, responde únicamente con el número 1 o 2 para continuar."
                        await responder_bot(respuesta)
                        
                elif cliente.paso_embudo == "pidiendo_cantidad":
                    calculo = procesar_pedido_gorras(texto_cliente)
                    if calculo:
                        cantidad, subtotal, envio, total = calculo
                        str_subtotal = f"{subtotal:,.2f}"
                        str_total = f"{total:,.2f}"
                        
                        nuevo_pedido = models.Pedido(cliente_id=cliente.id, cantidad=cantidad, total_quetzales=total, estatus="EN PROCESO", link_logo="n/a")
                        db.add(nuevo_pedido)
                        
                        respuesta = f"Entendido: **{cantidad} Gorras** 🧢\n"
                        respuesta += f"💰 *Tu Inversión: Q. {str_total} (Subtotal: Q.{str_subtotal} + Q.47 envío)*\n\n"
                        respuesta += "Ahora, dale personalidad. Mira el catálogo de arriba ☝️ y elige:\n\n"
                        respuesta += "🤍 *Neutros:* Blanco, Negro, Gris Claro, Gris Oscuro.\n"
                        respuesta += "💙 *Azules:* Marino, Rey, Celeste.\n"
                        respuesta += "🌈 *Vivos:* Rosa, Amarillo Mango, Verde Oscuro, Morado.\n"
                        respuesta += "🌸 *Pastel:* Rosa Millenial.\n\n"
                        respuesta += "👉 **¿Cuál es tu color favorito?** *(Escríbelo aquí abajo)*"
                        
                        link_catalogo = "https://crm-artie-backend-production.up.railway.app/static/colores.jpg"
                        await responder_bot(respuesta, imagen_url=link_catalogo)
                        
                        cliente.paso_embudo = "pidiendo_color"
                        db.commit()
                    else:
                        respuesta = "No logré entender la cantidad 😅. Por favor, escríbela con números (ej: 60, o 1 docena)."
                        await responder_bot(respuesta)

                elif cliente.paso_embudo == "pidiendo_color":
                    color_elegido = texto_cliente.title()
                    respuesta = f"¡El {color_elegido} es una gran elección! ✨\n\n"
                    respuesta += "Ahora, la parte más importante: *Tu Marca.*\n"
                    respuesta += "👉 *Envía la FOTO de tu LOGO aquí.*\n\n"
                    respuesta += "*(Con esto haremos un \"Pre-diseño Digital\" para que apruebes cómo se ve antes de fabricar).*"
                    await responder_bot(respuesta)
                    cliente.paso_embudo = "pidiendo_logo"
                    db.commit()
                    
                elif cliente.paso_embudo == "pidiendo_logo":
                    if tipo_mensaje == "image" or texto_cliente == "[imagen adjunta]":
                        respuesta = "✅ **¡Logo Recibido!**\nYa está con nuestro equipo de diseño. 👨‍🎨\n\nPara formalizar tu orden: **¿A nombre de quién la registramos?** 👤"
                        await responder_bot(respuesta)
                        cliente.paso_embudo = "pidiendo_nombre"
                        db.commit()
                    else:
                        respuesta = "Aún no detecto la imagen 🤔. Por favor, usa el ícono del clip 📎 o cámara para enviarme la foto de tu logo."
                        await responder_bot(respuesta)
                        
                elif cliente.paso_embudo == "pidiendo_nombre":
                    cliente.nombre = texto_cliente.title()
                    respuesta = f"Un gusto, {cliente.nombre}. 🤝\n📞 **¿A qué número de teléfono te podemos llamar para confirmar el diseño?**"
                    await responder_bot(respuesta)
                    cliente.paso_embudo = "pidiendo_telefono"
                    db.commit()
                    
                elif cliente.paso_embudo == "pidiendo_telefono":
                    numero_limpio = re.sub(r'\D', '', texto_cliente)
                    if len(numero_limpio) == 8:
                        respuesta = "Anotado. 📝\nPor último: **¿Cuál es tu NIT para la factura?**\n*(Escribe CF si no tienes)*"
                        await responder_bot(respuesta)
                        cliente.paso_embudo = "pidiendo_nit"
                        db.commit()
                    else:
                        respuesta = "Ese número no parece tener la cantidad correcta 🤔.\n\nPor favor, escribe un número de teléfono válido de **8 dígitos** para que no haya problemas con tu entrega."
                        await responder_bot(respuesta)
                    
                elif cliente.paso_embudo == "pidiendo_nit":
                    cliente.nit = texto_cliente.upper()
                    cliente.bot_activo = False
                    cliente.paso_embudo = "completado"
                    
                    pedido_actual = db.query(models.Pedido).filter(models.Pedido.cliente_id == cliente.id).order_by(models.Pedido.id.desc()).first()
                    if pedido_actual:
                        pedido_actual.estatus = "NUEVO"
                        
                    db.commit()
                    
                    respuesta = "🎉 **¡Pedido Confirmado Exitosamente!**\n\n"
                    respuesta += "📦 *Estado:* Orden registrada y enviada a mesa de diseño.\n"
                    respuesta += "💳 *Método de Pago:* Contra-entrega.\n\n"
                    respuesta += "⏳ *Siguiente paso:* En breve te enviaremos el **\"Pre-diseño Digital\"** a este chat para tu aprobación.\n\n"
                    respuesta += "¡Gracias por confiar en *La Sanjuanerita*! 🧢"
                    await responder_bot(respuesta)
                    
        except Exception as e:
            print(f"Error procesando el webhook en background: {e}", flush=True)
        finally:
            db.close() # Cerramos la sesión de base de datos de forma segura

    # 🔥 LA MAGIA: Le pasamos la tarea al servidor para que la haga en background
    background_tasks.add_task(procesar_flujo)
    
    # Y le respondemos a Meta INMEDIATAMENTE para que no duplique el mensaje
    return {"status": "ok"}

# --- MOTOR DE ENVÍO DE MENSAJES DE TEXTO ---
# --- MOTOR DE ENVÍO DE MENSAJES DE TEXTO ---
async def enviar_mensaje_whatsapp(numero_destino: str, texto: str):
    token = os.getenv("WHATSAPP_TOKEN")
    phone_id = os.getenv("PHONE_NUMBER_ID")
    
    # Usamos la v17.0 que es la más estable a nivel global para mensajería directa
    url = f"https://graph.facebook.com/v17.0/{phone_id}/messages"
    
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
        if response.status_code != 200:
            print("Error detallado de Meta (Texto):", response.text, flush=True)

# --- MOTOR DE ENVÍO DE IMÁGENES BLINDADO ---
async def enviar_imagen_whatsapp(numero_destino: str, link_imagen: str, caption: str = ""):
    token = os.getenv("WHATSAPP_TOKEN")
    phone_id = os.getenv("PHONE_NUMBER_ID")
    
    url = f"https://graph.facebook.com/v17.0/{phone_id}/messages"
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "messaging_product": "whatsapp",
        "to": numero_destino,
        "type": "image",
        "image": {
            "link": link_imagen
        }
    }
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, headers=headers, json=payload, timeout=5.0)
            if response.status_code != 200:
                print("Meta rechazó la imagen pero el flujo continúa:", response.text, flush=True)
    except Exception as img_err:
        # Si el servidor de imágenes falla o hay timeout, la app no se congela
        print(f"Fallo de conexión al enviar imagen: {img_err}", flush=True)