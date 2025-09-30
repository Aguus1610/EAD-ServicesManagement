"""
AgendaTaller Web - Aplicación web responsive para gestión de trabajos y mantenimientos
Tecnologías: Flask, Bootstrap 5, Chart.js, SQLite
Autor: AgendaTaller
"""

from flask import Flask, render_template, request, redirect, url_for, jsonify, send_file, session
from datetime import datetime, timedelta, date
import json
import csv
import io
import os
import logging
import traceback
import pandas as pd
import openpyxl
from werkzeug.utils import secure_filename
import requests
from pytz import timezone
from bs4 import BeautifulSoup
import re
from peewee import SqliteDatabase, Model, CharField, DateField, TextField, IntegerField, FloatField, ForeignKeyField, fn

# Configurar logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuración para subida de archivos
UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'xlsx', 'xls'}
MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB max file size

# Crear carpeta de uploads si no existe
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

# Configuración de Flask
app = Flask(__name__)
app.secret_key = 'tu-clave-secreta-aqui-cambiar-en-produccion'
app.config['MAX_CONTENT_LENGTH'] = MAX_CONTENT_LENGTH

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

class Client(BaseModel):
    """Modelo para clientes"""
    nombre = CharField()
    telefono = CharField(null=True)
    direccion = TextField(null=True)
    cuit_cuil = CharField(null=True)
    email = CharField(null=True)
    notes = TextField(null=True)
    created_at = DateField(default=datetime.now().date)
    
    class Meta:
        table_name = 'clients'

class Equipment(BaseModel):
    marca = CharField()
    modelo = CharField()
    anio = IntegerField()
    n_serie = CharField()
    propietario = CharField(null=True)  # Mantener por compatibilidad
    client = ForeignKeyField(Client, null=True, backref='equipments')  # Nueva relación
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
    
    # Verificar si necesitamos migrar la base de datos
    needs_migration = False
    
    try:
        # Intentar crear las tablas
        db.create_tables([Client, Equipment, Job], safe=True)
        
        # Verificar si la columna client_id existe en Equipment
        cursor = db.execute_sql("PRAGMA table_info(equipment)")
        columns = [column[1] for column in cursor.fetchall()]
        
        if 'client_id' not in columns:
            needs_migration = True
            logger.info("Detectada necesidad de migración - agregando columna client_id")
            
            # Agregar la columna client_id
            db.execute_sql("ALTER TABLE equipment ADD COLUMN client_id INTEGER")
            
            # Ahora migrar los datos
            migrate_propietarios_to_clients()
        else:
            # La columna ya existe, verificar si hay datos para migrar
            migrate_propietarios_to_clients()
        
    except Exception as e:
        logger.error(f"Error en inicialización de base de datos: {e}")
        # Si hay error, intentar crear tablas desde cero
        db.create_tables([Client, Equipment, Job])

def migrate_propietarios_to_clients():
    """Migra propietarios existentes a la tabla de clientes"""
    try:
        # Usar SQL directo para obtener propietarios únicos
        cursor = db.execute_sql("""
            SELECT DISTINCT propietario 
            FROM equipment 
            WHERE propietario IS NOT NULL 
            AND propietario != '' 
            AND (client_id IS NULL OR client_id = 0)
        """)
        
        propietarios_unicos = [row[0] for row in cursor.fetchall()]
        
        for propietario_nombre in propietarios_unicos:
            if propietario_nombre:
                # Verificar si ya existe el cliente
                try:
                    client = Client.get(Client.nombre == propietario_nombre)
                except Client.DoesNotExist:
                    # Crear nuevo cliente
                    client = Client.create(
                        nombre=propietario_nombre,
                        notes=f"Cliente migrado automáticamente desde propietario"
                    )
                    logger.info(f"Cliente creado: {propietario_nombre}")
                
                # Actualizar todos los equipos con este propietario usando SQL directo
                db.execute_sql("""
                    UPDATE equipment 
                    SET client_id = ? 
                    WHERE propietario = ? 
                    AND (client_id IS NULL OR client_id = 0)
                """, [client.id, propietario_nombre])
        
        logger.info("Migración de propietarios a clientes completada")
        
    except Exception as e:
        logger.error(f"Error en migración de propietarios: {e}")

# ---------------------------- FUNCIONES DE IMPORTACIÓN EXCEL ----------------------------

def allowed_file(filename):
    """Verifica si el archivo tiene una extensión permitida"""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

