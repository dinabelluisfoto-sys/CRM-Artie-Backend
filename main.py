import os
import asyncio
import httpx
from fastapi import FastAPI, Depends, HTTPException, Request, BackgroundTasks, UploadFile, File
from fastapi.responses import PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from typing import List
import re 
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from database import engine, get_db
import models, schemas
import shutil

# Asegúrate de tener una carpeta estática para almacenar temporalmente los pre-diseños
os.makedirs("static/uploads", exist_ok=True)

# 1. DECLARACIÓN ÚNICA MAESTRA DE LA APP
app = FastAPI(title="API CRM Artie", description="Motor de gestión de pedidos con WhatsApp", version="1.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Permite que tu index.html local lea los datos de Railway
    allow_credentials=True,
    allow_methods=["*"],  # Permite GET, POST, etc.
    allow_headers=["*"],
)

# --- CONFIGURACIÓN DE ARCHIVOS ESTÁTICOS PARA LAS IMÁGENES ---
if not os.path.exists("static"):
    os.makedirs("static")
app.mount("/static", StaticFiles(directory="static"), name="static")

# Asegurarnos de que las tablas existan
models.Base.metadata.create_all(bind=engine)

# 🛠️ PARCHE PARA ACTUALIZAR LA BASE DE DATOS
@app.on_event("startup")
def actualizar_base_datos():
    from sqlalchemy import text
    try:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE clientes ADD COLUMN esta_fijado BOOLEAN DEFAULT FALSE;"))
            conn.execute(text("ALTER TABLE clientes ADD COLUMN esta_eliminado BOOLEAN DEFAULT FALSE;"))
            print("✅ Base de datos actualizada con nuevas columnas.", flush=True)
    except Exception as e:
        print("ℹ️ Las columnas ya existen (todo en orden).", flush=True)

# --- CLASES AUXILIARES ---
class MensajeEnvio(BaseModel):
    texto: str
class ActualizarNombre(BaseModel):
    nombre: str


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
        
    envio = 47.00
    
    if cantidad < 12:
        precio_unitario = 25.00
        subtotal = cantidad * precio_unitario
    elif cantidad == 12:
        precio_unitario = 23.33
        subtotal = 280.00
    elif 13 <= cantidad < 24:
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

@app.put("/api/cliente/{cliente_id}/nombre")
def guardar_nombre_manual(cliente_id: int, datos: ActualizarNombre, db: Session = Depends(get_db)):
    cliente = db.query(models.Cliente).filter(models.Cliente.id == cliente_id).first()
    if cliente:
        cliente.nombre = datos.nombre
        db.commit()
        return {"status": "ok", "nuevo_nombre": cliente.nombre}
    raise HTTPException(status_code=404, detail="Cliente no encontrado")

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


# --- RUTA DEL DASHBOARD DE CHATS ---
@app.get("/api/dashboard/")
def obtener_dashboard_chats(db: Session = Depends(get_db)):
    clientes = db.query(models.Cliente).filter(models.Cliente.esta_eliminado == False).all()
    
    resultado_chats = []
    for c in clientes:
        ultimo_msg = db.query(models.Mensaje).filter(models.Mensaje.cliente_id == c.id).order_by(models.Mensaje.id.desc()).first()
        
        texto_preview = "Sin mensajes aún"
        fecha_orden = c.id
        
        if ultimo_msg:
            if "media_id" in ultimo_msg.contenido.lower() or "http" in ultimo_msg.contenido.lower():
                texto_preview = "📷 Imagen adjunta"
            else:
                texto_preview = ultimo_msg.contenido
            fecha_orden = ultimo_msg.id
            
        pedido_reciente = db.query(models.Pedido).filter(models.Pedido.cliente_id == c.id).order_by(models.Pedido.id.desc()).first()
        total_q = pedido_reciente.total_quetzales if pedido_reciente else 0.0
        cantidad_gorras = pedido_reciente.cantidad if pedido_reciente else 0
        
        resultado_chats.append({
            "cliente_id": c.id,
            # Si tiene nombre real úsalo, de lo contrario muestra el número limpio
            "cliente_nombre": c.nombre if c.nombre and c.nombre.lower() != "pendiente" else f"+{c.telefono}", 
            "telefono": c.telefono,
            "bot_activo": c.bot_activo,
            "estatus": c.paso_embudo.upper(),
            "ultimo_mensaje": texto_preview,
            "total_q": f"{total_q:,.2f}",
            "cantidad": cantidad_gorras,
            "esta_fijado": c.esta_fijado,
            "orden_id": fecha_orden
        })
        
    resultado_chats.sort(key=lambda x: (x["esta_fijado"], x["orden_id"]), reverse=True)
    return resultado_chats

