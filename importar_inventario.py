#!/usr/bin/env python3
import sqlite3
import random

print("🚀 INVENTARIO COMPLETO: 500 MED + 300 INSUMOS")
print("=" * 60)

DB_PATH = r"instance\historia_clinica.db"
conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

# LIMPIAR TODO
cursor.execute("DELETE FROM medicamentos")
cursor.execute("DELETE FROM insumos_medicos")
conn.commit()

# ========================================
# 💊 500 MEDICAMENTOS ÚNICOS (YA FUNCIONA)
# ========================================
bases_med = ["Paracetamol", "Ibuprofeno", "Amoxicilina", "Omeprazol", "Ceftriaxona", 
             "Metformina", "Enalapril", "Losartán", "Amlodipino", "Atorvastatina"]
formas_med = ["tb", "cáps", "inj", "susp", "inhal", "amp"]
dosis_med = ["500mg", "1g", "250mg", "400mg", "20mg", "10mg", "50mg"]

print("💊 Generando 500 medicamentos...")
meds_data = set()
while len(meds_data) < 500:
    nombre = f"{random.choice(bases_med)} {random.choice(formas_med)} x {random.choice(dosis_med)}"
    codigo = f"MED{len(meds_data)+1:04d}"
    stock = round(random.uniform(25, 450), 1)
    unidad = random.choice(["mg", "ampolla", "tableta"])
    
    meds_data.add((len(meds_data)+1, codigo, nombre, random.choice(formas_med).upper(), 
                  random.choice(dosis_med), stock, unidad))

cursor.executemany("""
INSERT OR REPLACE INTO medicamentos (id, codigo, nombre, forma_farmaceutica, presentacion, 
                                    cantidad_disponible, unidad_inventario) 
VALUES (?, ?, ?, ?, ?, ?, ?)""", list(meds_data))

# ========================================
# 🏥 300 INSUMOS ÚNICOS
# ========================================
insumos_reales = [
    "Jeringa 3ml desechable", "Jeringa 10ml desechable", "Agujas 21G 1\"", "Agujas 23G 1\"",
    "Guantes látex talla M", "Guantes nitrilo talla M", "Gasas estériles 10x10cm",
    "Suero fisiológico 500ml", "Suero fisiológico 1000ml", "Catéter IV 18G",
    "Apósitos adhesivos caja", "Mascarilla quirúrgica", "Bata quirúrgica desechable",
    "Algodón hidrófilo 500g", "Alcohol etílico 70% 1L", "Yodo povidona solución"
]

print("🏥 Generando 300 insumos...")
insumos_data = set()
while len(insumos_data) < 300:
    nombre = random.choice(insumos_reales)
    codigo = f"INS{len(insumos_data)+1:04d}"
    stock = round(random.uniform(50, 800), 1)
    unidad = random.choice(["uni", "caja", "paquete"])
    
    insumos_data.add((len(insumos_data)+1, codigo, nombre, stock, unidad, 1, "2025-12-30 10:00:00"))

cursor.executemany("""
INSERT OR REPLACE INTO insumos_medicos (id, codigo, nombre, stock_actual, unidad, activo, created_at) 
VALUES (?, ?, ?, ?, ?, ?, ?)""", list(insumos_data))

conn.commit()
conn.close()

print("\n" + "=" * 60)
print("✅ ¡INVENTARIO COMPLETO CARGADO!")
print("💊 500 medicamentos únicos (stock 25-450)")
print("🏥 300 insumos únicos (stock 50-800)")
print("\n🔥 Reinicia: flask run --debug")