class ExcelImporter:
    """Importador de datos desde archivos Excel"""
    
    def __init__(self, file_path):
        self.file_path = file_path
        self.parsed_data = []
        self.import_summary = {
            'clients_created': 0,
            'equipments_created': 0,
            'equipments_updated': 0,
            'jobs_created': 0,
            'errors': []
        }
    
    def parse_excel(self):
        """Parsea el archivo Excel y extrae los datos"""
        try:
            workbook = openpyxl.load_workbook(self.file_path)
            
            for sheet_name in workbook.sheetnames:
                if sheet_name.strip() and sheet_name != 'Hoja5':
                    logger.info(f"Procesando cliente: {sheet_name}")
                    client_data = self._parse_sheet(sheet_name)
                    if client_data:
                        self.parsed_data.extend(client_data)
                        logger.info(f"  -> {len(client_data)} registros extraídos")
            
            return True
        except Exception as e:
            logger.error(f"Error parseando Excel: {e}")
            self.import_summary['errors'].append(f"Error parseando Excel: {str(e)}")
            return False
    
    def _parse_sheet(self, sheet_name):
        """Parsea una hoja específica del Excel"""
        try:
            df = pd.read_excel(self.file_path, sheet_name=sheet_name, header=None)
            
            if df.empty:
                return []
            
            # Encontrar fila de encabezados
            header_row = self._find_header_row(df)
            if header_row is None:
                return []
            
            return self._extract_equipment_data(df, sheet_name, header_row)
            
        except Exception as e:
            logger.error(f"Error procesando {sheet_name}: {e}")
            return []
    
    def _find_header_row(self, df):
        """Encuentra la fila que contiene los encabezados"""
        for idx, row in df.iterrows():
            row_str = ' '.join([str(cell).upper() for cell in row if pd.notna(cell)])
            if 'EQUIPO' in row_str and ('FECHA' in row_str or 'MANO' in row_str):
                return idx
        return None
    
    def _extract_equipment_data(self, df, client_name, header_row):
        """Extrae los datos de equipos y trabajos"""
        data = []
        current_equipment = None
        current_date = None
        current_work = None  # Trabajo actual en construcción
        
        for idx in range(header_row + 1, len(df)):
            row = df.iloc[idx]
            
            equipo = self._clean_text(row.iloc[0]) if len(row) > 0 and pd.notna(row.iloc[0]) else None
            fecha = self._parse_date(row.iloc[1]) if len(row) > 1 and pd.notna(row.iloc[1]) else None
            repuestos = self._clean_text(row.iloc[2]) if len(row) > 2 and pd.notna(row.iloc[2]) else None
            mano_obra = self._clean_text(row.iloc[3]) if len(row) > 3 and pd.notna(row.iloc[3]) else None
            
            # Si hay un nuevo equipo, actualizar el equipo actual
            if equipo:
                current_equipment = equipo
            
            # Si hay una nueva fecha, crear un nuevo trabajo
            if fecha and current_equipment:
                # Finalizar trabajo anterior si existe
                if current_work and (current_work['repuestos'] or current_work['mano_obra']):
                    current_work['description'] = self._build_description(
                        current_work['repuestos'], 
                        current_work['mano_obra']
                    )
                    data.append(current_work)
                
                # Iniciar nuevo trabajo
                current_date = fecha
                current_work = {
                    'client': client_name,
                    'equipment': current_equipment,
                    'date': current_date,
                    'repuestos': repuestos or '',
                    'mano_obra': mano_obra or '',
                }
            
            # Si no hay fecha pero hay repuestos/mano de obra, agregar al trabajo actual
            elif (repuestos or mano_obra) and current_work:
                if repuestos:
                    if current_work['repuestos']:
                        current_work['repuestos'] += f"\n{repuestos}"
                    else:
                        current_work['repuestos'] = repuestos
                
                if mano_obra:
                    if current_work['mano_obra']:
                        current_work['mano_obra'] += f"\n{mano_obra}"
                    else:
                        current_work['mano_obra'] = mano_obra
        
        # Finalizar último trabajo si existe
        if current_work and (current_work['repuestos'] or current_work['mano_obra']):
            current_work['description'] = self._build_description(
                current_work['repuestos'], 
                current_work['mano_obra']
            )
            data.append(current_work)
        
        return data
    
    def _clean_text(self, text):
        """Limpia y normaliza texto"""
        if pd.isna(text):
            return None
        text = str(text).strip()
        return text if text and text.lower() not in ['nan', 'none', ''] else None
    
    def _parse_date(self, date_value):
        """Parsea fechas en diferentes formatos"""
        if pd.isna(date_value):
            return None
            
        if isinstance(date_value, (datetime, date)):
            return date_value.date() if isinstance(date_value, datetime) else date_value
        
        date_str = str(date_value).strip()
        formats = ['%Y-%m-%d', '%d/%m/%Y', '%m/%d/%Y', '%Y-%m-%d %H:%M:%S']
        
        for fmt in formats:
            try:
                parsed_date = datetime.strptime(date_str, fmt)
                return parsed_date.date()
            except ValueError:
                continue
        
        return None
    
    def _build_description(self, repuestos, mano_obra):
        """Construye la descripción del trabajo"""
        description_parts = []
        
        if mano_obra:
            description_parts.append(f"MANO DE OBRA:\n{mano_obra}")
        
        if repuestos:
            description_parts.append(f"REPUESTOS:\n{repuestos}")
        
        return "\n\n".join(description_parts)
    
    def import_to_database(self):
        """Importa los datos parseados a la base de datos"""
        if not self.parsed_data:
            self.import_summary['errors'].append("No hay datos para importar")
            return False
        
        try:
            for record in self.parsed_data:
                try:
                    # Crear o actualizar equipo
                    equipment = self._create_or_update_equipment(record)
                    
                    # Crear trabajo
                    if equipment:
                        self._create_job(equipment, record)
                        
                except Exception as e:
                    error_msg = f"Error importando registro {record.get('equipment', 'Unknown')}: {str(e)}"
                    logger.error(error_msg)
                    self.import_summary['errors'].append(error_msg)
            
            return True
            
        except Exception as e:
            logger.error(f"Error en importación: {e}")
            self.import_summary['errors'].append(f"Error general en importación: {str(e)}")
            return False
    
    def _create_or_update_equipment(self, record):
        """Crea o actualiza un equipo"""
        try:
            # Extraer información del equipo del nombre
            equipment_name = record['equipment']
            client_name = record['client']
            
            # Crear o encontrar cliente
            client = self._create_or_get_client(client_name)
            
            # Intentar encontrar equipo existente
            try:
                equipment = Equipment.get(Equipment.n_serie == equipment_name)
                
                # Actualizar cliente si no está asignado
                if not equipment.client and client:
                    equipment.client = client
                    equipment.propietario = client_name  # Mantener por compatibilidad
                    equipment.save()
                
                self.import_summary['equipments_updated'] += 1
                return equipment
            except Equipment.DoesNotExist:
                # Crear nuevo equipo
                equipment = Equipment.create(
                    marca=self._extract_brand(equipment_name),
                    modelo=self._extract_model(equipment_name),
                    anio=datetime.now().year,  # Año por defecto
                    n_serie=equipment_name,
                    propietario=client_name,  # Mantener por compatibilidad
                    client=client,  # Nueva relación con cliente
                    vehiculo=None,
                    dominio=None,
                    notes=f"Importado desde Excel - Cliente: {client_name}"
                )
                self.import_summary['equipments_created'] += 1
                return equipment
                
        except Exception as e:
            logger.error(f"Error creando equipo {record['equipment']}: {e}")
            return None
    
    def _create_or_get_client(self, client_name):
        """Crea o encuentra un cliente por nombre"""
        try:
            if not client_name or client_name.strip() == '':
                return None
            
            client_name = client_name.strip()
            
            # Intentar encontrar cliente existente
            try:
                client = Client.get(Client.nombre == client_name)
                logger.info(f"Cliente encontrado: {client_name}")
                return client
            except Client.DoesNotExist:
                # Crear nuevo cliente
                client = Client.create(
                    nombre=client_name,
                    notes=f"Cliente creado automáticamente desde importación Excel"
                )
                logger.info(f"Cliente creado: {client_name}")
                
                # Actualizar resumen de importación
                self.import_summary['clients_created'] += 1
                
                return client
                
        except Exception as e:
            logger.error(f"Error creando/obteniendo cliente {client_name}: {e}")
            return None
    
    def _extract_brand(self, equipment_name):
        """Extrae la marca del nombre del equipo"""
        # Lógica simple para extraer marca
        parts = equipment_name.split()
        if len(parts) > 0:
            return parts[0]
        return "Sin especificar"
    
    def _extract_model(self, equipment_name):
        """Extrae el modelo del nombre del equipo"""
        # Lógica simple para extraer modelo
        parts = equipment_name.split()
        if len(parts) > 1:
            return ' '.join(parts[1:])
        return "Sin especificar"
    
    def _create_job(self, equipment, record):
        """Crea un trabajo para el equipo"""
        try:
            # Verificar si ya existe un trabajo exacto (mismo equipo, misma fecha)
            existing_job = Job.select().where(
                (Job.equipment == equipment) &
                (Job.date_done == record['date'])
            ).first()
            
            if existing_job:
                logger.info(f"Trabajo ya existe para {equipment.n_serie} en fecha {record['date']} - actualizando descripción")
                # Actualizar descripción si es diferente
                if existing_job.description != record['description']:
                    existing_job.description = record['description']
                    existing_job.notes = f"Actualizado desde Excel - Cliente: {record['client']}"
                    existing_job.save()
                return existing_job
            
            # Crear nuevo trabajo solo si no existe uno para esa fecha
            job = Job.create(
                equipment=equipment,
                date_done=record['date'],
                description=record['description'],
                budget=0.0,  # Sin presupuesto por defecto
                next_service_days=None,
                next_service_date=None,
                notes=f"Importado desde Excel - Cliente: {record['client']}"
            )
            self.import_summary['jobs_created'] += 1
            logger.info(f"Trabajo creado para {equipment.n_serie} en fecha {record['date']}")
            return job
            
        except Exception as e:
            logger.error(f"Error creando trabajo: {e}")
            return None

