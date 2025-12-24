from app import create_app, db
from app.models import RegistroEnfermeria

def limpiar_registros_enfermeria():
    app = create_app()
    with app.app_context():
        try:
            num_eliminados = RegistroEnfermeria.query.delete()
            db.session.commit()
            print(f"Se eliminaron {num_eliminados} registros de enfermería.")
        except Exception as e:
            db.session.rollback()
            print(f"Error al eliminar registros: {e}")

if __name__ == "__main__":
    limpiar_registros_enfermeria()
