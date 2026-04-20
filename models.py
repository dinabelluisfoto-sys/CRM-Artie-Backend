from sqlalchemy import Column, Integer, String, Numeric, DateTime, ForeignKey, Boolean
from sqlalchemy.sql import func
from database import Base

class Cliente(Base):
    __tablename__ = "clientes"
    
    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String, nullable=False)
    telefono = Column(String, unique=True, index=True, nullable=False)
    nit = Column(String, default="CF")
    # --- NUEVOS CAMPOS PARA ARTIE ---
    bot_activo = Column(Boolean, default=True) # El Switch ON/OFF
    paso_embudo = Column(String, default="inicio") # Memoria de la plática

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