def clean_duplicate_jobs():
    """Limpia trabajos duplicados (mismo equipo, misma fecha)"""
    try:
        logger.info("Iniciando limpieza de trabajos duplicados")
        
        # Obtener todos los trabajos agrupados por equipo y fecha
        jobs = Job.select().order_by(Job.equipment, Job.date_done, Job.id)
        
        duplicates_removed = 0
        current_key = None
        jobs_to_keep = []
        jobs_to_remove = []
        
        for job in jobs:
            key = (job.equipment.id, job.date_done)
            
            if key == current_key:
                # Es un duplicado, marcarlo para eliminación
                jobs_to_remove.append(job)
                duplicates_removed += 1
            else:
                # Es el primer trabajo de este equipo/fecha, mantenerlo
                current_key = key
                jobs_to_keep.append(job)
        
        # Eliminar duplicados
        for job in jobs_to_remove:
            logger.info(f"Eliminando trabajo duplicado: {job.equipment.n_serie} - {job.date_done}")
            job.delete_instance()
        
        logger.info(f"Limpieza completada: {duplicates_removed} trabajos duplicados eliminados")
        return duplicates_removed
        
    except Exception as e:
        logger.error(f"Error limpiando trabajos duplicados: {e}")
        return 0

# ---------------------------- FUNCIONES DE INFORMACIÓN ----------------------------

