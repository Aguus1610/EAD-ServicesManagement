"""
AgendaTaller Web - Aplicación web responsive para gestión de trabajos y mantenimientos
Tecnologías: Flask, Bootstrap 5, Chart.js, SQLite
Autor: AgendaTaller
"""

from flask import Flask, render_template, request, redirect, url_for, jsonify, send_file
from datetime import datetime, timedelta
import json
import csv
import io
import os
import logging
import traceback
from peewee import SqliteDatabase, Model, CharField, DateField, TextField, IntegerField, FloatField, ForeignKeyField, fn

# Configurar logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuración de Flask
app = Flask(__name__)
app.secret_key = 'tu-clave-secreta-aqui-cambiar-en-produccion'

# Manejador de errores global
@app.errorhandler(500)
def internal_error(error):
    logger.error(f"Error interno del servidor: {error}")
    logger.error(traceback.format_exc())
    return render_template('error.html', 
                         error_code=500,
                         error_message="Error interno del servidor"), 500

@app.errorhandler(404)
def not_found_error(error):
    logger.warning(f"Página no encontrada: {request.url}")
    return render_template('error.html',
                         error_code=404,
                         error_message="Página no encontrada"), 404

# Ruta para favicon
@app.route('/favicon.ico')
def favicon():
    return send_file('static/img/EAD negro (snf).png', mimetype='image/png')

# Base de datos
DB_FILENAME = 'agenda_taller.db'
db = SqliteDatabase(DB_FILENAME)

# ---------------------------- MODELOS ----------------------------
class BaseModel(Model):
    class Meta:
        database = db

class Equipment(BaseModel):
    marca = CharField()
    modelo = CharField()
    anio = IntegerField()
    n_serie = CharField()
    propietario = CharField(null=True)
    vehiculo = CharField(null=True)
    dominio = CharField(null=True)
    notes = TextField(null=True)

class Job(BaseModel):
    equipment = ForeignKeyField(Equipment, backref='jobs', on_delete='CASCADE')
    date_done = DateField()
    description = TextField()
    budget = FloatField(default=0.0)
    next_service_days = IntegerField(null=True)
    next_service_date = DateField(null=True)
    notes = TextField(null=True)

def init_db():
    """Inicializar base de datos"""
    db.connect()
    db.create_tables([Equipment, Job])

# ---------------------------- RUTAS PRINCIPALES ----------------------------

@app.route('/')
def index():
    """Página principal - Dashboard"""
    total_equipment = Equipment.select().count()
    total_jobs = Job.select().count()
    
    # Próximos servicios
    today = datetime.now().date()
    upcoming_services = []
    total_upcoming = 0
    services_vencidos = 0
    
    for eq in Equipment.select():
        last_job = Job.select().where(Job.equipment == eq).order_by(Job.date_done.desc()).first()
        if last_job and last_job.next_service_date:
            days_left = (last_job.next_service_date - today).days
            
            # Contar todos los servicios próximos (30 días o menos)
            if days_left <= 30:
                total_upcoming += 1
            
            # Contar servicios vencidos
            if days_left < 0:
                services_vencidos += 1
                
            upcoming_services.append({
                'equipment': f"{eq.marca} {eq.modelo} ({eq.anio})",
                'propietario': eq.propietario,
                'date': last_job.next_service_date.strftime('%d/%m/%Y'),
                'days_left': days_left,
                'budget': last_job.budget,
                'status': 'danger' if days_left < 0 else 'warning' if days_left < 7 else 'success'
            })
    
    upcoming_services.sort(key=lambda x: x['days_left'])
    
    return render_template('dashboard.html',
                         total_equipment=total_equipment,
                         total_jobs=total_jobs,
                         total_upcoming=total_upcoming,
                         services_vencidos=services_vencidos,
                         upcoming_services=upcoming_services[:10])

# ---------------------------- RUTAS DE EQUIPOS ----------------------------

