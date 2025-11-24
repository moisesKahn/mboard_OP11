## PDF rápido (Snapshot) del Optimizador

Se reemplazó el flujo legacy pesado (ReportLab reconstruyendo layouts) por un mecanismo rápido basado en HTML → WeasyPrint.

Resumen del flujo:
1. Tras una optimización, se fija la visualización (`data-locked="1"`) y se guarda un snapshot HTML por material.
2. El botón PDF empaqueta todos los materiales optimizados: `{ titulo, eficiencia, layout_html, piezas[] }` y hace POST a `exportar-pdf-snapshot/<proyecto_id>/`.
3. El backend compacta el HTML, genera el PDF con WeasyPrint y guarda caché (`materiales_snapshot.json`, `snapshot.html`).
4. Descargas posteriores usan `exportar-pdf-snapshot-cached/<proyecto_id>/` sin reenviar datos ni recalcular optimización.

Ventajas:
- No dispara nueva optimización (usa resultado existente).
- Multi-material en un solo PDF.
- Segunda descarga instantánea (usa caché en disco).

Fallback: La ruta legacy `exportar-pdf` se mantiene como respaldo, pero la UI usa la nueva por defecto.

Si se reoptimiza un material, se desbloquea su contenedor, se vuelve a renderizar y se actualiza el snapshot correspondiente antes de la siguiente exportación.
# Mboard Optimizador

Panel de optimización de materiales multi–organización (Django) con chat en tiempo real por polling, control de accesos por rol, gestión de materiales (tableros y tapacantos), exportación a PDF y UI moderna.

[![CI](https://github.com/moisesKahn/Mboard_Optimizador/actions/workflows/ci.yml/badge.svg)](https://github.com/moisesKahn/Mboard_Optimizador/actions/workflows/ci.yml)

## Requisitos
- Python 3.11+ (recomendado)
- Pip
- (Opcional) virtualenv

## Estructura
- `Django/` – Proyecto Django principal (carpeta que contiene `manage.py` y `WowDash/`)
- `Django/static/` – Archivos estáticos (CSS/JS/imagenes)
- `Django/templates/` – Plantillas
- `Django/core/` – App principal (modelos, migraciones, comandos de gestión)

## Puesta en marcha (Windows PowerShell)
```powershell
cd "c:\Users\Moise\Documents\Mboard\base"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -U pip
pip install -r requirements.txt

# Preparar DB (SQLite por defecto)
cd Django
python manage.py migrate

# Crear superusuario (opcional)
python manage.py createsuperuser

# Iniciar servidor
python manage.py runserver 0.0.0.0:8000
```

## Puesta en marcha (Linux/macOS)
```bash
cd ~/Mboard/base
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -r requirements.txt

cd Django
python manage.py migrate
python manage.py createsuperuser  # opcional
python manage.py runserver 0.0.0.0:8000
```

## Funcionalidades clave
- Multi–organización con roles: super_admin, org_admin, agente, subordinador.
- Chat con conversaciones, conteo de no leídos y notificaciones sonoras (polling).
- Materiales por organización (tableros y tapacantos), importación CSV, búsqueda y paginación.
- Optimizador: exportación a PDF, gating del botón durante la generación.
- Dashboard con resumen del perfil y métricas por organización.

## Clon del Optimizador Autoservicio
Se agregó un clon independiente del optimizador para el rol `autoservicio` con ruta dedicada `/optimizador_autoservicio/`.

Motivación:
- Permitir evolución del flujo autoservicio sin riesgo de romper el optimizador principal.
- Aislar cambios visuales y lógicos (multi-material, PDF, historial) manteniendo compatibilidad.

Características del clon:
- Lógica completa duplicada (`optimizer_autoservicio_clone.py`) incluyendo multi-material, folio (public_id) y generación de PDF.
- Contexto aislado mediante flags: `clone_mode=True`, `optimizer_variant='autoservicio_clone'`.
- Acceso directo: usuarios con rol `autoservicio` saltan captura de RUT y reciben un proyecto borrador inicial.
- Animación separada (`static/js/optimizador_autoservicio/optimizer_anim_clone.js`).
- Plantilla dedicada (`templates/optimizador_autoservicio/home_clone.html`).

Flujo de redirección:
1. Login con rol `autoservicio` → redirect a `optimizador_autoservicio_home_clone`.
2. Búsqueda/creación de cliente en autoservicio retorna `redirect_clone` para navegar al clon.

Mantenimiento futuro:
- Realizar cambios del flujo autoservicio únicamente dentro de archivos `*_clone` y carpeta `optimizador_autoservicio/`.
- Si se requieren nuevas opciones PDF, duplicar primero en el clon y luego evaluar portarlo al original.
- Documentar diferencias cuando se añadan nuevas capacidades para evitar divergencias silenciosas.

Para pruebas rápidas (usuario `autoservicio_demo`):
```powershell
python manage.py shell -c "from django.contrib.auth import get_user_model; U=get_user_model(); u=U.objects.get(username='autoservicio_demo'); print('User existe:',u.username)"
```

## Importación de materiales
Consulta `Django/static/docs/IMPORTACION_MATERIALES.md` para el formato CSV de Tableros y Tapacantos.

## Comandos de gestión útiles
Desde `Django/`:
```bash
# Replicar materiales/tapacantos a todas las organizaciones (dry-run)
python manage.py migrar_materiales_organizaciones --dry-run --exclude-general

# Ejecución real
python manage.py migrar_materiales_organizaciones
```

## Variables/Entorno
- Por defecto usa SQLite. Si deseas apuntar a PostgreSQL (por ejemplo, a la MISMA base que usa tu URL de despliegue), configura variables de entorno:

		1) Copia `Django/.env.example` a `Django/.env` (recomendado) o crea `.env` en la raíz del repo.
		2) Rellena `DATABASE_URL` con la URL exacta de tu base (formato: `postgres://user:pass@host:port/db?sslmode=require`).
		3) Ajusta `CSRF_TRUSTED_ORIGINS` para incluir el host:puerto donde correrás el servidor.
		4) Opcional: `DJANGO_ALLOWED_HOSTS=*` en desarrollo.

		WowDash/settings.py intenta cargar `.env` tanto desde `Django/.env` como desde la raíz; si existen ambos, `Django/.env` tiene prioridad.

### Ejecutar servidor en un puerto específico (usando la misma DB de la URL)

Desde `Django/`:

```bash
python manage.py migrate              # usa la DB definida en DATABASE_URL
python manage.py runserver 0.0.0.0:8000
```

Si necesitas otro puerto, cambia `8000` por el que prefieras.

## Tests / Lint
Este repo trae un pipeline simple con GitHub Actions que:
- Instala dependencias (requirements + dev)
- Ejecuta ruff (lint) y `python manage.py check`

Localmente puedes ejecutar:
```bash
pip install -r requirements-dev.txt
ruff check .
cd Django && python manage.py check
```

## Despliegue
- Ajusta `ALLOWED_HOSTS` en `WowDash/settings.py`.
- Configura `DEBUG = False` y un `SECRET_KEY` seguro en variables de entorno para producción.
- Usa un servidor WSGI (gunicorn/uwsgi) detrás de Nginx/Apache.

## Licencia
MIT – ver `LICENSE`.