def get_current_datetime():
    """Obtiene la fecha y hora actual en Argentina"""
    try:
        # Zona horaria de Argentina
        argentina_tz = timezone('America/Argentina/Buenos_Aires')
        now = datetime.now(argentina_tz)
        
        return {
            'date': now.strftime('%d/%m/%Y'),
            'time': now.strftime('%H:%M:%S'),
            'datetime': now.strftime('%d/%m/%Y %H:%M:%S'),
            'day_name': now.strftime('%A'),
            'month_name': now.strftime('%B')
        }
    except Exception as e:
        logger.error(f"Error obteniendo fecha/hora: {e}")
        # Fallback a hora local
        now = datetime.now()
        return {
            'date': now.strftime('%d/%m/%Y'),
            'time': now.strftime('%H:%M:%S'),
            'datetime': now.strftime('%d/%m/%Y %H:%M:%S'),
            'day_name': now.strftime('%A'),
            'month_name': now.strftime('%B')
        }

def get_dollar_rate():
    """Obtiene la cotización del dólar desde el Banco de la Nación Argentina"""
    try:
        # URL del Banco Nación Argentina
        url = 'https://www.bna.com.ar'
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        
        logger.info("Obteniendo cotización del Banco Nación Argentina...")
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code == 200:
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Buscar la tabla de cotizaciones o elementos específicos del BNA
            # Intentar diferentes selectores comunes para cotizaciones
            cotizacion_encontrada = False
            compra = 0
            venta = 0
            
            # Método 1: Buscar por texto "Dólar" y extraer valores numéricos
            dollar_elements = soup.find_all(text=re.compile(r'[Dd]ólar|USD', re.IGNORECASE))
            
            for element in dollar_elements:
                parent = element.parent
                if parent:
                    # Buscar números en el elemento padre y hermanos
                    siblings = parent.find_next_siblings()
                    for sibling in siblings[:4]:  # Revisar los próximos 4 elementos
                        if sibling.get_text():
                            numbers = re.findall(r'\d+[,.]?\d*', sibling.get_text())
                            if len(numbers) >= 2:
                                try:
                                    compra = float(numbers[0].replace(',', '.'))
                                    venta = float(numbers[1].replace(',', '.'))
                                    cotizacion_encontrada = True
                                    break
                                except ValueError:
                                    continue
                    if cotizacion_encontrada:
                        break
            
            # Método 2: Buscar en tablas
            if not cotizacion_encontrada:
                tables = soup.find_all('table')
                for table in tables:
                    rows = table.find_all('tr')
                    for row in rows:
                        cells = row.find_all(['td', 'th'])
                        row_text = ' '.join([cell.get_text().strip() for cell in cells])
                        
                        if re.search(r'[Dd]ólar|USD', row_text, re.IGNORECASE):
                            numbers = re.findall(r'\d+[,.]?\d*', row_text)
                            if len(numbers) >= 2:
                                try:
                                    compra = float(numbers[0].replace(',', '.'))
                                    venta = float(numbers[1].replace(',', '.'))
                                    cotizacion_encontrada = True
                                    break
                                except ValueError:
                                    continue
                    if cotizacion_encontrada:
                        break
            
            # Método 3: Buscar por clases CSS comunes
            if not cotizacion_encontrada:
                possible_selectors = [
                    '.cotizacion', '.dolar', '.usd', '.divisa',
                    '[class*="cotiz"]', '[class*="dolar"]', '[class*="usd"]',
                    '[id*="cotiz"]', '[id*="dolar"]', '[id*="usd"]'
                ]
                
                for selector in possible_selectors:
                    elements = soup.select(selector)
                    for element in elements:
                        text = element.get_text()
                        numbers = re.findall(r'\d+[,.]?\d*', text)
                        if len(numbers) >= 2:
                            try:
                                compra = float(numbers[0].replace(',', '.'))
                                venta = float(numbers[1].replace(',', '.'))
                                cotizacion_encontrada = True
                                break
                            except ValueError:
                                continue
                    if cotizacion_encontrada:
                        break
            
            if cotizacion_encontrada and compra > 0 and venta > 0:
                argentina_tz = timezone('America/Argentina/Buenos_Aires')
                now = datetime.now(argentina_tz)
                
                logger.info(f"Cotización BNA obtenida: Compra ${compra}, Venta ${venta}")
                return {
                    'success': True,
                    'source': 'Banco Nación Argentina',
                    'compra': compra,
                    'venta': venta,
                    'fecha': now.strftime('%d/%m/%Y %H:%M'),
                    'moneda': 'USD'
                }
            else:
                logger.warning("No se pudo extraer la cotización del BNA")
                
    except Exception as e:
        logger.error(f"Error obteniendo cotización del BNA: {e}")
    
    # Fallback: Intentar con API del BCRA como respaldo
    try:
        logger.info("Intentando fallback con API del BCRA...")
        response = requests.get('https://api.estadisticasbcra.com/usd_of', timeout=5)
        
        if response.status_code == 200:
            data = response.json()
            if data:
                latest = data[-1]  # Último registro
                return {
                    'success': True,
                    'source': 'BCRA (Fallback)',
                    'compra': latest.get('v', 0),
                    'venta': latest.get('v', 0),
                    'fecha': latest.get('d', ''),
                    'moneda': 'USD'
                }
    except Exception as e:
        logger.warning(f"Error con fallback BCRA: {e}")
    
    # Si todo falla
    return {
        'success': False,
        'source': 'Error',
        'compra': 0,
        'venta': 0,
        'fecha': '',
        'moneda': 'USD',
        'error': 'No se pudo obtener la cotización del BNA'
    }