@app.route('/equipos')
def equipos_list():
    """Lista de equipos con búsqueda"""
    search = request.args.get('search', '')
    equipos = Equipment.select().order_by(Equipment.marca, Equipment.modelo)
    
    if search:
        equipos = equipos.where(
            (Equipment.marca.contains(search)) |
            (Equipment.modelo.contains(search)) |
            (Equipment.n_serie.contains(search)) |
            (Equipment.propietario.contains(search)) |
            (Equipment.dominio.contains(search))
        )
    
    equipos_list = []
    for eq in equipos:
        job_count = Job.select().where(Job.equipment == eq).count()
        total_spent = Job.select(fn.SUM(Job.budget)).where(Job.equipment == eq).scalar() or 0
        
        equipos_list.append({
            'id': eq.id,
            'marca': eq.marca,
            'modelo': eq.modelo,
            'anio': eq.anio,
            'n_serie': eq.n_serie,
            'propietario': eq.propietario or '-',
            'vehiculo': eq.vehiculo or '-',
            'dominio': eq.dominio or '-',
            'job_count': job_count,
            'total_spent': total_spent
        })
    
    return render_template('equipos.html', equipos=equipos_list, search=search)

@app.route('/equipo/<int:equipo_id>')
def equipo_detail(equipo_id):
    """Detalle de equipo con trabajos"""
    equipo = Equipment.get_by_id(equipo_id)
    trabajos = Job.select().where(Job.equipment == equipo).order_by(Job.date_done.desc())
    
    trabajos_list = []
    total_gastado = 0
    
    for job in trabajos:
        trabajos_list.append({
            'id': job.id,
            'date': job.date_done.strftime('%d/%m/%Y'),
            'description': job.description,
            'budget': job.budget,
            'next_service': job.next_service_date.strftime('%d/%m/%Y') if job.next_service_date else '-',
            'notes': job.notes or ''
        })
        total_gastado += job.budget
    
    promedio = total_gastado / len(trabajos_list) if trabajos_list else 0
    
    return render_template('equipo_detail.html',
                         equipo=equipo,
                         trabajos=trabajos_list,
                         total_gastado=total_gastado,
                         promedio=promedio)

@app.route('/equipo/nuevo', methods=['GET', 'POST'])
def equipo_new():
    """Crear nuevo equipo"""
    if request.method == 'POST':
        Equipment.create(
            marca=request.form['marca'],
            modelo=request.form['modelo'],
            anio=int(request.form['anio']),
            n_serie=request.form['n_serie'],
            propietario=request.form.get('propietario') or None,
            vehiculo=request.form.get('vehiculo') or None,
            dominio=request.form.get('dominio') or None,
            notes=request.form.get('notes') or None
        )
        return redirect(url_for('equipos_list'))
    
    # Obtener valores únicos para autocompletado
    marcas = list(set([eq.marca for eq in Equipment.select()]))
    propietarios = list(set([eq.propietario for eq in Equipment.select() if eq.propietario]))
    
    return render_template('equipo_form.html', 
                         equipo=None,
                         marcas=json.dumps(marcas),
                         propietarios=json.dumps(propietarios))

@app.route('/equipo/<int:equipo_id>/editar', methods=['GET', 'POST'])
def equipo_edit(equipo_id):
    """Editar equipo existente"""
    equipo = Equipment.get_by_id(equipo_id)
    
    if request.method == 'POST':
        equipo.marca = request.form['marca']
        equipo.modelo = request.form['modelo']
        equipo.anio = int(request.form['anio'])
        equipo.n_serie = request.form['n_serie']
        equipo.propietario = request.form.get('propietario') or None
        equipo.vehiculo = request.form.get('vehiculo') or None
        equipo.dominio = request.form.get('dominio') or None
        equipo.notes = request.form.get('notes') or None
        equipo.save()
        return redirect(url_for('equipo_detail', equipo_id=equipo_id))
    
    marcas = list(set([eq.marca for eq in Equipment.select()]))
    propietarios = list(set([eq.propietario for eq in Equipment.select() if eq.propietario]))
    
    return render_template('equipo_form.html',
                         equipo=equipo,
                         marcas=json.dumps(marcas),
                         propietarios=json.dumps(propietarios))

