#!/usr/bin/env python3
from sqlalchemy import create_engine, text
import sqlite3

print("🏗️  CREANDO TABLAS DE INVENTARIO...")

# Conexión directa SQLite (SIN SQLAlchemy)
conn = sqlite3.connect('instance/historiaclinica.db')
cursor = conn.cursor()

# Crear tabla MEDICAMENTOS
cursor.execute("""
CREATE TABLE IF NOT EXISTS medicamentos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    codigo VARCHAR(50) UNIQUE NOT NULL,
    nombre VARCHAR(255) NOT NULL,
    forma_farmaceutica VARCHAR(100),
    presentacion VARCHAR(100),
    cantidad_disponible DECIMAL(12,3) DEFAULT 0,
    unidad_inventario VARCHAR(50)
)
""")

# Crear tabla INSUMOS MÉDICOS
cursor.execute("""
CREATE TABLE IF NOT EXISTS insumos_medicos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    codigo VARCHAR(50) UNIQUE NOT NULL,
    nombre VARCHAR(255) NOT NULL,
    stock_actual DECIMAL(12,3) DEFAULT 0,
    unidad VARCHAR(50) DEFAULT 'uni',
    activo BOOLEAN DEFAULT 1,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
)
""")

conn.commit()
conn.close()

print("✅ Tablas creadas: medicamentos, insumos_medicos")
print("🔄 Ahora puedes importar los CSV")
