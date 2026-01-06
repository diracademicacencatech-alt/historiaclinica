import csv
from app import create_app, db
from app.models import CatLaboratorioExamen, CatLaboratorioParametro

app = create_app()

with app.app_context():
    with open("lab_parametros_con_examen.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "param_id",
            "examen_id",
            "examen_nombre",
            "examen_grupo",
            "param_nombre",
            "unidad",
            "valor_ref_min",
            "valor_ref_max",
        ])

        # join Examen + Parametro
        q = (
            db.session.query(
                CatLaboratorioParametro.id,
                CatLaboratorioParametro.examen_id,
                CatLaboratorioExamen.nombre.label("examen_nombre"),
                CatLaboratorioExamen.grupo.label("examen_grupo"),
                CatLaboratorioParametro.nombre,
                CatLaboratorioParametro.unidad,
                CatLaboratorioParametro.valor_ref_min,
                CatLaboratorioParametro.valor_ref_max,
            )
            .join(
                CatLaboratorioExamen,
                CatLaboratorioParametro.examen_id == CatLaboratorioExamen.id,
            )
            .order_by(CatLaboratorioExamen.id, CatLaboratorioParametro.id)
        )

        for row in q.all():
            writer.writerow([
                row.id,
                row.examen_id,
                row.examen_nombre,
                row.examen_grupo or "",
                row.nombre,
                row.unidad or "",
                row.valor_ref_min if row.valor_ref_min is not None else "",
                row.valor_ref_max if row.valor_ref_max is not None else "",
            ])