# ---------------------------- RUTAS PRINCIPALES ----------------------------

@app.route('/')
def index():
    """Página principal - Dashboard"""
    total_equipment = Equipment.select().count()
    total_jobs = Job.select().count()
    total_clients = Client.select().count()
    
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
                         total_clients=total_clients,
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
        # Obtener cliente si se especificó
        client = None
        if request.form.get('client_id'):
            try:
                client = Client.get_by_id(int(request.form['client_id']))
            except (Client.DoesNotExist, ValueError):
                client = None
        
        Equipment.create(
            marca=request.form['marca'],
            modelo=request.form['modelo'],
            anio=int(request.form['anio']),
            n_serie=request.form['n_serie'],
            propietario=request.form.get('propietario') or None,  # Mantener por compatibilidad
            client=client,
            vehiculo=request.form.get('vehiculo') or None,
            dominio=request.form.get('dominio') or None,
            notes=request.form.get('notes') or None
        )
        return redirect(url_for('equipos_list'))
    
    # Obtener valores únicos para autocompletado
    marcas = list(set([eq.marca for eq in Equipment.select()]))
    propietarios = list(set([eq.propietario for eq in Equipment.select() if eq.propietario]))
    
    # Obtener lista de clientes
    clientes = Client.select().order_by(Client.nombre)
    
    return render_template('equipo_form.html', 
                         equipo=None,
                         marcas=json.dumps(marcas),
                         propietarios=json.dumps(propietarios),
                         clientes=clientes)

@app.route('/equipo/<int:equipo_id>/editar', methods=['GET', 'POST'])
def equipo_edit(equipo_id):
    """Editar equipo existente"""
    equipo = Equipment.get_by_id(equipo_id)
    
    if request.method == 'POST':
        # Obtener cliente si se especificó
        client = None
        if request.form.get('client_id'):
            try:
                client = Client.get_by_id(int(request.form['client_id']))
            except (Client.DoesNotExist, ValueError):
                client = None
        
        equipo.marca = request.form['marca']
        equipo.modelo = request.form['modelo']
        equipo.anio = int(request.form['anio'])
        equipo.n_serie = request.form['n_serie']
        equipo.propietario = request.form.get('propietario') or None  # Mantener por compatibilidad
        equipo.client = client
        equipo.vehiculo = request.form.get('vehiculo') or None
        equipo.dominio = request.form.get('dominio') or None
        equipo.notes = request.form.get('notes') or None
        equipo.save()
        return redirect(url_for('equipo_detail', equipo_id=equipo_id))
    
    marcas = list(set([eq.marca for eq in Equipment.select()]))
    propietarios = list(set([eq.propietario for eq in Equipment.select() if eq.propietario]))
    
    # Obtener lista de clientes
    clientes = Client.select().order_by(Client.nombre)
    
    return render_template('equipo_form.html',
                         equipo=equipo,
                         marcas=json.dumps(marcas),
                         propietarios=json.dumps(propietarios),
                         clientes=clientes)

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

@app.route('/trabajo/<int:trabajo_id>')
def trabajo_detail(trabajo_id):
    """Ver detalles de un trabajo específico"""
    try:
        trabajo = Job.get_by_id(trabajo_id)
        
        # Obtener información del equipo
        equipo = trabajo.equipment
        
        return render_template('trabajo_detail.html', 
                             trabajo=trabajo, 
                             equipo=equipo)
    except Job.DoesNotExist:
        return render_template('error.html', 
                             error_code=404,
                             error_message="Trabajo no encontrado"), 404

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

# ---------------------------- RUTAS DE CLIENTES ----------------------------

