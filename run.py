from app import create_app
app = create_app()

if __name__ == '__main__':
    with app.app_context():
        print("\n-- Rutas disponibles --")
        for rule in app.url_map.iter_rules():
            print(f"{rule.endpoint}: {rule}")
        print("-- Fin de rutas disponibles --\n")
    app.run(debug=True)
