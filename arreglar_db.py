import sqlite3

conn = sqlite3.connect('instance/historia_clinica.db')
cursor = conn.cursor()

print("=== 1. REVISANDO ÓRDENES MÉDICAS (TABLA MAESTRA) ===")
# Aquí vemos qué mandó el médico
cursor.execute('''
    SELECT id, historia_clinica_id, fecha_orden, medicamentos_json 
    FROM orden_medica 
    WHERE historia_clinica_id = 2
''')
ordenes = cursor.fetchall()

if not ordenes:
    print("❌ No hay órdenes médicas para la Historia ID: 2")
else:
    for o in ordenes:
        print(f"Orden ID: {o[0]} | Historia: {o[1]} | Fecha: {o[2]}")
        print(f"Contenido JSON: {o[3][:100]}...") # Mostramos el inicio del JSON

print("\n=== 2. REVISANDO MEDICAMENTOS EN INVENTARIO ===")
# Verificamos si los códigos coinciden con lo que hay en inventario
cursor.execute('SELECT id, codigo, nombre FROM medicamentos LIMIT 5')
meds = cursor.fetchall()
for m in meds:
    print(f"ID: {m[0]} | Código: {m[1]} | Nombre: {m[2]}")

conn.close()