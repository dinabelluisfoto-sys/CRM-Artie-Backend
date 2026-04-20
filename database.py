import os
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv

# 1. Obtenemos la ruta exacta de la carpeta actual
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 2. Forzamos la carga del archivo .env que está en esta misma carpeta
load_dotenv(os.path.join(BASE_DIR, ".env"))

# 3. Obtenemos la URL
DATABASE_URL = os.getenv("DATABASE_URL")

# 4. Validación de seguridad (Para que nos avise si el archivo sigue vacío)
if not DATABASE_URL:
    raise ValueError("¡ERROR CRITICO! No se encontró DATABASE_URL. Revisa tu archivo .env")

# Creamos el motor de conexión
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()