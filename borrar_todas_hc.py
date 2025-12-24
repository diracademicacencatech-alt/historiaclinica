# borrar_todas_hc.py
from app import create_app, db
from app.models import (
    User,
    Paciente,
    HistoriaClinica,
    RegistroEnfermeria,
    Diagnostico,
    SignosVitales,
    OrdenMedica,
    Evolucion,
    AyudaDiagnostica,
    LabResultado,
    LabSolicitud,
    AdministracionMedicamento,
    # Catálogos que NO vamos a borrar:
    # Medico,
    # CIE10,
    # DiagnosticoCIE10,
    # Medicamento,
    # CatLaboratorioExamen,
    # CatLaboratorioParametro,
)

def reset_asistencial():
    app = create_app()
    with app.app_context():
        # 1. Detalle más profundo
        LabResultado.query.delete()
        AdministracionMedicamento.query.delete()
        AyudaDiagnostica.query.delete()
        Diagnostico.query.delete()
        SignosVitales.query.delete()
        Evolucion.query.delete()
        OrdenMedica.query.delete()
        RegistroEnfermeria.query.delete()

        # 2. Solicitudes de laboratorio ligadas a historias
        LabSolicitud.query.delete()

        # 3. Historias clínicas
        HistoriaClinica.query.delete()

        # 4. Pacientes
        Paciente.query.delete()

        db.session.commit()
        print("Datos asistenciales borrados (HC, enfermería, lab, diagnósticos, etc.).")

if __name__ == "__main__":
    reset_asistencial()