# --- RUTA PARA ENCENDER/APAGAR A ARTIE ---
# --- RUTA PARA ENCENDER/APAGAR A ARTIE Y REINICIAR EMBÚDO ---
@app.post("/api/toggle_bot/{telefono}")
def toggle_bot(telefono: str, db: Session = Depends(get_db)):
    cliente = db.query(models.Cliente).filter(models.Cliente.telefono == telefono).first()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    
    # Invertimos el estado (Si estaba apagado, se enciende)
    cliente.bot_activo = not cliente.bot_activo
    
    # 🔥 LA MAGIA DEL RESET: Si el dueño vuelve a ENCENDER a Artie, 
    # asumimos que el pedido anterior ya se entregó y preparamos al bot para un NUEVO PEDIDO.
    if cliente.bot_activo:
        cliente.paso_embudo = "inicio"
        cliente.cantidad = None # <-- ESTA ES LA CLAVE: Borramos las "500 gorras" de la base de datos
        
    db.commit()
    
    estado_nuevo = "ON (Memoria reiniciada)" if cliente.bot_activo else "OFF"
    return {"mensaje": f"Artie ahora está {estado_nuevo} para el número {telefono}"}

# --- RUTA PARA LEER EL HISTORIAL DEL CHAT EN EL FRONTEND ---
@app.get("/api/mensajes/{telefono}")
def obtener_mensajes_chat(telefono: str, db: Session = Depends(get_db)):
    cliente = db.query(models.Cliente).filter(models.Cliente.telefono == telefono).first()
    if not cliente:
        return []
    
    mensajes = db.query(models.Mensaje).filter(models.Mensaje.cliente_id == cliente.id).order_by(models.Mensaje.id.asc()).all()
    
    resultados = []
    for msg in mensajes:
        resultados.append({
            "id": msg.id,
            "remitente": msg.remitente,
            "tipo_mensaje": msg.tipo_mensaje,
            "contenido": msg.contenido,
            "fecha_envio": msg.fecha_envio.isoformat() if msg.fecha_envio else None
        })
    return resultados


# --- RUTAS DE ACCIONES DEL MENÚ (3 PUNTITOS) ---
@app.post("/api/chat/{cliente_id}/fijar")
def toggle_fijar_chat(cliente_id: int, db: Session = Depends(get_db)):
    cliente = db.query(models.Cliente).filter(models.Cliente.id == cliente_id).first()
    if cliente:
        cliente.esta_fijado = not cliente.esta_fijado
        db.commit()
    return {"status": "ok"}

@app.post("/api/chat/{cliente_id}/eliminar")
def ocultar_chat(cliente_id: int, db: Session = Depends(get_db)):
    cliente = db.query(models.Cliente).filter(models.Cliente.id == cliente_id).first()
    if cliente:
        cliente.esta_eliminado = True
        db.commit()
    return {"status": "ok"}


# --- RUTAS DE ENVÍO HUMANO DE MENSAJES Y MEDIOS ---
@app.post("/api/enviar_mensaje/{cliente_id}")
async def enviar_mensaje_manual(cliente_id: int, mensaje: MensajeEnvio, db: Session = Depends(get_db)):
    cliente = db.query(models.Cliente).filter(models.Cliente.id == cliente_id).first()
    if not cliente:
        return {"status": "error"}
    
    await enviar_mensaje_whatsapp(cliente.telefono, mensaje.texto)
    
    msg_humano = models.Mensaje(cliente_id=cliente.id, remitente="humano", tipo_mensaje="texto", contenido=mensaje.texto)
    db.add(msg_humano)
    db.commit()
    return {"status": "ok"}

