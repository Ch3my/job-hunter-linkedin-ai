"""Interfaz Tkinter.

La UI solo habla con `services.job_hunt` y con `db`; no conoce ninguna API.
Todo el trabajo pesado corre en un thread aparte y vuelve al thread de Tk con
`master.after()`.
"""

import sys
import threading
import tkinter as tk
import webbrowser
from datetime import datetime
from tkinter import messagebox, ttk

from config import active_provider_name
from db import (
    check_table_exists,
    create_table,
    delete_job,
    get_jobs_stats,
    insert_job,
    select_jobs,
    select_one_job,
    truncate_table,
    update_job_status,
)
from models import STATUSES, make_manual_posting
from services import job_hunt
from utils import append_to_log, icon_path, log_exception, open_log_file


class JobDatabaseGUI:
    def __init__(self, master):
        self.master = master
        self.master.title("Job Database Navigator")
        self.master.geometry("1080x720")
        self.set_window_icon()
        self.center_window()

        create_table()
        self.create_widgets()
        self.create_menu()
        self.load_jobs()
        self.update_stats()
        self.update_status(f"Listo (proveedor: {active_provider_name()})")

    # ------------------------------------------------------------------ menu
    def create_menu(self):
        menubar = tk.Menu(self.master)
        self.master.config(menu=menubar)
        menubar.add_command(label="Vaciar DB", command=self.call_vaciar_db)
        menubar.add_command(label="Ver Log", command=self.call_open_log)

    def call_vaciar_db(self):
        confirm = messagebox.askyesno(
            "Confirmar",
            "¿Estás seguro de que quieres vaciar la tabla de trabajos? Esta acción no se puede deshacer.",
        )
        if confirm:
            success, message = truncate_table()
            self.update_status(("Éxito: " if success else "Error: ") + message)
            if success:
                self.reset_job_details()
                self.refresh_jobs()
                self.update_stats()

    def call_open_log(self):
        if not open_log_file():
            self.update_status("Error al abrir el archivo de Log")

    # --------------------------------------------------------------- widgets
    def create_widgets(self):
        style = ttk.Style()
        style.configure("Treeview", font=("TkDefaultFont", 11))

        tree_frame = ttk.Frame(self.master)
        tree_frame.pack(pady=10, padx=10, expand=True, fill="both")

        self.tree = ttk.Treeview(
            tree_frame,
            columns=("Title", "Company", "Applied", "Created At", "Score"),
            show="headings",
            height=10,
        )
        self.tree.heading("Title", text="Title")
        self.tree.heading("Company", text="Company")
        self.tree.heading("Applied", text="Applied")
        self.tree.heading("Created At", text="Created At")
        self.tree.heading("Score", text="Score")

        self.tree.column("Title", width=500)
        self.tree.column("Applied", width=100)
        # Ancho justo para "2026-01-02 10:00:00"; el resto del espacio le sirve
        # mas al titulo, que es lo que uno lee.
        self.tree.column("Created At", width=140, anchor="center")
        self.tree.column("Score", width=60, anchor="center")

        tree_scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=tree_scrollbar.set)

        self.tree.grid(row=0, column=0, sticky="nsew")
        tree_scrollbar.grid(row=0, column=1, sticky="ns")
        tree_frame.grid_rowconfigure(0, weight=1)
        tree_frame.grid_columnconfigure(0, weight=1)

        self.tree.bind("<<TreeviewSelect>>", self.item_selected)

        # Estadisticas
        self.stats_frame = ttk.Frame(self.master)
        self.stats_frame.pack(pady=(0, 5), padx=10, fill="x")

        self.total_jobs_var = tk.StringVar()
        self.applied_jobs_var = tk.StringVar()
        self.discarded_jobs_var = tk.StringVar()
        self.not_applied_jobs_var = tk.StringVar()

        stats = (
            ("Total:", self.total_jobs_var),
            ("Applied:", self.applied_jobs_var),
            ("Discarded:", self.discarded_jobs_var),
            ("Not Applied:", self.not_applied_jobs_var),
        )
        for index, (label, variable) in enumerate(stats):
            ttk.Label(self.stats_frame, text=label).grid(
                row=0, column=index * 2, sticky="w", padx=5, pady=2
            )
            ttk.Label(
                self.stats_frame, textvariable=variable, font=("TkDefaultFont", 11)
            ).grid(row=0, column=index * 2 + 1, sticky="w", padx=5, pady=2)

        # Detalle del trabajo
        self.details_frame = ttk.LabelFrame(self.master, text="Job Details")
        self.details_frame.pack(pady=5, padx=10, fill="x")
        self.details_frame.columnconfigure(1, weight=1)

        self.title_var = tk.StringVar()
        self.company_var = tk.StringVar()
        self.url_var = tk.StringVar()
        self.applied_var = tk.StringVar()

        ttk.Label(self.details_frame, text="Title:").grid(row=0, column=0, sticky="e", padx=5, pady=2)
        ttk.Entry(self.details_frame, textvariable=self.title_var, width=50, font=("TkDefaultFont", 11)).grid(
            row=0, column=1, padx=5, pady=2, sticky="we"
        )

        ttk.Label(self.details_frame, text="Company:").grid(row=0, column=2, sticky="e", padx=5, pady=2)
        ttk.Entry(self.details_frame, textvariable=self.company_var, width=50, font=("TkDefaultFont", 11)).grid(
            row=0, column=3, padx=5, pady=2, sticky="we"
        )

        self.add_update_button = ttk.Button(
            self.details_frame, text="Add/Update Job", command=self.add_update_job
        )
        self.add_update_button.grid(row=0, column=4, padx=5, pady=2, sticky="e")

        ttk.Label(self.details_frame, text="URL:").grid(row=1, column=0, sticky="e", padx=5, pady=2)
        ttk.Entry(self.details_frame, textvariable=self.url_var, width=50, font=("TkDefaultFont", 11)).grid(
            row=1, column=1, columnspan=3, padx=5, pady=2, sticky="we"
        )

        self.delete_job_btn = ttk.Button(self.details_frame, text="Delete Job", command=self.delete_job_fn)
        self.delete_job_btn.grid(row=1, column=4, padx=5, pady=2, sticky="e")

        self.open_url_button = ttk.Button(self.details_frame, text="Visit Site", command=self.open_url)
        self.open_url_button.grid(row=2, column=4, padx=5, pady=2, sticky="e")

        ttk.Label(self.details_frame, text="Applied:").grid(row=2, column=0, sticky="e", padx=5, pady=2)
        self.applied_combo = ttk.Combobox(
            self.details_frame,
            font=("TkDefaultFont", 11),
            textvariable=self.applied_var,
            values=list(STATUSES),
        )
        self.applied_combo.grid(row=2, column=1, padx=5, pady=2, sticky="w")
        self.applied_combo.bind("<<ComboboxSelected>>", self.update_applied_status)

        # Descripcion
        self.description_frame = ttk.LabelFrame(self.master, text="Job Description")
        self.description_frame.pack(pady=10, padx=10, expand=True, fill="both")

        text_frame = ttk.Frame(self.description_frame)
        text_frame.pack(expand=True, fill="both", padx=5, pady=5)

        self.description_text = tk.Text(text_frame, wrap=tk.WORD, height=10, font=("TkDefaultFont", 11))
        self.description_text.pack(side="left", expand=True, fill="both")

        scrollbar = ttk.Scrollbar(text_frame, orient="vertical", command=self.description_text.yview)
        scrollbar.pack(side="right", fill="y")
        self.description_text.config(yscrollcommand=scrollbar.set)

        self.thread_button = ttk.Button(self.master, text="Hunt!", command=self.start_threaded_operation)
        self.thread_button.pack(pady=10)

        self.status_bar = tk.Label(
            self.master, text="  Ready", bd=1, relief=tk.SUNKEN, anchor=tk.W, font=("TkDefaultFont", 10)
        )
        self.status_bar.pack(side=tk.BOTTOM, fill=tk.X)

    # ---------------------------------------------------------------- estado
    def update_status(self, message):
        # Siempre con la hora, para distinguir un mensaje viejo de uno nuevo.
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.status_bar.config(text=f"  {current_time} - {message}")
        self.status_bar.update_idletasks()

    def post_status(self, message):
        """Actualiza el estado desde cualquier thread."""
        self.master.after(0, lambda: self.update_status(message))

    # ---------------------------------------------------------------- acciones
    def open_url(self):
        url = self.url_var.get()
        if url:
            webbrowser.open(url)

    def delete_job_fn(self):
        title, company = self.title_var.get(), self.company_var.get()
        if not title or not company:
            return
        confirm = messagebox.askyesno(
            "Confirmar",
            "¿Estás seguro de que quieres Eliminar este trabajo? Esta acción no se puede deshacer.",
        )
        if confirm:
            delete_job(title, company)
            self.reset_job_details()
            self.refresh_jobs()
            self.update_stats()

    def reset_job_details(self):
        self.title_var.set("")
        self.company_var.set("")
        self.url_var.set("")
        self.applied_var.set("")
        self.description_text.delete("1.0", tk.END)

    def add_update_job(self):
        title = self.title_var.get().strip()
        company = self.company_var.get().strip()

        if not (title and company):
            self.update_status("Title and Company are required fields.")
            return

        if select_one_job(title, company):
            # NOTA: por ahora solo actualiza el estado.
            if update_job_status(self.applied_var.get(), title, company):
                self.update_status("Job actualizado!")
                self.refresh_jobs()
                self.update_stats()
            else:
                self.update_status("No se pudo actualizar el job.")
            return

        posting = make_manual_posting(
            title=title,
            company=company,
            url=self.url_var.get(),
            description=self.description_text.get("1.0", tk.END).strip(),
            applied=self.applied_var.get(),
        )
        if insert_job(posting):
            self.update_status("Job added successfully!")
            self.refresh_jobs()
            self.update_stats()
        else:
            self.update_status("Failed to add job. Please try again.")

    def update_stats(self):
        stats = get_jobs_stats()
        self.total_jobs_var.set(str(stats["total"]))
        self.applied_jobs_var.set(str(stats["applied"]))
        self.discarded_jobs_var.set(str(stats["discarded"]))
        self.not_applied_jobs_var.set(str(stats["not_applied"]))

    def load_jobs(self):
        for item in self.tree.get_children():
            self.tree.delete(item)

        if not check_table_exists():
            self.update_status("La tabla 'jobs' no existe todavía.")
            return

        for row in select_jobs():
            self.tree.insert("", "end", values=row)

    def item_selected(self, event):
        for selected_item in self.tree.selection():
            record = self.tree.item(selected_item)["values"]
            if len(record) < 3:
                continue
            self.title_var.set(record[0])
            self.company_var.set(record[1])
            self.applied_var.set(record[2])

            details = select_one_job(record[0], record[1])
            self.description_text.delete("1.0", tk.END)
            if details:
                descripcion, url, motivo = details[0] or "", details[1] or "", details[2] or ""
                # El motivo de la AI va arriba de todo: es lo primero que uno
                # quiere leer al pararse sobre un trabajo.
                if motivo:
                    self.description_text.insert(tk.END, f"AI: {motivo}\n\n")
                self.description_text.insert(tk.END, descripcion)
                self.url_var.set(url)
            else:
                self.url_var.set("")

    def update_applied_status(self, event):
        if not self.tree.selection():
            return
        selected_item = self.tree.selection()[0]
        record = self.tree.item(selected_item)["values"]
        new_status = self.applied_var.get()

        update_job_status(new_status, record[0], record[1])
        self.update_stats()
        self.tree.item(
            selected_item, values=(record[0], record[1], new_status, record[3], record[4])
        )

    # ------------------------------------------------------------- busqueda
    def start_threaded_operation(self):
        self.thread_button.config(state="disabled")
        threading.Thread(target=self.run_job_hunt, daemon=True).start()

    def run_job_hunt(self):
        try:
            report = job_hunt(on_status=self.post_status)
            self.master.after(0, self.refresh_jobs)
            self.master.after(0, self.update_stats)
            self.post_status(report.message())
        except Exception as error:
            # job_hunt ya captura lo suyo; esto es la ultima red de seguridad.
            log_exception("run_job_hunt", error)
            self.post_status(f"An error occurred during job hunt: {error}")
        finally:
            # config() de Tk debe correr en el thread de la UI.
            self.master.after(0, lambda: self.thread_button.config(state="normal"))

    def refresh_jobs(self):
        self.load_jobs()

    # ---------------------------------------------------------------- ventana
    def set_window_icon(self):
        """Pone el icono de la app en la ventana y en la barra de tareas.

        Sin esto Tk usa el icono por defecto (la plumita de Python). El flag
        --icon de PyInstaller solo cambia el icono del .exe en el explorador,
        no el de la ventana, asi que hay que setearlo igual en tiempo de
        ejecucion.

        Si el archivo no esta o el sistema no soporta .ico, la app arranca sin
        icono: nunca deberia impedir abrir la ventana.
        """
        path = icon_path()
        if not path:
            append_to_log("[ui] no se encontro assets/favicon.ico, se usa el icono por defecto")
            return

        try:
            # En Windows esta es la forma que acepta archivos .ico, y ademas
            # deja el icono como default para los dialogos que se abran despues.
            self.master.iconbitmap(default=path)
            return
        except tk.TclError:
            pass

        try:
            self.master.iconbitmap(path)
            return
        except tk.TclError:
            pass

        try:
            # Linux/macOS: iconbitmap no acepta .ico, se intenta como imagen.
            self._icon_image = tk.PhotoImage(file=path)
            self.master.iconphoto(True, self._icon_image)
        except Exception as error:
            log_exception("set_window_icon", error)

    def center_window(self, width=1080, height=720, taskbar_offset=40):
        screen_width = self.master.winfo_screenwidth()
        screen_height = self.master.winfo_screenheight()

        x = (screen_width / 2) - (width / 2)
        y = max((screen_height / 2) - (height / 2) - (taskbar_offset / 2), 0)

        self.master.geometry("%dx%d+%d+%d" % (width, height, int(x), int(y)))
        self.master.lift()
        self.master.attributes("-topmost", True)
        self.master.after_idle(self.master.attributes, "-topmost", False)


def _claim_windows_taskbar_identity():
    """Hace que Windows agrupe la app bajo su propio icono, no bajo el de Python.

    Corriendo con `python main.py` el proceso es python.exe, y la barra de
    tareas muestra el icono de Python aunque la ventana ya tenga el suyo. Para
    separarlos hay que declarar un AppUserModelID propio antes de crear la
    ventana. En otros sistemas operativos esto no aplica y se ignora.
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("JobHunter.App")
    except Exception as error:
        log_exception("_claim_windows_taskbar_identity", error)


def run():
    _claim_windows_taskbar_identity()
    root = tk.Tk()
    JobDatabaseGUI(root)
    root.mainloop()