@app.route('/equipo/<int:equipo_id>/eliminar', methods=['POST'])
def equipo_delete(equipo_id):
    """Eliminar equipo"""
    try:
        equipo = Equipment.get_by_id(equipo_id)
        # Eliminar equipo y trabajos asociados de forma recursiva
        equipo.delete_instance(recursive=True)
        return redirect(url_for('equipos_list'))
    except Exception as e:
        logger.error(f"Error eliminando equipo {equipo_id}: {e}")
        logger.error(traceback.format_exc())
        return redirect(url_for('equipos_list'))

# ---------------------------- RUTAS DE TRABAJOS ----------------------------

@app.route('/trabajos')
def trabajos_list():
    """Lista de todos los trabajos con filtros"""
    # Obtener parámetros de filtro
    search = request.args.get('search', '')
    equipo_id = request.args.get('equipo_id', '')
    fecha_desde = request.args.get('fecha_desde', '')
    fecha_hasta = request.args.get('fecha_hasta', '')
    
    # Query base
    trabajos = Job.select().join(Equipment).order_by(Job.date_done.desc())
    
    # Aplicar filtros
    if search:
        trabajos = trabajos.where(Job.description.contains(search))
    if equipo_id:
        trabajos = trabajos.where(Job.equipment == equipo_id)
    if fecha_desde:
        trabajos = trabajos.where(Job.date_done >= datetime.strptime(fecha_desde, '%Y-%m-%d').date())
    if fecha_hasta:
        trabajos = trabajos.where(Job.date_done <= datetime.strptime(fecha_hasta, '%Y-%m-%d').date())
    
    # Preparar datos para la vista
    trabajos_list = []
    total_trabajos = 0
    total_presupuesto = 0
    
    for job in trabajos:
        eq = job.equipment
        trabajos_list.append({
            'id': job.id,
            'date': job.date_done.strftime('%d/%m/%Y'),
            'equipo': f"{eq.marca} {eq.modelo} ({eq.anio})",
            'equipo_id': eq.id,
            'propietario': eq.propietario or '-',
            'description': job.description,
            'budget': job.budget,
            'next_service': job.next_service_date.strftime('%d/%m/%Y') if job.next_service_date else '-',
            'days_until': (job.next_service_date - datetime.now().date()).days if job.next_service_date else None,
            'notes': job.notes or ''
        })
        total_trabajos += 1
        total_presupuesto += job.budget
    
    # Obtener lista de equipos para el filtro
    equipos_filter = []
    for eq in Equipment.select().order_by(Equipment.marca, Equipment.modelo):
        equipos_filter.append({
            'id': eq.id,
            'nombre': f"{eq.marca} {eq.modelo} ({eq.anio})"
        })
    
    return render_template('trabajos.html', 
                         trabajos=trabajos_list,
                         total_trabajos=total_trabajos,
                         total_presupuesto=total_presupuesto,
                         equipos_filter=equipos_filter,
                         search=search,
                         equipo_id=equipo_id,
                         fecha_desde=fecha_desde,
                         fecha_hasta=fecha_hasta)

@app.route('/trabajo/nuevo', methods=['GET', 'POST'])
def trabajo_new_global():
    """Crear nuevo trabajo desde la sección global"""
    if request.method == 'POST':
        equipo_id = request.form['equipo_id']
        equipo = Equipment.get_by_id(equipo_id)
        date_done = datetime.strptime(request.form['date_done'], '%Y-%m-%d').date()
        next_days = int(request.form['next_service_days']) if request.form.get('next_service_days') else None
        next_date = date_done + timedelta(days=next_days) if next_days else None
        
        Job.create(
            equipment=equipo,
            date_done=date_done,
            description=request.form['description'],
            budget=float(request.form.get('budget', 0)),
            next_service_days=next_days,
            next_service_date=next_date,
            notes=request.form.get('notes') or None
        )
        return redirect(url_for('trabajos_list'))
    
    # Obtener lista de equipos
    equipos = []
    for eq in Equipment.select().order_by(Equipment.marca, Equipment.modelo):
        equipos.append({
            'id': eq.id,
            'nombre': f"{eq.marca} {eq.modelo} ({eq.anio}) - {eq.n_serie}"
        })
    
    return render_template('trabajo_form_global.html', equipos=equipos)

