from pydantic import BaseModel
from typing import Optional

# --- ESQUEMAS PARA CLIENTES ---
class ClienteBase(BaseModel):
    nombre: str
    telefono: str
    nit: Optional[str] = "CF"

class ClienteCreate(ClienteBase):
    pass

class ClienteResponse(ClienteBase):
    id: int

    class Config:
        from_attributes = True


# --- ESQUEMAS PARA PEDIDOS ---
class PedidoBase(BaseModel):
    cliente_id: int
    cantidad: int
    link_logo: Optional[str] = None

class PedidoCreate(PedidoBase):
    pass

class PedidoResponse(PedidoBase):
    id: int
    total_quetzales: float
    estatus: str
    
    class Config:
        from_attributes = True