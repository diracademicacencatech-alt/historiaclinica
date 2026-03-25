import os
import re

def extraer_info_proyecto(ruta_base, archivo_salida="resumen_arquitectura.txt"):
    # Extensiones y carpetas a ignorar
    ignorar_dirs = {'.git', '__pycache__', 'venv', 'env', '.vscode', 'node_modules', 'static'}
    extensiones_interes = {'.py', '.html'} # Foco en Flask/Jinja2

    with open(archivo_salida, 'w', encoding='utf-8') as f_out:
        f_out.write("=== RESUMEN DE ARQUITECTURA TÉCNICA (HISTORIA CLÍNICA) ===\n\n")

        for raiz, dirs, archivos in os.walk(ruta_base):
            dirs[:] = [d for d in dirs if d not in ignorar_dirs]
            
            rel_path = os.path.relpath(raiz, ruta_base)
            nivel = 0 if rel_path == "." else rel_path.count(os.sep) + 1
            f_out.write(f"{'  ' * nivel}[DIR] {os.path.basename(raiz)}/\n")

            for nombre in archivos:
                if any(nombre.endswith(ext) for ext in extensiones_interes):
                    f_out.write(f"{'  ' * (nivel + 1)}|-- {nombre}\n")
                    
                    # Analizar contenido para extraer Rutas y Modelos
                    ruta_archivo = os.path.join(raiz, nombre)
                    try:
                        with open(ruta_archivo, 'r', encoding='utf-8') as f_in:
                            contenido = f_in.read()
                            
                            # 1. Extraer Endpoints (Flask @app.route o @blueprint.route)
                            rutas = re.findall(r'@.*\.route\(([\'\"]\/.*[\'\"])\)', contenido)
                            for r in rutas:
                                f_out.write(f"{'  ' * (nivel + 2)} > [Endpoint]: {r}\n")
                            
                            # 2. Extraer Funciones principales
                            funciones = re.findall(r'def\s+(\w+)\s*\(', contenido)
                            if funciones:
                                f_out.write(f"{'  ' * (nivel + 2)} > [Lógica]: {', '.join(funciones[:5])}...\n")

                            # 3. Extraer Clases (Modelos de Base de Datos)
                            clases = re.findall(r'class\s+(\w+)', contenido)
                            for c in clases:
                                f_out.write(f"{'  ' * (nivel + 2)} > [Modelo]: {c}\n")
                    except:
                        pass

if __name__ == "__main__":
    extraer_info_proyecto(".")
    print("Mapeo completado. Revisa 'resumen_arquitectura.txt'")