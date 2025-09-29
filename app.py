"""
AgendaTaller - Aplicación de gestión de trabajos y mantenimientos
Archivo: AgendaTaller_App.py
Lenguaje: Python 3.10+
Dependencias: 
 - peewee (pip install peewee)
 - tkcalendar (pip install tkcalendar)
Descripción: App de escritorio simple en Tkinter + Peewee + SQLite que permite:
 - Registrar equipos (máquinas/vehículos) con información detallada
 - Registrar trabajos realizados y presupuestos
 - Calcular/registrar la fecha del próximo service
 - Ver lista de próximos servicios ordenada por fecha
 - Exportar listados a CSV

Instrucciones:
 1) Instalar dependencias:
    pip install peewee tkcalendar
 2) Ejecutar:
    python app.py

Nota: Esta es una versión inicial y autocontenida pensada para que la uses en el trabajo.
Puedes pedirme que añada: importación/exportación desde Excel, generación de PDFs, recordatorios por correo/WhatsApp, interfaz más avanzada (PyQt), multiusuario, backups automáticos, etc.

"""
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from datetime import datetime, timedelta
from tkcalendar import DateEntry
import csv
import os
from peewee import SqliteDatabase, Model, CharField, DateField, TextField, IntegerField, FloatField, ForeignKeyField, fn

DB_FILENAME = 'agenda_taller.db'
db = SqliteDatabase(DB_FILENAME)

# ---------------------------- MODELOS (Peewee) ----------------------------
class BaseModel(Model):
    class Meta:
        database = db

class Equipment(BaseModel):
    marca = CharField()  # Obligatorio
    modelo = CharField()  # Obligatorio
    anio = IntegerField()  # Obligatorio
    n_serie = CharField()  # Obligatorio
    propietario = CharField(null=True)  # Opcional
    vehiculo = CharField(null=True)  # Opcional
    dominio = CharField(null=True)  # Opcional (Dominio del vehículo)
    notes = TextField(null=True)

class Job(BaseModel):
    equipment = ForeignKeyField(Equipment, backref='jobs', on_delete='CASCADE')
    date_done = DateField()
    description = TextField()
    budget = FloatField(default=0.0)
    next_service_days = IntegerField(null=True)  # después de cuántos días se debe el next service
    next_service_date = DateField(null=True)
    notes = TextField(null=True)

# Inicializar DB y migrar si es necesario
def init_db():
    db.connect()
    
    # Verificar si necesitamos migrar la estructura antigua
    cursor = db.execute_sql("PRAGMA table_info(equipment);")
    columns = cursor.fetchall()
    column_names = [col[1] for col in columns]
    
    # Si existe la columna 'name' es la estructura antigua
    if 'name' in column_names and 'marca' not in column_names:
        print("Detectada base de datos con estructura antigua. Migrando...")
        migrate_old_database()
    else:
        # Crear tablas si no existen
    db.create_tables([Equipment, Job])

def migrate_old_database():
    """Migra la base de datos de la estructura antigua a la nueva"""
    try:
        # Renombrar tabla antigua
        db.execute_sql("ALTER TABLE equipment RENAME TO equipment_old;")
        
        # Crear nueva tabla con estructura actualizada
        db.create_tables([Equipment])
        
        # Migrar datos existentes (adaptando los campos antiguos a los nuevos)
        cursor = db.execute_sql("SELECT id, name, serial, location, notes FROM equipment_old;")
        old_equipment = cursor.fetchall()
        
        for eq_data in old_equipment:
            eq_id, name, serial, location, notes = eq_data
            # Intentar extraer información del nombre para los nuevos campos
            # Por defecto usar el nombre como marca y "Sin especificar" para el resto
            Equipment.create(
                marca=name or "Sin especificar",
                modelo="Sin especificar",
                anio=2024,  # Año por defecto
                n_serie=serial or f"NS-{eq_id}",
                propietario=location,  # Usar location como propietario si existe
                vehiculo=None,
                dominio=None,
                notes=notes
            )
        
        # Eliminar tabla antigua
        db.execute_sql("DROP TABLE equipment_old;")
        
        print(f"Migración completada. {len(old_equipment)} equipos migrados.")
        print("Nota: Por favor revisa y actualiza la información de los equipos migrados.")
        messagebox.showinfo(
            "Migración Completada", 
            f"Se han migrado {len(old_equipment)} equipos a la nueva estructura.\n\n"
            "Por favor revisa y actualiza la información de cada equipo con los datos correctos "
            "(Marca, Modelo, Año, N° de Serie)."
        )
    except Exception as e:
        print(f"Error durante la migración: {e}")
        messagebox.showerror(
            "Error de Migración",
            f"Hubo un error al migrar la base de datos:\n{e}\n\n"
            "Se recomienda hacer backup del archivo 'agenda_taller.db' y contactar soporte."
        )

