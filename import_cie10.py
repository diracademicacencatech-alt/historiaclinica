import pandas as pd
from app import create_app, db
from app.models import DiagnosticoCIE10

# OJO: en Python las backslashes se escapan, por eso uso r"" (raw string)
RUTA_EXCEL = r"C:\Users\HASISTENCIAL93\Downloads\TablaReferencia_CIE10_}.xlsx"

def run():
    # La hoja se llama "Table" según el archivo que enviaste [file:1088]
    df = pd.read_excel(RUTA_EXCEL, sheet_name="Table")

    # Filtrar solo filas CIE10 habilitadas
    df = df[(df["Tabla"] == "CIE10") & (df["Habilitado"] == "SI")]

    # Limpiar tabla antes (opcional)
    DiagnosticoCIE10.query.delete()
    db.session.commit()

    for _, row in df.iterrows():
        dx = DiagnosticoCIE10(
            codigo=str(row["Codigo"]).strip(),
            nombre=str(row["Nombre"]).strip(),
            descripcion=str(row["Descripcion"]).strip() if pd.notna(row["Descripcion"]) else None,
            habilitado=True,
        )
        db.session.add(dx)

    db.session.commit()
    print(f"Importados {len(df)} diagnósticos CIE-10")

if __name__ == "__main__":
    app = create_app()
    with app.app_context():
        run()
