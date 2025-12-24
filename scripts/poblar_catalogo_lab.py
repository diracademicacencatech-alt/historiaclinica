from app.extensions import db
from app.models import CatLaboratorioExamen, CatLaboratorioParametro

def crear_examen(nombre, grupo, parametros):
    ex = CatLaboratorioExamen(nombre=nombre, grupo=grupo)
    db.session.add(ex)
    db.session.flush()  # para obtener ex.id sin hacer commit todavía
    for p in parametros:
        param = CatLaboratorioParametro(
            examen_id=ex.id,
            nombre=p.get("nombre"),
            unidad=p.get("unidad"),
            valor_ref_min=p.get("min"),
            valor_ref_max=p.get("max"),
        )
        db.session.add(param)
    return ex

def poblar_catalogo():
    # Hemograma completo
    crear_examen("Hemograma completo", "Hematología", [
        {"nombre": "Hemoglobina", "unidad": "g/dL"},
        {"nombre": "Hematocrito", "unidad": "%"},
        {"nombre": "Leucocitos", "unidad": "/mm3"},
        {"nombre": "Plaquetas", "unidad": "/mm3"},
    ])

    # Glucosa
    crear_examen("Glucosa en sangre", "Química", [
        {"nombre": "Glucosa", "unidad": "mg/dL"},
    ])

    # Creatinina
    crear_examen("Creatinina sérica", "Química", [
        {"nombre": "Creatinina", "unidad": "mg/dL"},
    ])

    # Perfil lipídico
    crear_examen("Perfil lipídico", "Química", [
        {"nombre": "Colesterol total", "unidad": "mg/dL"},
        {"nombre": "HDL colesterol", "unidad": "mg/dL"},
        {"nombre": "LDL colesterol", "unidad": "mg/dL"},
        {"nombre": "Triglicéridos", "unidad": "mg/dL"},
    ])

    # Uroanálisis
    crear_examen("Uroanálisis", "Orina", [
        {"nombre": "Color", "unidad": None},
        {"nombre": "Aspecto", "unidad": None},
        {"nombre": "Densidad", "unidad": None},
        {"nombre": "pH", "unidad": None},
        {"nombre": "Proteínas", "unidad": None},
        {"nombre": "Glucosa", "unidad": None},
        {"nombre": "Cetonas", "unidad": None},
        {"nombre": "Sangre", "unidad": None},
        {"nombre": "Leucocitos", "unidad": None},
    ])

    # Cultivo de orina
    crear_examen("Cultivo de orina", "Microbiología", [
        {"nombre": "Resultado", "unidad": None},
        {"nombre": "Recuento colonias", "unidad": "UFC/mL"},
        {"nombre": "Germen aislado", "unidad": None},
    ])

    # Cultivo de heces
    crear_examen("Cultivo de heces", "Microbiología", [
        {"nombre": "Resultado", "unidad": None},
        {"nombre": "Microorganismos identificados", "unidad": None},
    ])

    db.session.commit()