# ---------------------------- LÓGICA DE NEGOCIO ----------------------------

def calculate_next_service(date_done: datetime.date, days: int | None):
    if not days:
        return None
    return date_done + timedelta(days=days)

# ---------------------------- INTERFAZ GRÁFICA ----------------------------
class AgendaApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('Agenda Taller - Agenda de trabajos y servicios')
        self.geometry('1000x600')
        self.create_widgets()
        self.refresh_equipment_list()
        self.refresh_upcoming_services()

    def create_widgets(self):
        # --- Panel izquierdo: lista de equipos ---
        left = ttk.Frame(self)
        left.pack(side='left', fill='y', padx=8, pady=8)

        ttk.Label(left, text='Equipos', font=('TkDefaultFont', 10, 'bold')).pack(anchor='w')
        
        # Barra de búsqueda
        search_frame = ttk.Frame(left)
        search_frame.pack(fill='x', pady=(5, 10))
        ttk.Label(search_frame, text='🔍').pack(side='left')
        self.search_var = tk.StringVar()
        self.search_var.trace('w', lambda *args: self.filter_equipment_list())
        self.search_entry = ttk.Entry(search_frame, textvariable=self.search_var, width=25)
        self.search_entry.pack(side='left', fill='x', expand=True, padx=2)
        
        # Contador de equipos
        self.lbl_equip_count = ttk.Label(left, text='Total: 0 equipos', font=('TkDefaultFont', 8))
        self.lbl_equip_count.pack(anchor='w')
        
        self.equip_list = tk.Listbox(left, width=30, height=20)
        self.equip_list.pack(fill='y', expand=True)
        self.equip_list.bind('<<ListboxSelect>>', self.on_equipment_select)

        btn_frame = ttk.Frame(left)
        btn_frame.pack(fill='x', pady=6)
        ttk.Button(btn_frame, text='➕ Nuevo', command=self.new_equipment).pack(side='left', padx=2)
        ttk.Button(btn_frame, text='✏️ Editar', command=self.edit_equipment).pack(side='left', padx=2)
        ttk.Button(btn_frame, text='📋 Duplicar', command=self.duplicate_equipment).pack(side='left', padx=2)
        
        btn_frame2 = ttk.Frame(left)
        btn_frame2.pack(fill='x', pady=2)
        ttk.Button(btn_frame2, text='🗑️ Eliminar', command=self.delete_equipment).pack(side='left', padx=2)
        ttk.Button(btn_frame2, text='📊 Estadísticas', command=self.show_statistics).pack(side='left', padx=2)

        ttk.Separator(left, orient='horizontal').pack(fill='x', pady=8)
        ttk.Button(left, text='Exportar equipos (CSV)', command=self.export_equipments_csv).pack(fill='x')

        # --- Panel derecho: tabs con detalles ---
        right = ttk.Frame(self)
        right.pack(side='right', fill='both', expand=True, padx=8, pady=8)

        self.tabs = ttk.Notebook(right)
        self.tabs.pack(fill='both', expand=True)

        # Tab 1: Detalle y trabajos
        tab_detail = ttk.Frame(self.tabs)
        self.tabs.add(tab_detail, text='Detalle / Trabajos')

        detail_top = ttk.Frame(tab_detail)
        detail_top.pack(fill='x', pady=4)
        ttk.Label(detail_top, text='Equipo seleccionado:').pack(side='left')
        self.lbl_selected = ttk.Label(detail_top, text='(ninguno)')
        self.lbl_selected.pack(side='left', padx=6)

        # Trabajos list
        self.jobs_tree = ttk.Treeview(tab_detail, columns=('date','desc','budget','next_service'), show='headings')
        self.jobs_tree.heading('date', text='Fecha')
        self.jobs_tree.heading('desc', text='Descripción')
        self.jobs_tree.heading('budget', text='Presupuesto')
        self.jobs_tree.heading('next_service', text='Próx. Service')
        self.jobs_tree.pack(fill='both', expand=True, pady=6)

        job_buttons = ttk.Frame(tab_detail)
        job_buttons.pack(fill='x')
        ttk.Button(job_buttons, text='Nuevo Trabajo', command=self.new_job).pack(side='left', padx=4)
        ttk.Button(job_buttons, text='Editar Trabajo', command=self.edit_job).pack(side='left', padx=4)
        ttk.Button(job_buttons, text='Eliminar Trabajo', command=self.delete_job).pack(side='left', padx=4)
        ttk.Button(job_buttons, text='Exportar trabajos (CSV)', command=self.export_jobs_csv).pack(side='right', padx=4)

        # Tab 2: Próximos servicios
        tab_upcoming = ttk.Frame(self.tabs)
        self.tabs.add(tab_upcoming, text='Próximos Servicios')

        self.upcoming_tree = ttk.Treeview(tab_upcoming, columns=('equip','next_date','days_left','budget'), show='headings')
        self.upcoming_tree.heading('equip', text='Equipo')
        self.upcoming_tree.heading('next_date', text='Fecha Próxima')
        self.upcoming_tree.heading('days_left', text='Días Restantes')
        self.upcoming_tree.heading('budget', text='Último Presupuesto')
        self.upcoming_tree.pack(fill='both', expand=True, pady=6)

        up_buttons = ttk.Frame(tab_upcoming)
        up_buttons.pack(fill='x')
        ttk.Button(up_buttons, text='Refrescar', command=self.refresh_upcoming_services).pack(side='left', padx=4)
        ttk.Button(up_buttons, text='Exportar próximos (CSV)', command=self.export_upcoming_csv).pack(side='right', padx=4)

    # ---------------- UI actions: Equipos ----------------
    def refresh_equipment_list(self):
        self.equip_list.delete(0, tk.END)
        self.all_equipment = []  # Guardar todos los equipos para búsqueda
        
        for eq in Equipment.select().order_by(Equipment.marca, Equipment.modelo):
            display_text = f"{eq.id} - {eq.marca} {eq.modelo} ({eq.anio})"
            if eq.propietario:
                display_text += f" - {eq.propietario}"
            self.equip_list.insert(tk.END, display_text)
            self.all_equipment.append((eq, display_text))
        
        # Actualizar contador
        count = Equipment.select().count()
        self.lbl_equip_count.config(text=f'Total: {count} equipo{"s" if count != 1 else ""}')

    def get_selected_equipment_id(self):
        sel = self.equip_list.curselection()
        if not sel:
            return None
        text = self.equip_list.get(sel[0])
        return int(text.split(' - ')[0])

    def on_equipment_select(self, event=None):
        eid = self.get_selected_equipment_id()
        if not eid:
            self.lbl_selected.config(text='(ninguno)')
            self.jobs_tree.delete(*self.jobs_tree.get_children())
            return
        eq = Equipment.get_by_id(eid)
        
        # Mostrar información completa del equipo
        info_text = f'{eq.marca} {eq.modelo} ({eq.anio}) - Serie: {eq.n_serie}'
        if eq.propietario:
            info_text += f'\nPropietario: {eq.propietario}'
        if eq.vehiculo:
            info_text += f' | Vehículo: {eq.vehiculo}'
        if eq.dominio:
            info_text += f' | Dominio: {eq.dominio}'
        
        self.lbl_selected.config(text=info_text)
        
        # Cargar trabajos y calcular estadísticas
        self.jobs_tree.delete(*self.jobs_tree.get_children())
        total_gastado = 0
        trabajos_count = 0
        
        for job in Job.select().where(Job.equipment == eq).order_by(Job.date_done.desc()):
            ns = job.next_service_date.strftime('%d/%m/%Y') if job.next_service_date else ''
            self.jobs_tree.insert('', tk.END, iid=str(job.id), 
                values=(job.date_done.strftime('%d/%m/%Y'), 
                       job.description[:40] + ('...' if len(job.description) > 40 else ''), 
                       f"${job.budget:.2f}", 
                       ns))
            total_gastado += job.budget
            trabajos_count += 1
        
        # Actualizar título con estadísticas
        if trabajos_count > 0:
            promedio = total_gastado / trabajos_count
            stats_text = f' | {trabajos_count} trabajo{"s" if trabajos_count != 1 else ""} | Total: ${total_gastado:,.2f} | Promedio: ${promedio:,.2f}'
            self.lbl_selected.config(text=info_text + stats_text)

    def new_equipment(self):
        EquipmentForm(self, None, on_save=self.on_equipment_saved)

    def edit_equipment(self):
        eid = self.get_selected_equipment_id()
        if not eid:
            messagebox.showwarning('Atención', 'Seleccioná un equipo para editar')
            return
        eq = Equipment.get_by_id(eid)
        EquipmentForm(self, eq, on_save=self.on_equipment_saved)

    def delete_equipment(self):
        eid = self.get_selected_equipment_id()
        if not eid:
            messagebox.showwarning('Atención', 'Seleccioná un equipo para borrar')
            return
        if not messagebox.askyesno('Confirmar', '¿Eliminar equipo y todos sus trabajos?'):
            return
        eq = Equipment.get_by_id(eid)
        eq.delete_instance(recursive=True)
        self.refresh_equipment_list()
        self.refresh_upcoming_services()

    def on_equipment_saved(self, _):
        self.refresh_equipment_list()
    
    def filter_equipment_list(self):
        """Filtra la lista de equipos según el texto de búsqueda"""
        search_text = self.search_var.get().lower()
        
        self.equip_list.delete(0, tk.END)
        
        if not hasattr(self, 'all_equipment'):
            self.refresh_equipment_list()
            return
            
        count = 0
        for eq, display_text in self.all_equipment:
            # Buscar en todos los campos relevantes
            search_in = f"{eq.marca} {eq.modelo} {eq.anio} {eq.n_serie}".lower()
            if eq.propietario:
                search_in += f" {eq.propietario}".lower()
            if eq.vehiculo:
                search_in += f" {eq.vehiculo}".lower() 
            if eq.dominio:
                search_in += f" {eq.dominio}".lower()
                
            if search_text in search_in:
                self.equip_list.insert(tk.END, display_text)
                count += 1
        
        self.lbl_equip_count.config(text=f'Mostrando: {count} equipo{"s" if count != 1 else ""}')
    
    def duplicate_equipment(self):
        """Duplica el equipo seleccionado con un nuevo número de serie"""
        eid = self.get_selected_equipment_id()
        if not eid:
            messagebox.showwarning('Atención', 'Seleccioná un equipo para duplicar')
            return
        
        eq = Equipment.get_by_id(eid)
        # Crear copia con nuevo número de serie
        new_eq = Equipment.create(
            marca=eq.marca,
            modelo=eq.modelo,
            anio=eq.anio,
            n_serie=eq.n_serie + "-COPIA",  # Agregar sufijo para diferenciar
            propietario=eq.propietario,
            vehiculo=eq.vehiculo,
            dominio=eq.dominio,
            notes=eq.notes
        )
        self.refresh_equipment_list()
        messagebox.showinfo('Duplicado', f'Equipo duplicado exitosamente. Recuerde cambiar el N° de Serie.')
        # Abrir formulario de edición para la copia
        EquipmentForm(self, new_eq, on_save=self.on_equipment_saved)
    
    def show_statistics(self):
        """Muestra estadísticas de los equipos y trabajos"""
        stats_window = tk.Toplevel(self)
        stats_window.title('Estadísticas del Taller')
        stats_window.geometry('600x500')
        
        notebook = ttk.Notebook(stats_window)
        notebook.pack(fill='both', expand=True, padx=10, pady=10)
        
        # Tab de estadísticas generales
        tab_general = ttk.Frame(notebook)
        notebook.add(tab_general, text='General')
        
        frm_general = ttk.Frame(tab_general)
        frm_general.pack(padx=20, pady=20)
        
        # Estadísticas generales
        total_equipment = Equipment.select().count()
        total_jobs = Job.select().count()
        total_budget = Job.select(fn.SUM(Job.budget)).scalar() or 0
        
        ttk.Label(frm_general, text='ESTADÍSTICAS GENERALES', font=('TkDefaultFont', 12, 'bold')).grid(row=0, column=0, columnspan=2, pady=10)
        
        ttk.Label(frm_general, text='Total de Equipos:').grid(row=1, column=0, sticky='e', padx=10, pady=5)
        ttk.Label(frm_general, text=str(total_equipment)).grid(row=1, column=1, sticky='w', pady=5)
        
        ttk.Label(frm_general, text='Total de Trabajos:').grid(row=2, column=0, sticky='e', padx=10, pady=5)
        ttk.Label(frm_general, text=str(total_jobs)).grid(row=2, column=1, sticky='w', pady=5)
        
        ttk.Label(frm_general, text='Presupuesto Total:').grid(row=3, column=0, sticky='e', padx=10, pady=5)
        ttk.Label(frm_general, text=f'${total_budget:,.2f}').grid(row=3, column=1, sticky='w', pady=5)
        
        if total_jobs > 0:
            avg_budget = total_budget / total_jobs
            ttk.Label(frm_general, text='Presupuesto Promedio:').grid(row=4, column=0, sticky='e', padx=10, pady=5)
            ttk.Label(frm_general, text=f'${avg_budget:,.2f}').grid(row=4, column=1, sticky='w', pady=5)
        
        # Tab de top equipos
        tab_top = ttk.Frame(notebook)
        notebook.add(tab_top, text='Top Equipos')
        
        ttk.Label(tab_top, text='EQUIPOS CON MÁS TRABAJOS', font=('TkDefaultFont', 11, 'bold')).pack(pady=10)
        
        # TreeView para top equipos
        tree = ttk.Treeview(tab_top, columns=('equipo', 'trabajos', 'total'), show='headings', height=15)
        tree.heading('equipo', text='Equipo')
        tree.heading('trabajos', text='Cant. Trabajos')
        tree.heading('total', text='Total Gastado')
        tree.pack(padx=20, pady=10, fill='both', expand=True)
        
        # Query para top equipos
        from peewee import fn
        for eq in Equipment.select():
            job_count = Job.select().where(Job.equipment == eq).count()
            if job_count > 0:
                total = Job.select(fn.SUM(Job.budget)).where(Job.equipment == eq).scalar() or 0
                equip_name = f"{eq.marca} {eq.modelo} ({eq.anio})"
                tree.insert('', tk.END, values=(equip_name, job_count, f'${total:,.2f}'))
        
        # Ordenar por cantidad de trabajos
        items = [(tree.set(child, 'trabajos'), child) for child in tree.get_children('')]
        items.sort(reverse=True, key=lambda x: int(x[0]))
        for index, (val, child) in enumerate(items):
            tree.move(child, '', index)
        
        ttk.Button(stats_window, text='Cerrar', command=stats_window.destroy).pack(pady=10)

    def export_equipments_csv(self):
        fn = filedialog.asksaveasfilename(defaultextension='.csv', filetypes=[('CSV','*.csv')], title='Guardar equipos como...')
        if not fn:
            return
        with open(fn,'w',newline='',encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['id','marca','modelo','año','n_serie','propietario','vehiculo','dominio','notas'])
            for eq in Equipment.select():
                writer.writerow([eq.id,eq.marca,eq.modelo,eq.anio,eq.n_serie,eq.propietario or '',eq.vehiculo or '',eq.dominio or '',eq.notes or ''])
        messagebox.showinfo('Exportado', f'Equipos exportados a {fn}')

    # ---------------- UI actions: Trabajos ----------------
    def new_job(self):
        eid = self.get_selected_equipment_id()
        if not eid:
            messagebox.showwarning('Atención', 'Seleccioná un equipo antes de crear un trabajo')
            return
        eq = Equipment.get_by_id(eid)
        JobForm(self, None, equipment=eq, on_save=self.on_job_saved)

    def edit_job(self):
        sel = self.jobs_tree.selection()
        if not sel:
            messagebox.showwarning('Atención', 'Seleccioná un trabajo para editar')
            return
        jid = int(sel[0])
        job = Job.get_by_id(jid)
        JobForm(self, job, on_save=self.on_job_saved)

    def delete_job(self):
        sel = self.jobs_tree.selection()
        if not sel:
            messagebox.showwarning('Atención', 'Seleccioná un trabajo para eliminar')
            return
        jid = int(sel[0])
        if not messagebox.askyesno('Confirmar', '¿Eliminar trabajo?'):
            return
        Job.get_by_id(jid).delete_instance()
        self.on_equipment_select()
        self.refresh_upcoming_services()

    def on_job_saved(self, job):
        self.on_equipment_select()
        self.refresh_upcoming_services()

    def export_jobs_csv(self):
        eid = self.get_selected_equipment_id()
        if not eid:
            messagebox.showwarning('Atención', 'Seleccioná un equipo para exportar trabajos')
            return
        fn = filedialog.asksaveasfilename(defaultextension='.csv', filetypes=[('CSV','*.csv')], title='Guardar trabajos como...')
        if not fn:
            return
        with open(fn,'w',newline='',encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['job_id','equip_id','date_done','description','budget','next_service_date','next_service_days','notes'])
            for job in Job.select().where(Job.equipment == eid):
                writer.writerow([job.id, job.equipment.id, job.date_done.strftime('%Y-%m-%d'), job.description, job.budget, job.next_service_date.strftime('%Y-%m-%d') if job.next_service_date else '', job.next_service_days or '', job.notes or ''])
        messagebox.showinfo('Exportado', f'Trabajos exportados a {fn}')

    # ---------------- Próximos servicios ----------------
    def refresh_upcoming_services(self):
        self.upcoming_tree.delete(*self.upcoming_tree.get_children())
        today = datetime.now().date()
        # buscamos el último trabajo por equipo que tenga next_service_date
        for eq in Equipment.select():
            # seleccionar último job por fecha
            last_job = Job.select().where(Job.equipment == eq).order_by(Job.date_done.desc()).first()
            if not last_job:
                continue
            ns = last_job.next_service_date
            if not ns:
                continue
            days_left = (ns - today).days
            equip_name = f"{eq.marca} {eq.modelo} ({eq.anio})"
            if eq.propietario:
                equip_name += f" - {eq.propietario}"
            self.upcoming_tree.insert('', tk.END, values=(equip_name, ns.strftime('%Y-%m-%d'), days_left, f"${last_job.budget:.2f}"))

    def export_upcoming_csv(self):
        fn = filedialog.asksaveasfilename(defaultextension='.csv', filetypes=[('CSV','*.csv')], title='Guardar próximos servicios como...')
        if not fn:
            return
        today = datetime.now().date()
        with open(fn,'w',newline='',encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['equip_name','next_service_date','days_left','last_budget'])
            for eq in Equipment.select():
                last_job = Job.select().where(Job.equipment == eq).order_by(Job.date_done.desc()).first()
                if not last_job or not last_job.next_service_date:
                    continue
                ns = last_job.next_service_date
                days_left = (ns - today).days
                equip_name = f"{eq.marca} {eq.modelo} ({eq.anio})"
                if eq.propietario:
                    equip_name += f" - {eq.propietario}"
                writer.writerow([equip_name, ns.strftime('%Y-%m-%d'), days_left, f"{last_job.budget:.2f}"])
        messagebox.showinfo('Exportado', f'Próximos servicios exportados a {fn}')

