# 🚀 Guía de Despliegue en Render - EAD Oleohidráulica

## 📋 Paso a Paso para Desplegar

### **1. Preparar el Repositorio**

1. **Crear cuenta en GitHub** (si no tienes):
   - Ve a https://github.com
   - Crea una cuenta gratuita

2. **Crear nuevo repositorio**:
   - Click en "New repository"
   - Nombre: `ead-oleohidraulica-sistema`
   - Descripción: `Sistema de Gestión de Taller - EAD Oleohidráulica`
   - Público o Privado (recomendado: Privado)
   - Click "Create repository"

### **2. Subir el Código a GitHub**

Desde tu carpeta del proyecto, ejecuta estos comandos en la terminal:

```bash
# Inicializar Git
git init

# Agregar todos los archivos
git add .

# Hacer el primer commit
git commit -m "Initial commit - EAD Oleohidráulica Sistema"

# Conectar con GitHub (reemplaza TU_USUARIO y TU_REPO)
git remote add origin https://github.com/TU_USUARIO/ead-oleohidraulica-sistema.git

# Subir el código
git push -u origin main
```

### **3. Crear Cuenta en Render**

1. Ve a https://render.com
2. Click "Get Started"
3. Regístrate con tu cuenta de GitHub
4. Autoriza a Render para acceder a tus repositorios

### **4. Desplegar en Render**

1. **En el Dashboard de Render**:
   - Click "New +"
   - Selecciona "Web Service"

2. **Conectar Repositorio**:
   - Busca tu repositorio `ead-oleohidraulica-sistema`
   - Click "Connect"

3. **Configurar el Servicio**:
   - **Name**: `ead-oleohidraulica`
   - **Region**: Oregon (US West) - más cercano
   - **Branch**: `main`
   - **Runtime**: `Python 3`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `gunicorn app_web:app --bind 0.0.0.0:$PORT`

4. **Plan**:
   - Selecciona "Free" (gratis)
   - Click "Create Web Service"

### **5. Variables de Entorno (Opcional)**

Si necesitas configurar variables:
- En tu servicio, ve a "Environment"
- Agrega las variables necesarias

### **6. Acceder a tu Aplicación**

1. **URL de tu aplicación**:
   - Render te dará una URL como: `https://ead-oleohidraulica.onrender.com`
   - El despliegue toma 5-10 minutos la primera vez

2. **Verificar funcionamiento**:
   - Abre la URL en tu navegador
   - Verifica que el logo se vea correctamente
   - Prueba crear equipos y trabajos

### **7. Actualizaciones Futuras**

Para actualizar tu aplicación:

```bash
# Hacer cambios en tu código local
# Guardar cambios
git add .
git commit -m "Descripción de los cambios"
git push origin main
```

Render automáticamente desplegará los cambios.

## 🔧 Archivos de Configuración Incluidos

- ✅ `requirements.txt` - Dependencias de Python
- ✅ `render.yaml` - Configuración de Render
- ✅ `Procfile` - Comando de inicio
- ✅ Configuración de puerto dinámico en `app_web.py`

## 🌐 Características del Despliegue

- **Base de datos**: SQLite (incluida en el despliegue)
- **Archivos estáticos**: Servidos por Flask
- **Logo**: Incluido en `/static/img/`
- **SSL**: Automático con Render
- **Dominio**: Subdominio gratuito de Render

## 📞 Soporte

Si tienes problemas:
1. Revisa los logs en Render Dashboard
2. Verifica que todos los archivos estén en GitHub
3. Confirma que las dependencias estén en `requirements.txt`

---
**EAD Oleohidráulica - ENZO A. DEUX**  
Sistema de Gestión de Taller v1.0