@app.route('/trabajo/nuevo/<int:equipo_id>', methods=['GET', 'POST'])
def trabajo_new(equipo_id):
    """Crear nuevo trabajo"""
    equipo = Equipment.get_by_id(equipo_id)
    
    if request.method == 'POST':
        date_done = datetime.strptime(request.form['date_done'], '%Y-%m-%d').date()
        next_days = int(request.form['next_service_days']) if request.form.get('next_service_days') else None
        next_date = date_done + timedelta(days=next_days) if next_days else None
        
        Job.create(
            equipment=equipo,
            date_done=date_done,
            description=request.form['description'],
            budget=float(request.form.get('budget', 0)),
            next_service_days=next_days,
            next_service_date=next_date,
            notes=request.form.get('notes') or None
        )
        return redirect(url_for('equipo_detail', equipo_id=equipo_id))
    
    return render_template('trabajo_form.html', equipo=equipo, trabajo=None)

@app.route('/trabajo/<int:trabajo_id>/editar', methods=['GET', 'POST'])
def trabajo_edit(trabajo_id):
    """Editar trabajo existente"""
    trabajo = Job.get_by_id(trabajo_id)
    
    if request.method == 'POST':
        trabajo.date_done = datetime.strptime(request.form['date_done'], '%Y-%m-%d').date()
        trabajo.description = request.form['description']
        trabajo.budget = float(request.form.get('budget', 0))
        
        next_days = int(request.form['next_service_days']) if request.form.get('next_service_days') else None
        trabajo.next_service_days = next_days
        trabajo.next_service_date = trabajo.date_done + timedelta(days=next_days) if next_days else None
        trabajo.notes = request.form.get('notes') or None
        trabajo.save()
        
        return redirect(url_for('equipo_detail', equipo_id=trabajo.equipment.id))
    
    return render_template('trabajo_form.html', equipo=trabajo.equipment, trabajo=trabajo)

@app.route('/trabajo/<int:trabajo_id>/eliminar', methods=['POST'])
def trabajo_delete(trabajo_id):
    """Eliminar trabajo"""
    try:
        trabajo = Job.get_by_id(trabajo_id)
        equipo_id = trabajo.equipment.id
        trabajo.delete_instance()
        
        # Determinar desde dónde se llamó para redirigir correctamente
        referer = request.headers.get('Referer', '')
        if '/trabajos' in referer:
            # Si viene de la página de trabajos, redirigir ahí
            return redirect(url_for('trabajos_list'))
        else:
            # Si viene del detalle del equipo, redirigir ahí
            return redirect(url_for('equipo_detail', equipo_id=equipo_id))
    except Exception as e:
        logger.error(f"Error eliminando trabajo {trabajo_id}: {e}")
        logger.error(traceback.format_exc())
        # En caso de error, redirigir a trabajos con mensaje de error
        return redirect(url_for('trabajos_list'))

# ---------------------------- RUTAS DE ESTADÍSTICAS ----------------------------

@app.route('/estadisticas')
def estadisticas():
    """Vista de estadísticas con gráficos"""
    # Estadísticas generales
    total_equipment = Equipment.select().count()
    total_jobs = Job.select().count()
    total_budget = Job.select(fn.SUM(Job.budget)).scalar() or 0
    avg_budget = total_budget / total_jobs if total_jobs > 0 else 0
    
    # Top equipos por gastos
    top_equipos = []
    for eq in Equipment.select():
        job_count = Job.select().where(Job.equipment == eq).count()
        if job_count > 0:
            total = Job.select(fn.SUM(Job.budget)).where(Job.equipment == eq).scalar() or 0
            top_equipos.append({
                'name': f"{eq.marca} {eq.modelo}",
                'jobs': job_count,
                'total': total
            })
    
    top_equipos.sort(key=lambda x: x['total'], reverse=True)
    top_equipos = top_equipos[:10]
    
    # Gastos por mes (últimos 12 meses)
    gastos_mes = []
    for i in range(11, -1, -1):
        fecha = datetime.now() - timedelta(days=i*30)
        mes_inicio = fecha.replace(day=1)
        if i == 0:
            mes_fin = datetime.now().date()
        else:
            siguiente_mes = mes_inicio + timedelta(days=32)
            mes_fin = siguiente_mes.replace(day=1) - timedelta(days=1)
        
        total_mes = Job.select(fn.SUM(Job.budget)).where(
            (Job.date_done >= mes_inicio.date()) & 
            (Job.date_done <= mes_fin)
        ).scalar() or 0
        
        gastos_mes.append({
            'month': fecha.strftime('%b %Y'),
            'total': float(total_mes)
        })
    
    # Distribución por marca
    marcas_dist = []
    for marca in Equipment.select(Equipment.marca).distinct():
        count = Equipment.select().where(Equipment.marca == marca.marca).count()
        marcas_dist.append({
            'marca': marca.marca,
            'count': count
        })
    
    return render_template('estadisticas.html',
                         total_equipment=total_equipment,
                         total_jobs=total_jobs,
                         total_budget=total_budget,
                         avg_budget=avg_budget,
                         top_equipos=json.dumps(top_equipos),
                         gastos_mes=json.dumps(gastos_mes),
                         marcas_dist=json.dumps(marcas_dist))

