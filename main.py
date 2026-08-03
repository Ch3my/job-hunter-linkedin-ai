"""Punto de entrada de Job Hunter.

    python main.py

La logica esta en los paquetes: `providers/` (APIs), `ai/` (relevancia),
`db/` (SQLite), `services/` (orquestacion) y `ui/` (Tkinter).
"""

from ui import run

if __name__ == "__main__":
    run()