# ---------------------------- Formularios (ventanas) ----------------------------
class EquipmentForm(tk.Toplevel):
    def __init__(self, parent, equipment: Equipment | None, on_save=None):
        super().__init__(parent)
        self.equipment = equipment
        self.on_save = on_save
        title_text = 'Equipo - Nuevo'
        if equipment:
            title_text = f'Equipo - {equipment.marca} {equipment.modelo} ({equipment.anio})'
        self.title(title_text)
        self.geometry('450x480')
        self.build()

    def build(self):
        frm = ttk.Frame(self)
        frm.pack(padx=10, pady=10, fill='both', expand=True)
        
        # Obtener marcas y modelos únicos de la base de datos
        self.marcas_existentes = list(set([eq.marca for eq in Equipment.select()]))
        self.modelos_existentes = list(set([eq.modelo for eq in Equipment.select()]))
        self.propietarios_existentes = list(set([eq.propietario for eq in Equipment.select() if eq.propietario]))
        
        # Campos obligatorios (con asterisco)
        ttk.Label(frm, text='Marca: *').grid(row=0, column=0, sticky='e', pady=4)
        self.marca_var = tk.StringVar()
        self.ent_marca = ttk.Combobox(frm, width=33, textvariable=self.marca_var, values=self.marcas_existentes)
        self.ent_marca.grid(row=0, column=1, sticky='w', pady=4)
        
        # Cuando se selecciona una marca, filtrar modelos relacionados
        self.marca_var.trace('w', self.on_marca_change)

        ttk.Label(frm, text='Modelo: *').grid(row=1, column=0, sticky='e', pady=4)
        self.modelo_var = tk.StringVar()
        self.ent_modelo = ttk.Combobox(frm, width=33, textvariable=self.modelo_var)
        self.ent_modelo.grid(row=1, column=1, sticky='w', pady=4)

        ttk.Label(frm, text='Año: *').grid(row=2, column=0, sticky='e', pady=4)
        # Usar Spinbox para el año con rango sensible
        current_year = datetime.now().year
        self.spin_anio = ttk.Spinbox(frm, from_=1900, to=current_year+5, width=15)
        self.spin_anio.set(current_year)  # Valor por defecto: año actual
        self.spin_anio.grid(row=2, column=1, sticky='w', pady=4)

        ttk.Label(frm, text='N° de Serie: *').grid(row=3, column=0, sticky='e', pady=4)
        self.ent_n_serie = ttk.Entry(frm, width=35)
        self.ent_n_serie.grid(row=3, column=1, sticky='w', pady=4)
        
        # Separador visual
        ttk.Separator(frm, orient='horizontal').grid(row=4, column=0, columnspan=2, sticky='ew', pady=10)
        
        # Campos opcionales
        ttk.Label(frm, text='Propietario:').grid(row=5, column=0, sticky='e', pady=4)
        self.ent_propietario = ttk.Combobox(frm, width=33, values=self.propietarios_existentes)
        self.ent_propietario.grid(row=5, column=1, sticky='w', pady=4)

        ttk.Label(frm, text='Vehículo:').grid(row=6, column=0, sticky='e', pady=4)
        self.ent_vehiculo = ttk.Entry(frm, width=35)
        self.ent_vehiculo.grid(row=6, column=1, sticky='w', pady=4)

        ttk.Label(frm, text='Dominio del vehículo:').grid(row=7, column=0, sticky='e', pady=4)
        self.ent_dominio = ttk.Entry(frm, width=35)
        self.ent_dominio.grid(row=7, column=1, sticky='w', pady=4)

        ttk.Label(frm, text='Notas:').grid(row=8, column=0, sticky='ne', pady=4)
        self.txt_notes = tk.Text(frm, width=35, height=5)
        self.txt_notes.grid(row=8, column=1, sticky='w', pady=4)
        
        # Etiqueta de campos obligatorios
        ttk.Label(frm, text='* Campos obligatorios', font=('TkDefaultFont', 8)).grid(
            row=9, column=0, columnspan=2, pady=5
        )

        # Botones
        btns = ttk.Frame(frm)
        btns.grid(row=10, column=0, columnspan=2, pady=10)
        ttk.Button(btns, text='Guardar', command=self.save).pack(side='left', padx=5)
        ttk.Button(btns, text='Cancelar', command=self.destroy).pack(side='left', padx=5)

        # Cargar datos si estamos editando
        if self.equipment:
            self.marca_var.set(self.equipment.marca)
            self.modelo_var.set(self.equipment.modelo)
            self.spin_anio.set(self.equipment.anio)
            self.ent_n_serie.insert(0, self.equipment.n_serie)
            if self.equipment.propietario: 
                self.ent_propietario.set(self.equipment.propietario)
            if self.equipment.vehiculo: 
                self.ent_vehiculo.insert(0, self.equipment.vehiculo)
            if self.equipment.dominio: 
                self.ent_dominio.insert(0, self.equipment.dominio)
            if self.equipment.notes: 
                self.txt_notes.insert('1.0', self.equipment.notes)
    
    def on_marca_change(self, *args):
        """Cuando se selecciona una marca, filtrar los modelos relacionados"""
        marca_seleccionada = self.marca_var.get()
        if marca_seleccionada:
            # Obtener modelos únicos para esta marca
            modelos_filtrados = list(set([
                eq.modelo for eq in Equipment.select() 
                if eq.marca == marca_seleccionada
            ]))
            self.ent_modelo['values'] = modelos_filtrados

    def save(self):
        # Obtener y validar campos obligatorios
        marca = self.ent_marca.get().strip()
        modelo = self.ent_modelo.get().strip()
        anio_str = self.spin_anio.get().strip()
        n_serie = self.ent_n_serie.get().strip()
        
        # Validación de campos obligatorios
        if not marca:
            messagebox.showwarning('Atención', 'La marca es obligatoria')
            return
        if not modelo:
            messagebox.showwarning('Atención', 'El modelo es obligatorio')
            return
        if not anio_str:
            messagebox.showwarning('Atención', 'El año es obligatorio')
            return
        try:
            anio = int(anio_str)
            if anio < 1900 or anio > 2100:
                raise ValueError
        except ValueError:
            messagebox.showwarning('Atención', 'El año debe ser un número válido (ej: 2023)')
            return
        if not n_serie:
            messagebox.showwarning('Atención', 'El número de serie es obligatorio')
            return
        
        # Obtener campos opcionales
        propietario = self.ent_propietario.get().strip() or None
        vehiculo = self.ent_vehiculo.get().strip() or None
        dominio = self.ent_dominio.get().strip() or None
        notes = self.txt_notes.get('1.0', 'end').strip() or None
        
        # Guardar o actualizar
        if self.equipment:
            self.equipment.marca = marca
            self.equipment.modelo = modelo
            self.equipment.anio = anio
            self.equipment.n_serie = n_serie
            self.equipment.propietario = propietario
            self.equipment.vehiculo = vehiculo
            self.equipment.dominio = dominio
            self.equipment.notes = notes
            self.equipment.save()
        else:
            Equipment.create(
                marca=marca,
                modelo=modelo, 
                anio=anio,
                n_serie=n_serie,
                propietario=propietario,
                vehiculo=vehiculo,
                dominio=dominio,
                notes=notes
            )
        
        if self.on_save:
            self.on_save(True)
        self.destroy()

