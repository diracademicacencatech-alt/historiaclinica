import csv
from app import create_app, db
from app.models import CatLaboratorioExamen, CatLaboratorioParametro

app = create_app()

CSV_PATH = r"C:\Users\HASISTENCIAL93\Documents\JF HELMER\SOFTWARE HC\historiaclinica\lab_parametros_con_examen.csv"

with app.app_context():
    # Opcional: limpiar tablas antes de cargar
    # CatLaboratorioParametro.query.delete()
    # CatLaboratorioExamen.query.delete()
    # db.session.commit()

    examenes_cache = {}

    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)

        for row in reader:
            examen_id = int(row["examen_id"])
            examen_nombre = row["examen_nombre"].strip()
            examen_grupo = row["examen_grupo"].strip() or None

            # Crear/actualizar examen solo una vez
            if examen_id not in examenes_cache:
                ex = CatLaboratorioExamen.query.get(examen_id)
                if ex is None:
                    ex = CatLaboratorioExamen(
                        id=examen_id,
                        nombre=examen_nombre,
                        grupo=examen_grupo,
                        activo=True,
                    )
                    db.session.add(ex)
                else:
                    ex.nombre = examen_nombre
                    ex.grupo = examen_grupo
                    ex.activo = True
                examenes_cache[examen_id] = ex

            # Crear/actualizar parámetro
            param_id = int(row["param_id"])  # <-- aquí el cambio
            nombre_param = row["param_nombre"].strip()
            unidad = row["unidad"].strip() or None

            def parse_float(value: str):
                value = value.strip()
                if not value:
                    return None
                return float(value)

            valor_min = parse_float(row["valor_ref_min"])
            valor_max = parse_float(row["valor_ref_max"])

            p = CatLaboratorioParametro.query.get(param_id)
            if p is None:
                p = CatLaboratorioParametro(
                    id=param_id,        # ajusta si tu PK se llama distinto
                    examen_id=examen_id,
                    nombre=nombre_param,
                    unidad=unidad,
                    valor_ref_min=valor_min,
                    valor_ref_max=valor_max,
                )
                db.session.add(p)
            else:
                p.examen_id = examen_id
                p.nombre = nombre_param
                p.unidad = unidad
                p.valor_ref_min = valor_min
                p.valor_ref_max = valor_max

    db.session.commit()
    print("Importación de exámenes y parámetros completada.")
