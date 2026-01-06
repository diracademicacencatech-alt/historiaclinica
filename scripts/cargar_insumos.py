#!/usr/bin/env python3
import sqlite3
import csv

print("🏥 ACTUALIZANDO SOLO INSUMOS DESDE CSV (sin tocar created_at)")
print("=" * 60)

DB_PATH = r"instance\historia_clinica.db"
CSV_PATH = r"C:\Users\HASISTENCIAL93\Documents\JF HELMER\SOFTWARE HC\historiaclinica\insumo_medicos.csv"

conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

print("🧹 Borrando insumos_medicos existentes...")
cursor.execute("DELETE FROM insumos_medicos")
conn.commit()

print(f"📥 Leyendo CSV: {CSV_PATH}")
with open(CSV_PATH, newline='', encoding='latin-1') as f:
    reader = csv.DictReader(f, delimiter=';')  # ; si tu CSV viene así
    print("Encabezados detectados:", reader.fieldnames)

    # localizar columna id aunque lleve espacios/BOM
    id_key = None
    for k in reader.fieldnames:
        if k.strip().lower() == "id":
            id_key = k
            break
    if not id_key:
        raise RuntimeError("No se encontró columna 'id' en el CSV")

    rows = []
    for row in reader:
        rows.append((
            int(row[id_key]),
            row["codigo"],
            row["nombre"],
            float(row.get("stock_actual", 0) or 0),
            row.get("unidad", ""),
            int(row.get("activo", 1) or 1),
        ))

print(f"🔢 Registros a insertar: {len(rows)}")

cursor.executemany("""
    INSERT OR REPLACE INTO insumos_medicos
    (id, codigo, nombre, stock_actual, unidad, activo)
    VALUES (?, ?, ?, ?, ?, ?)
""", rows)

conn.commit()
conn.close()

print("\n" + "=" * 60)
print("✅ ¡INSUMOS CARGADOS DESDE CSV (created_at intacto)!")