class JobForm(tk.Toplevel):
    def __init__(self, parent, job: Job | None, equipment: Equipment | None=None, on_save=None):
        super().__init__(parent)
        self.job = job
        self.equipment = equipment
        self.on_save = on_save
        self.title('Trabajo' + (f' - ID {job.id}' if job else ' - Nuevo'))
        self.build()

    def build(self):
        frm = ttk.Frame(self)
        frm.pack(padx=8,pady=8,fill='both',expand=True)

        ttk.Label(frm, text='Equipo:').grid(row=0,column=0,sticky='e')
        if self.equipment:
            equip_text = f"{self.equipment.marca} {self.equipment.modelo} ({self.equipment.anio})"
        elif self.job:
            eq = self.job.equipment
            equip_text = f"{eq.marca} {eq.modelo} ({eq.anio})"
        else:
            equip_text = ""
        self.lbl_eid = ttk.Label(frm, text=equip_text)
        self.lbl_eid.grid(row=0,column=1,sticky='w')

        ttk.Label(frm, text='Fecha del trabajo:').grid(row=1,column=0,sticky='e', pady=5)
        # Usar DateEntry con calendario desplegable
        self.date_entry = DateEntry(frm, 
                                   width=12, 
                                   background='darkblue',
                                   foreground='white', 
                                   borderwidth=2,
                                   locale='es_ES',  # Español
                                   date_pattern='dd/mm/yyyy',  # Formato día/mes/año
                                   showweeknumbers=False)
        self.date_entry.grid(row=1,column=1,sticky='w', pady=5)

        ttk.Label(frm, text='Descripción:').grid(row=2,column=0,sticky='ne', pady=5)
        self.txt_desc = tk.Text(frm, width=50, height=6)
        self.txt_desc.grid(row=2,column=1,sticky='w', pady=5)

        ttk.Label(frm, text='Presupuesto ($):').grid(row=3,column=0,sticky='e', pady=5)
        self.ent_budget = ttk.Entry(frm, width=20)
        self.ent_budget.grid(row=3,column=1,sticky='w', pady=5)

        ttk.Label(frm, text='Días para próximo service:').grid(row=4,column=0,sticky='e', pady=5)
        frm_next = ttk.Frame(frm)
        frm_next.grid(row=4,column=1,sticky='w', pady=5)
        self.ent_next_days = ttk.Entry(frm_next, width=10)
        self.ent_next_days.pack(side='left')
        ttk.Label(frm_next, text='días (opcional)', font=('TkDefaultFont', 9)).pack(side='left', padx=5)

        # Mostrar fecha calculada del próximo service
        ttk.Label(frm, text='Próximo service será:').grid(row=5,column=0,sticky='e', pady=5)
        self.lbl_next_date = ttk.Label(frm, text='(ingrese días para calcular)', foreground='gray')
        self.lbl_next_date.grid(row=5,column=1,sticky='w', pady=5)
        
        # Vincular el cálculo automático
        self.ent_next_days.bind('<KeyRelease>', self.calculate_next_date)
        self.date_entry.bind('<<DateEntrySelected>>', self.calculate_next_date)

        ttk.Label(frm, text='Notas:').grid(row=6,column=0,sticky='ne', pady=5)
        self.txt_notes = tk.Text(frm, width=50, height=4)
        self.txt_notes.grid(row=6,column=1,sticky='w', pady=5)

        btns = ttk.Frame(frm)
        btns.grid(row=7,column=0,columnspan=2,pady=10)
        ttk.Button(btns, text='Guardar', command=self.save).pack(side='left', padx=4)
        ttk.Button(btns, text='Cancelar', command=self.destroy).pack(side='left', padx=4)

        if self.job:
            # Cargar fecha existente
            self.date_entry.set_date(self.job.date_done)
            self.txt_desc.insert('1.0', self.job.description)
            self.ent_budget.insert(0, f"{self.job.budget:.2f}")
            if self.job.next_service_days: 
                self.ent_next_days.insert(0, str(self.job.next_service_days))
                self.calculate_next_date()
            if self.job.notes: 
                self.txt_notes.insert('1.0', self.job.notes)
        else:
            # Fecha por defecto: hoy
            self.date_entry.set_date(datetime.now().date())
            
    def calculate_next_date(self, event=None):
        """Calcula y muestra la fecha del próximo service basada en los días ingresados"""
        try:
            days = int(self.ent_next_days.get())
            if days > 0:
                current_date = self.date_entry.get_date()
                next_date = current_date + timedelta(days=days)
                self.lbl_next_date.config(
                    text=next_date.strftime('%d/%m/%Y'),
                    foreground='darkgreen'
                )
        else:
                self.lbl_next_date.config(
                    text='(días debe ser mayor a 0)',
                    foreground='gray'
                )
        except:
            self.lbl_next_date.config(
                text='(ingrese días para calcular)',
                foreground='gray'
            )

    def save(self):
        # Obtener fecha del calendario (ya viene como objeto date)
        date_done = self.date_entry.get_date()
        desc = self.txt_desc.get('1.0','end').strip()
        try:
            budget = float(self.ent_budget.get().strip() or 0)
        except:
            messagebox.showwarning('Atención', 'Presupuesto inválido')
            return
        next_days_raw = self.ent_next_days.get().strip()
        next_days = int(next_days_raw) if next_days_raw else None
        next_date = calculate_next_service(date_done, next_days) if next_days else None
        notes = self.txt_notes.get('1.0','end').strip() or None

        if self.job:
            self.job.date_done = date_done
            self.job.description = desc
            self.job.budget = budget
            self.job.next_service_days = next_days
            self.job.next_service_date = next_date
            self.job.notes = notes
            self.job.save()
            saved = self.job
        else:
            saved = Job.create(equipment=self.equipment, date_done=date_done, description=desc, budget=budget, next_service_days=next_days, next_service_date=next_date, notes=notes)
        if self.on_save:
            self.on_save(saved)
        self.destroy()

# ---------------------------- Ejecución ----------------------------
if __name__ == '__main__':
    # crear DB si no existe
    init_db()
    app = AgendaApp()
    app.mainloop()
