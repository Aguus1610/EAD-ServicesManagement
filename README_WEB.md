# Agenda Taller - Aplicación Web

Aplicación web responsive para gestión de trabajos y mantenimientos de equipos/vehículos.

## 🚀 Características

- **100% Responsive**: Funciona perfectamente en smartphones, tablets y desktop
- **Dashboard interactivo**: Vista general con estadísticas y próximos servicios
- **Gestión de equipos**: CRUD completo con búsqueda y filtrado
- **Historial de trabajos**: Registro detallado de todos los mantenimientos
- **Estadísticas avanzadas**: Gráficos interactivos con Chart.js
- **Autocompletado inteligente**: Basado en datos existentes
- **Exportación CSV**: Descarga de datos para análisis externo

## 📱 Capturas de Pantalla

La aplicación se adapta automáticamente a cualquier tamaño de pantalla:
- Vista móvil con menú hamburguesa
- Cards optimizadas para táctil
- Tablas responsive con scroll horizontal
- Gráficos que se ajustan al viewport

## 🛠️ Tecnologías

- **Backend**: Flask (Python)
- **Base de datos**: SQLite con Peewee ORM
- **Frontend**: Bootstrap 5 + Chart.js
- **Deployment**: Render.com

## 📦 Instalación Local

1. **Clonar el repositorio**
```bash
git clone <tu-repositorio>
cd agenda-taller
```

2. **Crear entorno virtual**
```bash
python -m venv venv
# Windows
venv\Scripts\activate
# Linux/Mac
source venv/bin/activate
```

3. **Instalar dependencias**
```bash
pip install -r requirements.txt
```

4. **Ejecutar la aplicación**
```bash
python app_web.py
```

5. **Abrir en el navegador**
```
http://localhost:5000
```

## 🌐 Deployment en Render

### Opción 1: Deploy Automático

1. Sube tu código a GitHub
2. Ve a [Render.com](https://render.com)
3. Conecta tu repositorio de GitHub
4. Render detectará automáticamente el archivo `render.yaml`
5. Click en "Deploy"

### Opción 2: Deploy Manual

1. En Render, crea un nuevo Web Service
2. Conecta tu repositorio
3. Configura:
   - **Environment**: Python
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `gunicorn app_web:app`
4. Deploy!

## 📊 Estructura del Proyecto

```
agenda-taller/
├── app_web.py          # Aplicación Flask principal
├── templates/          # Plantillas HTML
│   ├── base.html      # Layout base
│   ├── dashboard.html # Panel principal
│   ├── equipos.html   # Lista de equipos
│   └── ...
├── static/            # Archivos estáticos
│   ├── css/          # Estilos personalizados
│   └── js/           # Scripts personalizados
├── agenda_taller.db   # Base de datos SQLite
├── requirements.txt   # Dependencias Python
└── render.yaml       # Configuración Render
```

## 💾 Migración desde App Desktop

Si tienes datos en la aplicación desktop anterior:

1. Copia el archivo `agenda_taller.db` al directorio del proyecto web
2. La aplicación web usará automáticamente la base de datos existente
3. Todos tus equipos y trabajos estarán disponibles

## 🔧 Configuración Avanzada

### Variables de Entorno

Crea un archivo `.env` (no subir a Git):

```env
SECRET_KEY=tu-clave-secreta-muy-segura
FLASK_ENV=production
DATABASE_URL=sqlite:///agenda_taller.db
```

### Base de Datos PostgreSQL (Opcional)

Para usar PostgreSQL en producción:

1. Instala el driver: `pip install psycopg2-binary`
2. Modifica `app_web.py`:
```python
import os
from playhouse.db_url import connect

# En lugar de SqliteDatabase
db = connect(os.environ.get('DATABASE_URL', 'sqlite:///agenda_taller.db'))
```

## 📱 PWA (Progressive Web App)

La aplicación está optimizada para móviles y puede instalarse como PWA:
- Agregar a pantalla de inicio en Android/iOS
- Funciona offline (con service worker - próximamente)
- Notificaciones push (próximamente)

## 🆘 Soporte

Si encuentras algún problema o tienes sugerencias:
1. Abre un issue en GitHub
2. Contacta al desarrollador

## 📄 Licencia

MIT - Uso libre para proyectos personales y comerciales

---

**Desarrollado con ❤️ para talleres mecánicos**