@app.route('/clientes')
def clientes_list():
    """Lista de todos los clientes"""
    search = request.args.get('search', '')
    
    # Query base
    clientes = Client.select().order_by(Client.nombre)
    
    # Aplicar filtro de búsqueda
    if search:
        clientes = clientes.where(
            (Client.nombre.contains(search)) |
            (Client.telefono.contains(search)) |
            (Client.email.contains(search)) |
            (Client.cuit_cuil.contains(search))
        )
    
    # Preparar datos para la vista
    clientes_list = []
    for client in clientes:
        # Contar equipos del cliente
        equipos_count = Equipment.select().where(Equipment.client == client).count()
        
        clientes_list.append({
            'id': client.id,
            'nombre': client.nombre,
            'telefono': client.telefono,
            'direccion': client.direccion,
            'cuit_cuil': client.cuit_cuil,
            'email': client.email,
            'equipos_count': equipos_count,
            'created_at': client.created_at.strftime('%d/%m/%Y') if client.created_at else '-'
        })
    
    return render_template('clientes.html', 
                         clientes=clientes_list,
                         search=search,
                         total_clientes=len(clientes_list))

@app.route('/cliente/nuevo', methods=['GET', 'POST'])
def cliente_new():
    """Crear nuevo cliente"""
    if request.method == 'POST':
        try:
            client = Client.create(
                nombre=request.form['nombre'],
                telefono=request.form.get('telefono') or None,
                direccion=request.form.get('direccion') or None,
                cuit_cuil=request.form.get('cuit_cuil') or None,
                email=request.form.get('email') or None,
                notes=request.form.get('notes') or None
            )
            return redirect(url_for('clientes_list'))
        except Exception as e:
            logger.error(f"Error creando cliente: {e}")
            return redirect(url_for('cliente_new'))
    
    return render_template('cliente_form.html', cliente=None)

@app.route('/cliente/<int:cliente_id>')
def cliente_detail(cliente_id):
    """Detalle de un cliente específico"""
    try:
        client = Client.get_by_id(cliente_id)
        
        # Obtener equipos del cliente
        equipos = Equipment.select().where(Equipment.client == client)
        equipos_list = []
        
        for equipo in equipos:
            # Contar trabajos del equipo
            trabajos_count = Job.select().where(Job.equipment == equipo).count()
            
            equipos_list.append({
                'id': equipo.id,
                'marca': equipo.marca,
                'modelo': equipo.modelo,
                'anio': equipo.anio,
                'n_serie': equipo.n_serie,
                'vehiculo': equipo.vehiculo,
                'dominio': equipo.dominio,
                'trabajos_count': trabajos_count
            })
        
        # Estadísticas del cliente
        total_equipos = len(equipos_list)
        total_trabajos = sum(eq['trabajos_count'] for eq in equipos_list)
        total_gastado = Job.select(fn.SUM(Job.budget)).join(Equipment).where(
            Equipment.client == client
        ).scalar() or 0.0
        
        return render_template('cliente_detail.html',
                             cliente=client,
                             equipos=equipos_list,
                             total_equipos=total_equipos,
                             total_trabajos=total_trabajos,
                             total_gastado=total_gastado)
        
    except Client.DoesNotExist:
        return redirect(url_for('clientes_list'))

@app.route('/cliente/<int:cliente_id>/editar', methods=['GET', 'POST'])
def cliente_edit(cliente_id):
    """Editar cliente"""
    try:
        client = Client.get_by_id(cliente_id)
        
        if request.method == 'POST':
            client.nombre = request.form['nombre']
            client.telefono = request.form.get('telefono') or None
            client.direccion = request.form.get('direccion') or None
            client.cuit_cuil = request.form.get('cuit_cuil') or None
            client.email = request.form.get('email') or None
            client.notes = request.form.get('notes') or None
            client.save()
            
            return redirect(url_for('cliente_detail', cliente_id=client.id))
        
        return render_template('cliente_form.html', cliente=client)
        
    except Client.DoesNotExist:
        return redirect(url_for('clientes_list'))

@app.route('/cliente/<int:cliente_id>/eliminar', methods=['POST'])
def cliente_delete(cliente_id):
    """Eliminar cliente"""
    try:
        client = Client.get_by_id(cliente_id)
        
        # Verificar si tiene equipos asociados
        equipos_count = Equipment.select().where(Equipment.client == client).count()
        
        if equipos_count > 0:
            # No eliminar si tiene equipos, solo desasociar
            Equipment.update(client=None).where(Equipment.client == client).execute()
            logger.info(f"Cliente {client.nombre} desasociado de {equipos_count} equipos")
        
        client.delete_instance()
        return redirect(url_for('clientes_list'))
        
    except Exception as e:
        logger.error(f"Error eliminando cliente {cliente_id}: {e}")
        return redirect(url_for('clientes_list'))

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

# ---------------------------- RUTAS DE IMPORTACIÓN EXCEL ----------------------------

@app.route('/import/excel')
def import_excel_form():
    """Página para importar datos desde Excel"""
    return render_template('import_excel.html')

