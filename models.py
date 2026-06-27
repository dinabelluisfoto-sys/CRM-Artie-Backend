from sqlalchemy import Column, Integer, String, Numeric, DateTime, ForeignKey, Boolean, Text
from sqlalchemy.sql import func
from database import Base

class Cliente(Base):
    __tablename__ = "clientes"
    
    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String, nullable=False)
    telefono = Column(String, unique=True, index=True, nullable=False)
    nit = Column(String, default="CF")
    bot_activo = Column(Boolean, default=True) 
    paso_embudo = Column(String, default="inicio") 
    # 🔥 NUEVOS CAMPOS PARA PASO 2 (MENÚ DE CONTEXTO)
    esta_fijado = Column(Boolean, default=False)
    esta_eliminado = Column(Boolean, default=False)  # Borrado lógico para ocultar

class Producto(Base):
    __tablename__ = "productos"
    
    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String, nullable=False)
    precio_unidad = Column(Numeric(10, 2), nullable=False)

class Pedido(Base):
    __tablename__ = "pedidos"
    
    id = Column(Integer, primary_key=True, index=True)
    cliente_id = Column(Integer, ForeignKey("clientes.id"))
    fecha_pedido = Column(DateTime(timezone=True), server_default=func.now())
    cantidad = Column(Integer, nullable=False)
    total_quetzales = Column(Numeric(10, 2), nullable=False)
    estatus = Column(String, default="NUEVO")
    link_logo = Column(String, nullable=True)

# --- NUEVA TABLA: LA MEMORIA DEL CHAT TIPO WHATSAPP ---
class Mensaje(Base):
    __tablename__ = "mensajes"
    
    id = Column(Integer, primary_key=True, index=True)
    cliente_id = Column(Integer, ForeignKey("clientes.id"))
    remitente = Column(String, nullable=False) # Guardará: 'cliente', 'bot' o 'humano'
    tipo_mensaje = Column(String, default="texto") # Guardará: 'texto' o 'imagen'
    contenido = Column(Text, nullable=False) # Guardará el mensaje o el link de la foto
    fecha_envio = Column(DateTime(timezone=True), server_default=func.now())