# ---------------------------- API ENDPOINTS ----------------------------

@app.route('/api/modelos/<marca>')
def api_modelos(marca):
    """API: Obtener modelos por marca"""
    modelos = list(set([
        eq.modelo for eq in Equipment.select() 
        if eq.marca == marca
    ]))
    return jsonify(modelos)

@app.route('/api/export/equipos')
def export_equipos():
    """Exportar equipos a CSV"""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['ID', 'Marca', 'Modelo', 'Año', 'N° Serie', 'Propietario', 'Vehículo', 'Dominio', 'Notas'])
    
    for eq in Equipment.select():
        writer.writerow([
            eq.id, eq.marca, eq.modelo, eq.anio, eq.n_serie,
            eq.propietario or '', eq.vehiculo or '', eq.dominio or '', eq.notes or ''
        ])
    
    output.seek(0)
    return send_file(
        io.BytesIO(output.getvalue().encode('utf-8')),
        mimetype='text/csv',
        as_attachment=True,
        download_name=f'equipos_{datetime.now().strftime("%Y%m%d")}.csv'
    )

@app.route('/api/export/trabajos')
def export_trabajos():
    """Exportar trabajos a CSV"""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['ID', 'Fecha', 'Equipo', 'Marca', 'Modelo', 'Año', 'Propietario', 'Descripción', 'Presupuesto', 'Próximo Service', 'Días para Service', 'Notas'])
    
    for job in Job.select().join(Equipment).order_by(Job.date_done.desc()):
        eq = job.equipment
        writer.writerow([
            job.id,
            job.date_done.strftime('%d/%m/%Y'),
            f"{eq.marca} {eq.modelo}",
            eq.marca,
            eq.modelo,
            eq.anio,
            eq.propietario or '',
            job.description,
            job.budget,
            job.next_service_date.strftime('%d/%m/%Y') if job.next_service_date else '',
            job.next_service_days or '',
            job.notes or ''
        ])
    
    output.seek(0)
    return send_file(
        io.BytesIO(output.getvalue().encode('utf-8')),
        mimetype='text/csv',
        as_attachment=True,
        download_name=f'trabajos_{datetime.now().strftime("%Y%m%d")}.csv'
    )

@app.route('/api/backup')
def backup_database():
    """Descarga una copia de seguridad de la base de datos"""
    try:
        # Verificar que el archivo existe
        if not os.path.exists(DB_FILENAME):
            return jsonify({'error': 'Base de datos no encontrada'}), 404
        
        # Enviar el archivo de base de datos
        return send_file(
            DB_FILENAME,
            mimetype='application/x-sqlite3',
            as_attachment=True,
            download_name=f'backup_ead_{datetime.now().strftime("%Y%m%d_%H%M%S")}.db'
        )
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ---------------------------- INICIALIZACIÓN ----------------------------

if __name__ == '__main__':
    init_db()
    # Para desarrollo local
    import os
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=False, host='0.0.0.0', port=port)
    
    # Para producción en Render, se usará gunicorn