@app.post("/api/enviar_imagen_humano/{cliente_id}")
async def enviar_imagen_manual(cliente_id: int, file: UploadFile = File(...), db: Session = Depends(get_db)):
    cliente = db.query(models.Cliente).filter(models.Cliente.id == cliente_id).first()
    if not cliente:
        return {"status": "error", "message": "Cliente no encontrado"}
    
    ruta_archivo = f"static/uploads/{cliente.id}_{file.filename}"
    with open(ruta_archivo, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    url_publica_imagen = f"https://crm-artie-backend-production.up.railway.app/{ruta_archivo}"
    
    await enviar_imagen_whatsapp(cliente.telefono, url_publica_imagen)
    
    msg_humano = models.Mensaje(
        cliente_id=cliente.id, 
        remitente="humano", 
        tipo_mensaje="imagen", 
        contenido=url_publica_imagen
    )
    db.add(msg_humano)
    db.commit()
    
    return {"status": "ok", "url": url_publica_imagen}

# --- MOTOR PARA DESCARGAR IMÁGENES DESDE META ---
async def descargar_media_whatsapp(media_id: str) -> str:
    token = os.getenv("WHATSAPP_TOKEN")
    
    headers = {
        "Authorization": f"Bearer {token}"
    }
    
    async with httpx.AsyncClient() as client:
        try:
            # 1. Le pedimos a Meta la URL de descarga secreta de ese Media ID
            url_meta = f"https://graph.facebook.com/v17.0/{media_id}"
            response = await client.get(url_meta, headers=headers)
            
            if response.status_code == 200:
                datos_media = response.json()
                url_descarga = datos_media.get("url")
                
                # 2. Con la URL secreta, descargamos la imagen real (los bytes)
                archivo_response = await client.get(url_descarga, headers=headers)
                
                if archivo_response.status_code == 200:
                    # Guardamos la imagen con su ID como nombre en tu carpeta de Railway
                    nombre_archivo = f"static/uploads/client_logo_{media_id}.jpg"
                    with open(nombre_archivo, "wb") as f:
                        f.write(archivo_response.content)
                    
                    # Retornamos el link público definitivo para tu CRM
                    return f"https://crm-artie-backend-production.up.railway.app/{nombre_archivo}"
            
            print(f"Error al obtener URL de Meta para ID {media_id}: {response.text}", flush=True)
            return None
        except Exception as e:
            print(f"Excepción al descargar media de WhatsApp: {e}", flush=True)
            return None


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
    
    async def procesar_flujo():
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
                    media_id = mensaje_info.get("image", {}).get("id")
                    print(f"📷 Detectado Media ID de Meta: {media_id}. Iniciando descarga...", flush=True)
                    
                    # Llamamos al motor que acabamos de crear
                    url_descargada = await descargar_media_whatsapp(media_id)
                    
                    if url_descargada:
                        # Reemplazamos el texto crudo por la URL real para que el historial lo pinte como foto
                        texto_cliente = url_descargada
                        print(f"✅ Logo descargado y guardado en: {url_descargada}", flush=True)
                    else:
                        texto_cliente = f"[Error al descargar Logo ID: {media_id}]"
                
                cliente = db.query(models.Cliente).filter(models.Cliente.telefono == numero_cliente).first()
                
                if not cliente:
                    cliente = models.Cliente(
                        nombre="Pendiente", 
                        telefono=numero_cliente, 
                        nit="CF", 
                        bot_activo=True, 
                        paso_embudo="inicio",
                        esta_fijado=False,
                        esta_eliminado=False
                    )
                    db.add(cliente)
                    db.commit()
                    db.refresh(cliente)
                else:
                    if cliente.esta_eliminado:
                        cliente.esta_eliminado = False
                        db.commit()

                msg_cliente = models.Mensaje(
                    cliente_id=cliente.id, 
                    remitente="cliente", 
                    tipo_mensaje="texto" if tipo_mensaje == "text" else "imagen", 
                    contenido=texto_cliente
                )
                db.add(msg_cliente)
                db.commit()

                # --- MOTOR DE RESPUESTA INTERNO ---
                async def responder_bot(texto_respuesta: str, imagen_url: str = None):
                    if imagen_url:
                        await enviar_imagen_whatsapp(numero_cliente, imagen_url)
                        msg_img = models.Mensaje(cliente_id=cliente.id, remitente="bot", tipo_mensaje="imagen", contenido=imagen_url)
                        db.add(msg_img)
                        db.commit()
                        await asyncio.sleep(3)
                        
                    await enviar_mensaje_whatsapp(numero_cliente, texto_respuesta)
                    msg_bot = models.Mensaje(cliente_id=cliente.id, remitente="bot", tipo_mensaje="texto", contenido=texto_respuesta)
                    db.add(msg_bot)
                    db.commit()

                # --- ESCUDO DE INTERVENCIÓN HUMANA ---
                # Si el pedido ya se confirmó, bloqueamos al bot por completo
                if cliente.paso_embudo == "completado":
                    cliente.bot_activo = False
                    db.commit()
                    return # Cortamos la ejecución aquí. El bot se queda mudo.    

                palabras_reinicio = ["hola", "menu", "menú", "cancelar", "reiniciar", "salir"]
                if texto_cliente in palabras_reinicio:
                    cliente.bot_activo = True  
                    cliente.paso_embudo = "inicio"
                    db.commit()
                    
                if not cliente.bot_activo:
                    print(f"🤫 Artie en silencio para el número +502 {numero_cliente}.", flush=True)
                    return 
                    
                # --- EMBUDO DE VENTAS UNIFICADO ---
                if cliente.paso_embudo == "inicio":
                    respuesta = "¡Hola! 👋 Bienvenido a La Sanjuanerita. Soy Artie, tu asistente virtual.\n\n¿Listo para destacar tu marca?\n1️⃣ Iniciar mi Pedido\n2️⃣ Ver Precios y Ofertas\n\n*(Responde con el número)*"
                    await responder_bot(respuesta)
                    cliente.paso_embudo = "esperando_opcion"
                    db.commit()
                    
                elif cliente.paso_embudo == "esperando_opcion":
                    if texto_cliente == "1" or texto_cliente == "2":
                        respuesta = "¡Excelente decisión! ✨ Para que elijas la mejor opción, aquí tienes nuestra escala de precios:\n\n"
                        respuesta += "📌 *Escala por volumen:*\n"
                        respuesta += "📦 *1 Docena (12)*: Q.280 en total\n"
                        respuesta += "📦 *24 a 299 gorras*: Q.17.99 c/u\n"
                        respuesta += "📦 *300 a 499 gorras*: Q.16.00 c/u\n"
                        respuesta += "📦 *500+ gorras*: Q.15.00 c/u\n\n"
                        respuesta += "💡 **¿Cuántas gorras tienes en mente para tu pedido?**\n"
                        respuesta += "*(Responde directamente con la cantidad, ej: 60, 100, 500...)*"
                        
                        link_precios = "https://crm-artie-backend-production.up.railway.app/static/precios.jpg"
                        await responder_bot(respuesta, imagen_url=link_precios)
                        
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
                        
                        pedido_existente = db.query(models.Pedido).filter(models.Pedido.cliente_id == cliente.id, models.Pedido.estatus == "EN PROCESO").first()
                        if pedido_existente:
                            pedido_existente.cantidad = cantidad
                            pedido_existente.total_quetzales = total
                        else:
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
                    cliente.paso_embudo = "pidiendo_logo"
                    db.commit()
                    color_elegido = texto_cliente.title()
                    respuesta = f"¡El {color_elegido} es una gran elección! ✨\n\nAhora, la parte más importante: *Tu Marca.*\n👉 *Envía la FOTO de tu LOGO aquí.*\n\n*(Con esto haremos un \"Pre-diseño Digital\" para que apruebes cómo se ve antes de fabricar).*"
                    await responder_bot(respuesta)
                    
                elif cliente.paso_embudo == "pidiendo_logo":
                    if tipo_mensaje == "image" or "[media_id" in texto_cliente:
                        respuesta = "✅ **¡Logo Recibido!**\nYa está con nuestro equipo de diseño. 👨‍🎨\n\nPara formalizar tu orden: **¿A nombre de quién la registramos?** 👤"
                        await responder_bot(respuesta)
                        cliente.paso_embudo = "pidiendo_nombre"
                        db.commit()
                    else:
                        respuesta = "Aún no detecto la imagen 🤔. Por favor, envíame la foto de tu logo."
                        await responder_bot(respuesta)
                        
                elif cliente.paso_embudo == "pidiendo_nombre":
                    nombre_pedido = texto_cliente.title()
                    
                    # 🔥 ESCUDO DE IDENTIDAD: Solo guardamos el nombre si el contacto es "Pendiente" o no tiene nombre.
                    # Si el dueño ya lo guardó manualmente en la agenda, respetamos el nombre del dueño.
                    if not cliente.nombre or cliente.nombre.lower() == "pendiente":
                        cliente.nombre = nombre_pedido
                        
                    respuesta = f"Un gusto, {nombre_pedido}. 🤝\n📞 **¿A qué número de teléfono te podemos llamar para confirmar el diseño?**"
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
                        respuesta = "Por favor, escribe un número de teléfono válido de **8 dígitos**."
                        await responder_bot(respuesta)
                    
                elif cliente.paso_embudo == "pidiendo_nit":
                    cliente.nit = texto_cliente.upper()
                    
                    # 🧠 Psicología de ventas: Sentido de pertenencia y seguridad
                    respuesta = "¡Excelente! 📝\nPara asegurar que tu pedido llegue directo a tus manos y sin contratiempos, **¿cuál es la dirección exacta donde deseas recibir esta entrega especial?** 🚚📍\n*(Por favor, incluye referencias o municipio)*"
                    await responder_bot(respuesta)
                    
                    cliente.paso_embudo = "pidiendo_direccion"
                    db.commit()
                    
                elif cliente.paso_embudo == "pidiendo_direccion":
                    # El cliente ya dio su dirección (queda guardada en el historial del chat)
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
            print(f"Error unificando flujo en background: {e}", flush=True)
        finally:
            db.close()

    background_tasks.add_task(procesar_flujo)
    return {"status": "ok"}

# --- MOTOR DE ENVÍO DE MENSAJES DE TEXTO ---
async def enviar_mensaje_whatsapp(numero_destino: str, texto: str):
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
        print(f"Fallo de conexión al enviar imagen: {img_err}", flush=True)