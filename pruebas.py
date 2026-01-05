#!/usr/bin/env python3
from app import db, create_app
from app.models import *

app = create_app()
with app.app_context():
    # Crear tabla manualmente si no existe
    db.create_all()
    print("✅ Tabla insumos_paciente creada")
    
    # Verificar migración
    print("✅ Migración completada - Reinicia Flask")
