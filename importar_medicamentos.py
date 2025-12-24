import csv
from app import create_app
from app.extensions import db
from app.models import Medicamento

RUTA_CSV = "medicamentos_iniciales.csv"

def run():
    with open(RUTA_CSV, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)

        # Opcional: limpiar tabla antes de cargar
        Medicamento.query.delete()
        db.session.commit()

        for row in reader:
            med = Medicamento(
                codigo=row["codigo"].strip(),
                nombre=row["nombre"].strip(),
                forma_farmaceutica=(row.get("forma_farmaceutica") or "").strip() or None,
                presentacion=(row.get("presentacion") or "").strip() or None,
                cantidad_disponible=row.get("cantidad_disponible") or 0,
                unidad_inventario=(row.get("unidad_inventario") or "").strip() or None,
            )
            db.session.add(med)

        db.session.commit()
        print("Catálogo inicial de medicamentos importado")

if __name__ == "__main__":
    app = create_app()
    with app.app_context():
        run()
