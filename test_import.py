import sys
# Añade el directorio 'src' al path si es necesario, aunque con la importación relativa no debería serlo
# sys.path.insert(0, './src') # Descomenta si la importación directa falla
try:
    from src.gui.main_window import MainWindow
    print("Importación de MainWindow exitosa.")

    # Intentar instanciar para ver si el __init__ falla
    # Esto podría dar el mismo error si el problema está en la instancia
    # window = MainWindow()
    # print("Instancia de MainWindow creada.")

    # Verificar si el atributo existe después de la importación
    if hasattr(MainWindow, 'handle_export_files'):
        print("El atributo 'handle_export_files' EXISTE en la clase MainWindow.")
    else:
        print("ERROR: El atributo 'handle_export_files' NO EXISTE en la clase MainWindow.")

except ImportError as e:
    print(f"Error de importación: {e}")
except AttributeError as e:
    print(f"Error de atributo durante la prueba: {e}")
except Exception as e:
    print(f"Otro error durante la prueba: {e}")

