import os
import asyncio
import httpx
import json
from fastapi import FastAPI, Depends, HTTPException, Request, BackgroundTasks, UploadFile, File, WebSocket, WebSocketDisconnect
from fastapi.responses import PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from typing import List, Optional
import re 
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from database import engine, get_db
import models, schemas
import shutil

os.makedirs("static/uploads", exist_ok=True)

app = FastAPI(title="API CRM Artie", description="Motor de gestión de pedidos con WhatsApp", version="1.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if not os.path.exists("static"):
    os.makedirs("static")
app.mount("/static", StaticFiles(directory="static"), name="static")

models.Base.metadata.create_all(bind=engine)

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

class MensajeEnvio(BaseModel):
    texto: str
class ActualizarNombre(BaseModel):
    nombre: str
class ContactoSchema(BaseModel):
    nombre: str
    telefono: str
class LoginRequest(BaseModel):
    username: str
    password: str    

class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: str):
        for connection in self.active_connections[:]:
            try:
                await connection.send_text(message)
            except Exception:
                if connection in self.active_connections:
                    self.active_connections.remove(connection)

manager = ConnectionManager()

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)    

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
    elif 13 <= cantidad <= 23:
        precio_unitario = 23.50
        subtotal = cantidad * precio_unitario
    elif 24 <= cantidad <= 99:
        precio_unitario = 18.00
        subtotal = cantidad * precio_unitario
    elif 100 <= cantidad <= 199:
        precio_unitario = 17.00
        subtotal = cantidad * precio_unitario
    elif 200 <= cantidad <= 499:
        precio_unitario = 16.00
        subtotal = cantidad * precio_unitario
    else: 
        precio_unitario = 15.00
        subtotal = cantidad * precio_unitario
        
    subtotal = round(subtotal, 2)
    total = round(subtotal + envio, 2)
    
    return cantidad, subtotal, envio, total


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

@app.post("/api/login")
def login_sistema(credenciales: LoginRequest):
    if credenciales.username == "dinabelluisfoto@gmail.com" and credenciales.password == "admin1234":
        return {"access_token": "token_maestro_alsys_gorraprint"}
    raise HTTPException(status_code=401, detail="Credenciales incorrectas")

@app.post("/api/contactos/guardar")
def guardar_contacto_agenda(datos: ContactoSchema, id: Optional[str] = None, db: Session = Depends(get_db)):
    telefono_db = datos.telefono.replace(" ", "").replace("+", "")
    
    if id and id.replace("nuevo_", "").isdigit(): 
        cliente = db.query(models.Cliente).filter(models.Cliente.id == int(id)).first()
        if cliente:
            cliente.nombre = datos.nombre
            cliente.telefono = telefono_db
            db.commit()
            return {"status": "ok", "message": "Contacto actualizado correctamente"}
            
    cliente_existente = db.query(models.Cliente).filter(models.Cliente.telefono == telefono_db).first()
    
    if cliente_existente:
        cliente_existente.nombre = datos.nombre
        cliente_existente.esta_eliminado = False
        db.commit()
        return {"status": "ok", "message": "Contacto recuperado y actualizado"}
    else:
        nuevo_cliente = models.Cliente(
            nombre=datos.nombre,
            telefono=telefono_db,
            nit="CF",
            bot_activo=False, 
            paso_embudo="inicio",
            esta_fijado=False,
            esta_eliminado=False
        )
        db.add(nuevo_cliente)
        db.commit()
        return {"status": "ok", "message": "Contacto nuevo creado"}

@app.delete("/api/contactos/eliminar/{cliente_id}")
def eliminar_contacto_agenda(cliente_id: int, db: Session = Depends(get_db)):
    cliente = db.query(models.Cliente).filter(models.Cliente.id == cliente_id).first()
    if cliente:
        cliente.esta_eliminado = True
        db.commit()
        return {"status": "ok"}
    raise HTTPException(status_code=404, detail="Cliente no encontrado")

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