@app.route('/import/excel', methods=['POST'])
def import_excel_process():
    """Procesa la importación de datos desde Excel"""
    try:
        # Verificar si se subió un archivo
        if 'excel_file' not in request.files:
            return jsonify({'error': 'No se seleccionó ningún archivo'}), 400
        
        file = request.files['excel_file']
        
        if file.filename == '':
            return jsonify({'error': 'No se seleccionó ningún archivo'}), 400
        
        if not allowed_file(file.filename):
            return jsonify({'error': 'Tipo de archivo no permitido. Solo se aceptan archivos .xlsx y .xls'}), 400
        
        # Guardar archivo temporalmente
        filename = secure_filename(file.filename)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{timestamp}_{filename}"
        file_path = os.path.join(UPLOAD_FOLDER, filename)
        file.save(file_path)
        
        # Procesar archivo
        importer = ExcelImporter(file_path)
        
        # Parsear Excel
        if not importer.parse_excel():
            os.remove(file_path)  # Limpiar archivo
            return jsonify({
                'error': 'Error parseando el archivo Excel',
                'details': importer.import_summary['errors']
            }), 400
        
        # Verificar si hay datos para procesar
        if not importer.parsed_data:
            os.remove(file_path)  # Limpiar archivo
            return jsonify({'error': 'No se encontraron datos válidos en el archivo'}), 400
        
        # Mostrar preview antes de importar
        preview_data = importer.parsed_data[:10]  # Primeros 10 registros
        summary = {
            'total_records': len(importer.parsed_data),
            'clients': list(set(record['client'] for record in importer.parsed_data)),
            'equipments': list(set(record['equipment'] for record in importer.parsed_data)),
            'date_range': {
                'start': min(record['date'] for record in importer.parsed_data if record['date']),
                'end': max(record['date'] for record in importer.parsed_data if record['date'])
            }
        }
        
        # Guardar información del archivo en sesión para confirmar importación
        session['import_file'] = file_path
        session['import_summary'] = summary
        
        return jsonify({
            'success': True,
            'preview': preview_data,
            'summary': summary,
            'message': 'Archivo procesado correctamente. Revise los datos y confirme la importación.'
        })
        
    except Exception as e:
        logger.error(f"Error en importación Excel: {e}")
        return jsonify({'error': f'Error procesando archivo: {str(e)}'}), 500

@app.route('/import/excel/confirm', methods=['POST'])
def import_excel_confirm():
    """Confirma e importa los datos a la base de datos"""
    try:
        # Verificar que hay un archivo en sesión
        if 'import_file' not in session:
            return jsonify({'error': 'No hay archivo para importar'}), 400
        
        file_path = session['import_file']
        
        if not os.path.exists(file_path):
            return jsonify({'error': 'Archivo no encontrado'}), 400
        
        # Procesar archivo nuevamente e importar
        importer = ExcelImporter(file_path)
        
        if not importer.parse_excel():
            return jsonify({
                'error': 'Error parseando el archivo',
                'details': importer.import_summary['errors']
            }), 400
        
        # Importar a base de datos
        if not importer.import_to_database():
            return jsonify({
                'error': 'Error importando datos a la base de datos',
                'details': importer.import_summary['errors']
            }), 500
        
        # Limpiar archivo temporal
        os.remove(file_path)
        session.pop('import_file', None)
        session.pop('import_summary', None)
        
        return jsonify({
            'success': True,
            'message': 'Datos importados exitosamente',
            'summary': {
                'clients_created': importer.import_summary['clients_created'],
                'equipments_created': importer.import_summary['equipments_created'],
                'equipments_updated': importer.import_summary['equipments_updated'],
                'jobs_created': importer.import_summary['jobs_created'],
                'errors': importer.import_summary['errors']
            }
        })
        
    except Exception as e:
        logger.error(f"Error confirmando importación: {e}")
        return jsonify({'error': f'Error en importación: {str(e)}'}), 500

@app.route('/import/excel/cancel', methods=['POST'])
def import_excel_cancel():
    """Cancela la importación y limpia archivos temporales"""
    try:
        if 'import_file' in session:
            file_path = session['import_file']
            if os.path.exists(file_path):
                os.remove(file_path)
            session.pop('import_file', None)
            session.pop('import_summary', None)
        
        return jsonify({'success': True, 'message': 'Importación cancelada'})
        
    except Exception as e:
        logger.error(f"Error cancelando importación: {e}")
        return jsonify({'error': str(e)}), 500

# ---------------------------- RUTAS DE ADMINISTRACIÓN ----------------------------

@app.route('/admin/reset', methods=['GET'])
def admin_reset_form():
    """Página de confirmación para vaciar la aplicación"""
    # Obtener estadísticas actuales
    stats = {
        'total_clients': Client.select().count(),
        'total_equipments': Equipment.select().count(),
        'total_jobs': Job.select().count()
    }
    
    return render_template('admin_reset.html', stats=stats)