@app.get("/api/dashboard/")
def obtener_dashboard_chats(db: Session = Depends(get_db)):
    clientes = db.query(models.Cliente).filter(models.Cliente.esta_eliminado == False).all()
    
    resultado_chats = []
    for c in clientes:
        ultimo_msg = db.query(models.Mensaje).filter(models.Mensaje.cliente_id == c.id, models.Mensaje.remitente != "sistema").order_by(models.Mensaje.id.desc()).first()
        
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

@app.post("/api/toggle_bot/{telefono}")
def toggle_bot(telefono: str, db: Session = Depends(get_db)):
    cliente = db.query(models.Cliente).filter(models.Cliente.telefono == telefono).first()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    
    cliente.bot_activo = not cliente.bot_activo
    
    if cliente.bot_activo:
        cliente.paso_embudo = "inicio"
        
    db.commit()
    
    estado_nuevo = "ON (Memoria IA reiniciada)" if cliente.bot_activo else "OFF"
    return {"mensaje": f"Artie ahora está {estado_nuevo} para el número {telefono}"}

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

async def descargar_media_whatsapp(media_id: str) -> str:
    token = os.getenv("WHATSAPP_TOKEN")
    headers = {"Authorization": f"Bearer {token}"}
    
    async with httpx.AsyncClient() as client:
        try:
            url_meta = f"https://graph.facebook.com/v17.0/{media_id}"
            response = await client.get(url_meta, headers=headers)
            
            if response.status_code == 200:
                datos_media = response.json()
                url_descarga = datos_media.get("url")
                
                archivo_response = await client.get(url_descarga, headers=headers)
                
                if archivo_response.status_code == 200:
                    nombre_archivo = f"static/uploads/client_logo_{media_id}.jpg"
                    with open(nombre_archivo, "wb") as f:
                        f.write(archivo_response.content)
                    
                    return f"https://crm-artie-backend-production.up.railway.app/{nombre_archivo}"
            
            print(f"Error al obtener URL de Meta para ID {media_id}: {response.text}", flush=True)
            return None
        except Exception as e:
            print(f"Excepción al descargar media de WhatsApp: {e}", flush=True)
            return None

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
                    url_descargada = await descargar_media_whatsapp(media_id)
                    
                    if url_descargada:
                        texto_cliente = url_descargada
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
                        cliente.nombre = "Pendiente"
                        cliente.bot_activo = True
                        cliente.paso_embudo = "inicio"
                        db.query(models.Mensaje).filter(models.Mensaje.cliente_id == cliente.id).delete()
                        db.commit()

                msg_cliente = models.Mensaje(
                    cliente_id=cliente.id, 
                    remitente="cliente", 
                    tipo_mensaje="texto" if tipo_mensaje == "text" else "imagen", 
                    contenido=texto_cliente
                )
                db.add(msg_cliente)
                db.commit()

                await manager.broadcast("nuevo_mensaje_recibido")

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

                if cliente.paso_embudo == "completado":
                    cliente.bot_activo = False
                    db.commit()
                    return 

                palabras_reinicio = ["hola", "menu", "menú", "cancelar", "reiniciar", "salir"]
                if texto_cliente in palabras_reinicio:
                    cliente.bot_activo = True  
                    cliente.paso_embudo = "inicio"
                    db.commit()
                    
                if not cliente.bot_activo:
                    return 
                    
                # ==========================================================
                # CEREBRO GEMINI IA ALSYS (NUEVA CONEXIÓN REST API PURA)
                # ==========================================================
                try:
                    # 1. Recuperar contexto histórico
                    historial_db = db.query(models.Mensaje).filter(
                        models.Mensaje.cliente_id == cliente.id
                    ).order_by(models.Mensaje.id.desc()).limit(15).all()
                    historial_db.reverse()

                    contexto = ""
                    for msg in historial_db:
                        rol = "Cliente" if msg.remitente == "cliente" else "Artie"
                        if "http" in msg.contenido and msg.remitente == "cliente":
                            texto = "[Imagen/Logo adjunto por el cliente]"
                        elif "http" in msg.contenido and msg.remitente == "bot":
                            texto = "[Catálogo visual enviado por Artie]"
                        else:
                            texto = msg.contenido
                        contexto += f"{rol}: {texto}\n"

                    prompt = f"""
                    Eres Artie, el vendedor estrella de Gorra Print (Guatemala). Eres amable, humano, súper rápido para responder y usas emojis.
                    Tu objetivo es cerrar ventas de gorras trucker personalizadas.

                    PRECIOS Y CANTIDADES (OBLIGATORIO):
                    - 1 a 11 gorras: Q.25.00 c/u
                    - 1 Docena (12 gorras): Q.280.00 total
                    - 13 a 23 gorras: Q.23.50 c/u
                    - 24 a 99 gorras: Q.18.00 c/u
                    - 100 a 199 gorras: Q.17.00 c/u
                    - 200 a 499 gorras: Q.16.00 c/u
                    - 500+ gorras: Q.15.00 c/u

                    ENVÍO: Siempre cobra Q.47.00 adicionales. Pago contra-entrega.
                    COLORES: Negro, Gris Oscuro, Gris Claro, Blanco, Café, Marino, Azul Rey, Celeste, Verde, Pistache, Rojo, Corinto, Mango, Morado, Rosa Millenial, Fucsia.

                    REGLAS ESTRICTAS DE ALSYS:
                    1. NUNCA inventes precios. Calcula los totales multiplicando la cantidad por el precio unitario y súmale los Q.47 de envío.
                    2. Responde SIEMPRE de forma conversacional, sin menús numéricos (olvida el presiona 1 o 2). Si el cliente dice "quiero 50 gorras rojas", tú respondes calculando el total y pidiendo el siguiente dato.
                    3. Proceso para cerrar venta: Debes recolectar Cantidad, Color, pedir que te envíen la foto del Logo, pedir Nombre, Teléfono (OBLIGATORIO que sean exactamente 8 dígitos, si el cliente envía más o menos dígitos, dile amablemente que en Guatemala el número debe ser de 8 dígitos y vuelve a pedirlo), NIT y Dirección de envío. Pídelos uno por uno conversando, no todos de golpe.
                    4. Si el historial dice "[Imagen/Logo adjunto por el cliente]", agradécele por el logo y continúa con la venta. No te confundas con los catálogos que tú mismo envías.
                    
                    CONTROL DE IMÁGENES ALSYS (REGLA DE ORO):
                    - Si el cliente te pide precios por primera vez, DEBES escribir al final exacto de tu mensaje la etiqueta: [ENVIAR_PRECIOS]. ¡NO LO REPITAS si ya se lo enviaste antes!
                    - Si el cliente te pide ver colores por primera vez, DEBES escribir al final exacto de tu mensaje la etiqueta: [ENVIAR_COLORES]. ¡NO LO REPITAS si ya se lo enviaste antes!
                    
                    5. GATILLO SECRETO: Cuando el cliente ya te haya dado TODOS los datos finales para su pedido (Cantidad, Color, Logo, Nombre, Teléfono, NIT y Dirección), dale un resumen final de su compra, infórmale expresamente que "en un breve momento un asesor humano le enviará su pre-diseño digital para su aprobación" y despídete amablemente. Al FINAL EXACTO de tu mensaje pon esta estructura estricta separada por el símbolo | :
                    [ORDEN_COMPLETA]|cantidad_en_numeros|total_a_pagar_en_numeros|NIT_del_cliente|direccion_del_cliente
                    Ejemplo exacto: [ORDEN_COMPLETA]|100|1747.00|CF|Quetzaltenango

                    HISTORIAL DE CONVERSACIÓN ACTUAL:
                    {contexto}

                    Escribe la respuesta de Artie para el cliente basándote en el último mensaje del historial:
                    """

                    # 2. Conexión Directa REST API (Bypass completo de la librería vieja)
                    gemini_api_key = os.getenv("GEMINI_API_KEY")
                    gemini_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={gemini_api_key}"
                    
                    payload_ia = {
                        "contents": [{"parts": [{"text": prompt}]}],
                        "safetySettings": [
                            {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
                            {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
                            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
                            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"}
                        ]
                    }
                    
                    async with httpx.AsyncClient() as client_ia:
                        res_ia = await client_ia.post(gemini_url, json=payload_ia, timeout=30.0)
                        if res_ia.status_code == 200:
                            data_ia = res_ia.json()
                            respuesta_ia = data_ia["candidates"][0]["content"]["parts"][0]["text"].strip()
                        else:
                            raise Exception(f"API Gemini REST falló: {res_ia.text}")

                    # Limpieza por si la IA agrega su nombre al inicio
                    if respuesta_ia.startswith("Artie:"):
                        respuesta_ia = respuesta_ia.replace("Artie:", "").strip()
                        
                    # ---- DETECCIÓN DE IMÁGENES ALSYS ----
                    url_adjunta = None
                    if "[ENVIAR_PRECIOS]" in respuesta_ia:
                        url_adjunta = "https://crm-artie-backend-production.up.railway.app/static/precios.jpg"
                        respuesta_ia = respuesta_ia.replace("[ENVIAR_PRECIOS]", "").strip()
                    
                    if "[ENVIAR_COLORES]" in respuesta_ia:
                        url_adjunta = "https://crm-artie-backend-production.up.railway.app/static/colores.jpg"
                        respuesta_ia = respuesta_ia.replace("[ENVIAR_COLORES]", "").strip()

                    # 4. Evaluación del Gatillo Secreto y Extracción de Datos
                    if "[ORDEN_COMPLETA]" in respuesta_ia:
                        
                        partes = respuesta_ia.split("[ORDEN_COMPLETA]")
                        mensaje_despedida = partes[0].strip()
                        datos_ocultos = partes[1].strip() if len(partes) > 1 else ""
                        
                        cantidad_final = "Ver chat"
                        total_final = "Ver chat"
                        nit_final = "Validar en chat"
                        direccion_final = "Validar en chat"
                        
                        if "|" in datos_ocultos:
                            detalles = datos_ocultos.split("|")
                            if len(detalles) >= 5:
                                cantidad_final = detalles[1].strip()
                                total_final = detalles[2].strip()
                                nit_final = detalles[3].strip()
                                direccion_final = detalles[4].strip()

                        await responder_bot(mensaje_despedida, imagen_url=url_adjunta)

                        # Apagar bot y enviar ficha al CRM
                        cliente.bot_activo = False
                        cliente.paso_embudo = "completado"
                        db.commit()
                        
                        # Buscar el último logo enviado por el cliente para adjuntarlo a la ficha
                        ultimo_logo = db.query(models.Mensaje).filter(
                            models.Mensaje.cliente_id == cliente.id,
                            models.Mensaje.remitente == "cliente",
                            models.Mensaje.tipo_mensaje == "imagen"
                        ).order_by(models.Mensaje.id.desc()).first()
                        url_del_logo = ultimo_logo.contenido if ultimo_logo else "n/a"

                        datos_ficha = {
                            "tipo": "ficha_produccion",
                            "cliente": cliente.nombre if cliente.nombre != "Pendiente" else cliente.telefono,
                            "telefono": cliente.telefono,
                            "nit": nit_final,
                            "direccion": direccion_final,
                            "cantidad": cantidad_final,
                            "total": f"Q. {total_final}",
                            "logo_url": url_del_logo
                        }
                        
                        msg_sistema = models.Mensaje(cliente_id=cliente.id, remitente="sistema", tipo_mensaje="ficha", contenido=json.dumps(datos_ficha))
                        db.add(msg_sistema)
                        db.commit()
                        await manager.broadcast("nuevo_mensaje_recibido")

                    else:
                        await responder_bot(respuesta_ia, imagen_url=url_adjunta)

                except Exception as e_ia:
                    print(f"Error crítico en IA Gemini: {e_ia}", flush=True)
                    await responder_bot("En este momento nuestro sistema está procesando un alto volumen de solicitudes. Por favor, permíteme un momento mientras uno de nuestros asesores toma este chat para brindarte atención personalizada. 🤝")
                # ==========================================================
                    
        except Exception as e:
            print(f"Error unificando flujo en background: {e}", flush=True)
        finally:
            db.close()
            await manager.broadcast("nuevo_mensaje_recibido")

    background_tasks.add_task(procesar_flujo)
    return {"status": "ok"}

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