@app.route('/admin/reset/confirm', methods=['POST'])
def admin_reset_confirm():
    """Vacía toda la información de la aplicación"""
    try:
        # Verificar que se envió la confirmación correcta
        confirmation = request.form.get('confirmation', '').strip().upper()
        
        if confirmation != 'VACIAR TODO':
            return jsonify({
                'error': 'Confirmación incorrecta. Debe escribir exactamente "VACIAR TODO"'
            }), 400
        
        # Obtener estadísticas antes del borrado
        stats_before = {
            'clients': Client.select().count(),
            'equipments': Equipment.select().count(),
            'jobs': Job.select().count()
        }
        
        # Eliminar todos los datos en orden correcto (respetando foreign keys)
        logger.info("Iniciando proceso de vaciado de la aplicación")
        
        # 1. Eliminar trabajos (dependen de equipos)
        jobs_deleted = Job.delete().execute()
        logger.info(f"Eliminados {jobs_deleted} trabajos")
        
        # 2. Eliminar equipos (pueden depender de clientes)
        equipments_deleted = Equipment.delete().execute()
        logger.info(f"Eliminados {equipments_deleted} equipos")
        
        # 3. Eliminar clientes
        clients_deleted = Client.delete().execute()
        logger.info(f"Eliminados {clients_deleted} clientes")
        
        # Limpiar archivos temporales de uploads si existen
        import os
        import glob
        
        upload_files = glob.glob(os.path.join(UPLOAD_FOLDER, '*'))
        files_deleted = 0
        for file_path in upload_files:
            try:
                os.remove(file_path)
                files_deleted += 1
            except Exception as e:
                logger.warning(f"No se pudo eliminar archivo {file_path}: {e}")
        
        logger.info(f"Eliminados {files_deleted} archivos temporales")
        
        # Resetear secuencias de IDs (SQLite)
        try:
            db.execute_sql("DELETE FROM sqlite_sequence WHERE name IN ('clients', 'equipment', 'job')")
            logger.info("Secuencias de IDs reseteadas")
        except Exception as e:
            logger.warning(f"No se pudieron resetear las secuencias: {e}")
        
        logger.info("Proceso de vaciado completado exitosamente")
        
        return jsonify({
            'success': True,
            'message': 'Aplicación vaciada exitosamente',
            'stats': {
                'deleted': stats_before,
                'files_deleted': files_deleted
            }
        })
        
    except Exception as e:
        logger.error(f"Error vaciando la aplicación: {e}")
        logger.error(traceback.format_exc())
        return jsonify({
            'error': f'Error vaciando la aplicación: {str(e)}'
        }), 500

@app.route('/admin/reset/database', methods=['POST'])
def admin_reset_database():
    """Elimina completamente la base de datos y la recrea"""
    try:
        # Verificar confirmación
        confirmation = request.form.get('confirmation', '').strip().upper()
        
        if confirmation != 'RESETEAR BASE DE DATOS':
            return jsonify({
                'error': 'Confirmación incorrecta. Debe escribir exactamente "RESETEAR BASE DE DATOS"'
            }), 400
        
        logger.info("Iniciando reseteo completo de base de datos")
        
        # Cerrar conexión actual
        db.close()
        
        # Eliminar archivo de base de datos
        import os
        if os.path.exists(DB_FILENAME):
            os.remove(DB_FILENAME)
            logger.info(f"Archivo de base de datos {DB_FILENAME} eliminado")
        
        # Recrear base de datos
        init_db()
        logger.info("Base de datos recreada exitosamente")
        
        return jsonify({
            'success': True,
            'message': 'Base de datos reseteada completamente'
        })
        
    except Exception as e:
        logger.error(f"Error reseteando base de datos: {e}")
        logger.error(traceback.format_exc())
        return jsonify({
            'error': f'Error reseteando base de datos: {str(e)}'
        }), 500

@app.route('/admin/clean-duplicates', methods=['POST'])
def admin_clean_duplicates():
    """Limpia trabajos duplicados"""
    try:
        duplicates_removed = clean_duplicate_jobs()
        
        return jsonify({
            'success': True,
            'message': f'Limpieza completada: {duplicates_removed} trabajos duplicados eliminados',
            'duplicates_removed': duplicates_removed
        })
        
    except Exception as e:
        logger.error(f"Error limpiando duplicados: {e}")
        return jsonify({
            'error': f'Error limpiando duplicados: {str(e)}'
        }), 500

@app.route('/api/info')
def api_info():
    """API para obtener información de fecha/hora y cotización del dólar"""
    try:
        # Obtener información
        datetime_info = get_current_datetime()
        dollar_info = get_dollar_rate()
        
        return jsonify({
            'success': True,
            'datetime': datetime_info,
            'dollar': dollar_info,
            'timestamp': datetime.now().isoformat()
        })
        
    except Exception as e:
        logger.error(f"Error en API info: {e}")
        return jsonify({
            'success': False,
            'error': str(e),
            'datetime': get_current_datetime(),  # Al menos devolver la fecha/hora
            'dollar': {
                'success': False,
                'error': 'Error obteniendo cotización'
            }
        }), 500

# ---------------------------- INICIALIZACIÓN ----------------------------

if __name__ == '__main__':
    init_db()
    # Para desarrollo local
    import os
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=False, host='0.0.0.0', port=port)
    
    # Para producción en Render, se usará gunicorn
