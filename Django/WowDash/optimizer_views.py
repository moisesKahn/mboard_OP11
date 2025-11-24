# optimizer_views.py - Motor de optimización simplificado y robusto
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, HttpResponse
from django.contrib import messages
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.core.paginator import Paginator
from django.db.models import Q
from django.utils import timezone
import json
import uuid
from datetime import datetime
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter, landscape
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
try:
    from weasyprint import HTML as WEASY_HTML
except Exception:
    WEASY_HTML = None
from django.templatetags.static import static
from django.utils.text import slugify
from django.contrib.staticfiles import finders
from core.models import Proyecto, Cliente, Material, Tapacanto, OptimizationRun, AuditLog
from core.auth_utils import get_auth_context
import math

def _normalize_rut(rut: str) -> str:
    """Normaliza un RUT/identificador para comparación: quita puntos, guiones y espacios, y pasa a mayúsculas.
    Evita duplicados por formato (ej. 12.345.678-9 vs 12345678-9).
    """
    if not rut:
        return ''
    try:
        s = str(rut).upper()
        # quitar espacios, puntos y guiones
        for ch in [' ', '.', '-']:
            s = s.replace(ch, '')
        return s
    except Exception:
        return str(rut).strip()

class TipoMaterial:
    TABLERO = 'tablero'

class OptimizationEngine:
    """Motor de optimización simplificado que evita superposiciones"""
    def __init__(self, tablero_ancho, tablero_largo, margen_x, margen_y, desperdicio_sierra):
        self.tablero_ancho_original = tablero_ancho
        self.tablero_largo_original = tablero_largo
        self.tablero_ancho = tablero_ancho - (2 * margen_x)
        self.tablero_largo = tablero_largo - (2 * margen_y)
        self.margen_x = margen_x
        self.margen_y = margen_y
        self.desperdicio_sierra = desperdicio_sierra
        self.tableros = []

    def optimizar_piezas(self, piezas):
        """Algoritmo de optimización principal con timeout y colocación Bottom-Left"""
        import time
        tiempo_inicio = time.time()
        timeout_segundos = 30

        # Expandir piezas por cantidad
        piezas_individuales = []
        for pieza in piezas:
            for i in range(pieza.get('cantidad', 1)):
                pi = pieza.copy(); pi['id_unico'] = f"{pieza['nombre']}_{i+1}"; pi['cantidad'] = 1
                piezas_individuales.append(pi)

        # Orden: primero áreas mayores
        def criterio(p):
            area = p['ancho'] * p['largo']
            max_dim = max(p['ancho'], p['largo'])
            return (-area, -max_dim)
        piezas_individuales.sort(key=criterio)

        piezas_no_colocadas = []

        for i, pieza in enumerate(piezas_individuales):
            if time.time() - tiempo_inicio > timeout_segundos:
                piezas_no_colocadas.extend(piezas_individuales[i:])
                break

            colocada = False
            # Probar primero en tableros existentes (más llenos primero)
            tableros_ordenados = sorted(self.tableros, key=lambda t: len(t['piezas']), reverse=True)
            for tablero in tableros_ordenados:
                if self._colocar_pieza_en_tablero(tablero, pieza):
                    colocada = True
                    break
                if time.time() - tiempo_inicio > timeout_segundos:
                    break

            # Crear nuevo tablero si no cupo
            if not colocada and time.time() - tiempo_inicio <= timeout_segundos:
                nuevo = self._crear_nuevo_tablero()
                if self._colocar_pieza_en_tablero(nuevo, pieza):
                    self.tableros.append(nuevo)
                    colocada = True
                else:
                    piezas_no_colocadas.append(pieza)
            elif not colocada:
                piezas_no_colocadas.append(pieza)

        # Generar resultado y ajustar métricas
        resultado = self._generar_resultado()
        resultado['piezas_no_colocadas'] = len(piezas_no_colocadas)
        resultado['tiempo_optimizacion'] = time.time() - tiempo_inicio
        return resultado

    def _colocar_pieza_en_tablero(self, tablero, pieza):
        # Validar si cabe o intentar rotación si veta libre
        if (pieza['ancho'] > self.tablero_ancho or pieza['largo'] > self.tablero_largo):
            if (pieza.get('veta_libre', False) and pieza['largo'] <= self.tablero_ancho and pieza['ancho'] <= self.tablero_largo):
                orientaciones = [(pieza['largo'], pieza['ancho'], True)]
            else:
                return False
        else:
            orientaciones = [(pieza['ancho'], pieza['largo'], False)]
            if (pieza.get('veta_libre', False) and pieza['largo'] <= self.tablero_ancho and pieza['ancho'] <= self.tablero_largo):
                orientaciones.append((pieza['largo'], pieza['ancho'], True))

        for ancho, largo, rotada in orientaciones:
            pos = self._encontrar_posicion_libre(tablero, ancho, largo)
            if pos:
                x, y = pos['x'], pos['y']
                if (x + ancho <= self.tablero_ancho and y + largo <= self.tablero_largo):
                    nueva = {
                        'nombre': pieza['nombre'],
                        'id_unico': pieza.get('id_unico', pieza['nombre']),
                        'x': x, 'y': y,
                        'ancho': ancho, 'largo': largo,
                        'rotada': rotada,
                        'tapacantos': pieza.get('tapacantos', {}),
                        'veta_libre': pieza.get('veta_libre', False)
                    }
                    tablero['piezas'].append(nueva)
                    return True
        return False

    def _encontrar_posicion_libre(self, tablero, ancho, largo):
        if ancho > self.tablero_ancho or largo > self.tablero_largo:
            return None
        if not tablero['piezas']:
            return {'x': 0, 'y': 0}

        # Estrategia: Grid regular para piezas uniformes
        # Si todas las piezas en el tablero tienen el mismo tamaño, usar grid estricto
        if len(tablero['piezas']) > 0:
            piezas_uniformes = all(
                p['ancho'] == ancho and p['largo'] == largo 
                for p in tablero['piezas']
            )
            
            if piezas_uniformes:
                # Calcular posiciones de grid con kerf
                paso_x = ancho + self.desperdicio_sierra
                paso_y = largo + self.desperdicio_sierra
                
                # Buscar en grid regular
                y = 0
                while y + largo <= self.tablero_largo:
                    x = 0
                    while x + ancho <= self.tablero_ancho:
                        if self._posicion_libre(tablero, x, y, ancho, largo):
                            return {'x': x, 'y': y}
                        x += paso_x
                    y += paso_y

        # Estrategia: Bottom-Left mejorada con alineación estricta
        # Crear una lista de posiciones candidatas basadas en las esquinas de piezas existentes
        posiciones = set()
        posiciones.add((0, 0))
        
        for p in tablero['piezas']:
            # Posición a la derecha de la pieza (considerando kerf)
            x_der = p['x'] + p['ancho'] + self.desperdicio_sierra
            # Posición arriba de la pieza (considerando kerf)
            y_sup = p['y'] + p['largo'] + self.desperdicio_sierra
            
            # Alineado a la derecha, misma Y
            posiciones.add((x_der, p['y']))
            # Alineado arriba, misma X
            posiciones.add((p['x'], y_sup))
            # Esquina superior derecha
            posiciones.add((x_der, y_sup))
            # Misma posición (puede caber si la otra pieza está rotada)
            posiciones.add((p['x'], p['y']))

        # Ordenar posiciones: primero las más abajo (menor Y), luego más a la izquierda (menor X)
        pos_list = sorted(list(posiciones), key=lambda pos: (pos[1], pos[0]))
        
        # Intentar cada posición candidata
        for (x, y) in pos_list:
            # Validar que está dentro del tablero
            if x + ancho <= self.tablero_ancho and y + largo <= self.tablero_largo:
                if self._posicion_libre(tablero, x, y, ancho, largo):
                    return {'x': x, 'y': y}
        
        # Si no encontró posición en candidatas, búsqueda exhaustiva con paso fino
        # Usar un paso más fino para mejor precisión
        paso = 5  # Paso más fino para mejor alineación
        for y in range(0, self.tablero_largo - largo + 1, paso):
            for x in range(0, self.tablero_ancho - ancho + 1, paso):
                if self._posicion_libre(tablero, x, y, ancho, largo):
                    return {'x': x, 'y': y}
        
        return None

    def _posicion_libre(self, tablero, x, y, ancho, largo):
        if (x < 0 or y < 0 or x + ancho > self.tablero_ancho or y + largo > self.tablero_largo):
            return False
        for p in tablero['piezas']:
            nuevo_x1, nuevo_y1 = x, y
            nuevo_x2, nuevo_y2 = x + ancho, y + largo
            exist_x1, exist_y1 = p['x'], p['y']
            exist_x2, exist_y2 = p['x'] + p['ancho'], p['y'] + p['largo']
            margen = self.desperdicio_sierra
            overlap_x = not (nuevo_x2 + margen <= exist_x1 or exist_x2 + margen <= nuevo_x1)
            overlap_y = not (nuevo_y2 + margen <= exist_y1 or exist_y2 + margen <= nuevo_y1)
            if overlap_x and overlap_y:
                return False
        return True

    def _crear_nuevo_tablero(self):
        return {
            'id': len(self.tableros) + 1,
            'ancho': self.tablero_ancho,
            'largo': self.tablero_largo,
            'piezas': [],
            'area_usada': 0
        }

    def _generar_resultado(self):
        total_area_tableros = len(self.tableros) * (self.tablero_ancho * self.tablero_largo)
        area_utilizada = 0
        total_piezas = 0
        for tablero in self.tableros:
            area_tablero = 0
            for pieza in tablero['piezas']:
                area_pieza = pieza['ancho'] * pieza['largo']
                area_utilizada += area_pieza
                area_tablero += area_pieza
                total_piezas += 1
            tablero['area_usada'] = area_tablero
            tablero['area_total'] = self.tablero_ancho * self.tablero_largo
            tablero['area_utilizada'] = area_tablero
            tablero['eficiencia_tablero'] = (area_tablero / (self.tablero_ancho * self.tablero_largo)) * 100
            # Ajustes para visualización (incluir márgenes)
            for pieza in tablero['piezas']:
                pieza['x'] += self.margen_x
                pieza['y'] += self.margen_y
            tablero['ancho'] = self.tablero_ancho_original
            tablero['largo'] = self.tablero_largo_original
            tablero['ancho_trabajo'] = self.tablero_ancho
            tablero['largo_trabajo'] = self.tablero_largo

        eficiencia = (area_utilizada / total_area_tableros * 100) if total_area_tableros > 0 else 0
        return {
            'tableros': self.tableros,
            'total_tableros': len(self.tableros),
            'total_piezas': total_piezas,
            'area_utilizada': area_utilizada / 1000000,
            'eficiencia': round(eficiencia, 1),
            'area_total': total_area_tableros / 1000000,
            'desperdicio_sierra': self.desperdicio_sierra,
            'tablero_ancho_efectivo': self.tablero_ancho,
            'tablero_largo_efectivo': self.tablero_largo,
            'tablero_ancho_original': self.tablero_ancho_original,
            'tablero_largo_original': self.tablero_largo_original,
            'margenes': {
                'margen_x': self.margen_x,
                'margen_y': self.margen_y
            }
        }
def optimizador_home_clasico(request):
    """Versión clásica del optimizador (conservada por compatibilidad)."""
    ctx = get_auth_context(request)
    base = Proyecto.objects.filter(usuario=request.user)
    if not (ctx.get('organization_is_general') or ctx.get('is_support')):
        base = base.filter(organizacion_id=ctx.get('organization_id'))
    proyectos = base.order_by('-fecha_creacion')[:10]
    clientes = Cliente.objects.all()
    tableros = Material.objects.all()
    tapacantos = Tapacanto.objects.all()

    context = {
        'proyectos': proyectos,
        'clientes': clientes,
        'tableros': tableros,
        'tapacantos': tapacantos,
    }
    return render(request, 'optimizador/home.html', context)

@login_required
def optimizador_autoservicio(request):
    """Optimización restringida para flujo autoservicio: reutiliza template principal con flags.
    Requiere que el usuario tenga rol autoservicio y cliente identificado en sesión.
    """
    perfil = getattr(request.user, 'usuarioperfiloptimizador', None)
    if not (perfil and perfil.rol == 'autoservicio'):
        return redirect('/')
    from WowDash.autoservicio_views import SESSION_KEY_CLIENTE
    cliente_id = request.session.get(SESSION_KEY_CLIENTE)
    if not cliente_id:
        return redirect('/autoservicio/')
    cliente = Cliente.objects.filter(id=cliente_id).first()
    if not cliente:
        request.session.pop(SESSION_KEY_CLIENTE, None)
        return redirect('/autoservicio/')
    ctx = get_auth_context(request)
    # Limitar materiales al org si aplica
    materiales_qs = Material.objects.all()
    tapacantos_qs = Tapacanto.objects.all()
    if not (ctx.get('organization_is_general') or ctx.get('is_support')):
        materiales_qs = materiales_qs.filter(organizacion_id=ctx.get('organization_id')) if hasattr(Material, 'organizacion') else materiales_qs
        tapacantos_qs = tapacantos_qs.filter(organizacion_id=ctx.get('organization_id')) if hasattr(Tapacanto, 'organizacion') else tapacantos_qs
    # Fallback: si filtros devolvieron vacío, usar primeros materiales/tapacantos globales para evitar select vacío
    mats_list = list(materiales_qs[:50])
    if not mats_list:
        mats_list = list(Material.objects.all()[:50])
    taps_list = list(tapacantos_qs[:50])
    if not taps_list:
        taps_list = list(Tapacanto.objects.all()[:50])
    context = {
        'title': 'Optimizador Autoservicio',
        'subTitle': 'Proyecto Nuevo',
        'cliente_autoservicio': cliente,
        'autoservicio': True,
        'tableros': mats_list,
        'tapacantos': taps_list,
    }
    return render(request, 'optimizador/home.html', context)

@login_required
def autoservicio_portada_pdf(request, proyecto_id: int):
    """Genera sólo la portada PDF resumida para un proyecto (flujo autoservicio)."""
    perfil = getattr(request.user, 'usuarioperfiloptimizador', None)
    if not (perfil and perfil.rol == 'autoservicio'):
        return HttpResponse('Forbidden', status=403)
    proyecto = get_object_or_404(Proyecto, id=proyecto_id)
    # Validar que el proyecto pertenezca al cliente actual (por RUT / cliente id)
    from WowDash.autoservicio_views import SESSION_KEY_CLIENTE
    cliente_id = request.session.get(SESSION_KEY_CLIENTE)
    if not cliente_id or proyecto.cliente_id != cliente_id:
        return HttpResponse('Forbidden', status=403)
    # Crear PDF en memoria con resumen
    from io import BytesIO
    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=letter)
    c.setTitle("Resumen Proyecto Autoservicio")
    c.setFont("Helvetica-Bold", 18)
    c.drawString(40, 750, "Resumen Proyecto Autoservicio")
    c.setFont("Helvetica", 12)
    y = 710
    def line(txt):
        nonlocal y
        c.drawString(40, y, txt)
        y -= 20
    line(f"Proyecto ID: {proyecto.id}")
    line(f"Cliente: {proyecto.cliente.nombre} ({proyecto.cliente.rut})")
    line(f"Nombre Proyecto: {proyecto.nombre}")
    line(f"Fecha: {timezone.now().strftime('%Y-%m-%d %H:%M')}")
    # Materiales / métricas si existen en relaciones
    mats = getattr(proyecto, 'materiales_utilizados', []).all() if hasattr(proyecto, 'materiales_utilizados') else []
    if mats:
        line("Materiales utilizados:")
        for m in mats[:20]:
            line(f" - {getattr(m.material,'nombre','Material')} | Tableros: {m.cantidad_tableros} | Eficiencia: {m.eficiencia}%")
    else:
        line("Materiales: (sin detalles registrados)")
    c.showPage()
    c.save()
    pdf = buffer.getvalue()
    buffer.close()
    resp = HttpResponse(pdf, content_type='application/pdf')
    resp['Content-Disposition'] = f'attachment; filename="portada-proyecto-{proyecto.id}.pdf"'
    return resp

# ------------------------------
# Renderizado de PDF desde resultado
# ------------------------------
def _materiales_desde_resultado(resultado):
    if not isinstance(resultado, dict):
        return []
    mats = resultado.get('materiales')
    if isinstance(mats, list) and mats:
        return mats
    # Soportar caso single-material plano
    if resultado.get('tableros'):
        return [resultado]
    return []

def _pdf_from_result(proyecto, resultado, opts: dict | None = None):
    """Genera un PDF (bytes) que dibuja cada tablero y sus piezas según el resultado guardado.
    Paridad 1:1 con la vista: coords relativas al área útil con origen arriba-izquierda.
    """
    from io import BytesIO
    buf = BytesIO()

    # Canvas con numeración total de páginas
    class NumberedCanvas(canvas.Canvas):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._saved_page_states = []
            self._page_width, self._page_height = landscape(letter)
        def showPage(self):
            # Guarda el estado de la página actual y empieza una nueva
            self._saved_page_states.append(dict(self.__dict__))
            self._startPage()
        def save(self):
            # Asegurar que el estado de la página actual también esté incluido
            # (si no se llamó a showPage() tras el último contenido, se perdería la última página).
            try:
                self._saved_page_states.append(dict(self.__dict__))
            except Exception:
                pass
            # Inserta numeración "Página X de Y" centrada abajo
            page_count = len(self._saved_page_states)
            for i, state in enumerate(self._saved_page_states, start=1):
                self.__dict__.update(state)
                self._draw_page_number(i, page_count)
                canvas.Canvas.showPage(self)
            canvas.Canvas.save(self)
        def _draw_page_number(self, page_num, page_count):
            try:
                self.setFont("Helvetica", 9)
                txt = f"Página {page_num} de {page_count}"
                self.drawCentredString(self._page_width/2.0, 18, txt)
            except Exception:
                pass

    # PDF en orientación horizontal (apaisado)
    p = NumberedCanvas(buf, pagesize=landscape(letter))
    width, height = landscape(letter)
    # Título del documento para evitar "Untitled" en el viewer
    try:
        cliente_slug = slugify(proyecto.cliente.nombre) if proyecto.cliente_id else 'cliente'
    except Exception:
        cliente_slug = 'cliente'
    try:
        folio_txt = str(getattr(proyecto, 'public_id', '') or '')
    except Exception:
        folio_txt = ''
    p.setTitle(f"Optimizacion_{folio_txt or proyecto.codigo}_{cliente_slug}")
    # Opciones de renderizado PDF (con valores por defecto)
    PDF_OPTS_DEFAULT = {
        'fast': True,               # si True, hachurar márgenes con relleno suave (más rápido)
        'hatch_spacing': 6.0,       # separación de líneas de hachurado (puntos PDF)
        'hatch_lw': 0.5,            # grosor de línea de hachura (puntos PDF)
        'hatch_useful': True,       # si True, hachura también el área útil (gris en modo rápido)
        'kerf_min_lw': 0.6,         # grosor mínimo del kerf (puntos PDF)
        'kerf_max_lw': 3.0,         # grosor máximo del kerf (puntos PDF)
        'kerf_scale': 1.0,          # factor multiplicador extra del grosor del kerf
        'draw_kerf': False,         # dibujar líneas de corte por kerf (desactivado por defecto)
        'draw_kerf_invisible': False,# trazar kerf invisible (color de fondo)
        'piece_border_lw': 0.8,     # grosor del borde de cada pieza (puntos PDF)
        'piece_border_gray': 0.0,   # color gris del borde (0=negro)
        'snap_step': 0.5,           # cuadrícula de alineación en puntos PDF para evitar desajustes
        'piece_grid': False,        # dibujar rejilla de bordes por columnas/filas (off por defecto)
    }
    _opts = dict(PDF_OPTS_DEFAULT)
    try:
        if isinstance(opts, dict):
            for k in PDF_OPTS_DEFAULT.keys():
                if k in opts and opts[k] is not None:
                    _opts[k] = opts[k]
    except Exception:
        pass
    # Modo rápido: simplificar hachurado de márgenes para acelerar generación
    FAST_PDF = bool(_opts.get('fast', True))
    PROFILE = bool(_opts.get('profile', False))
    import time as _t
    _t_total_start = _t.perf_counter() if PROFILE else None
    _prof = {
        'summary_s': 0.0,
        'boards_hatch_margin_s': 0.0,
        'boards_hatch_useful_s': 0.0,
        'boards_kerf_s': 0.0,
        'boards_pieces_s': 0.0,
        'boards_count': 0,
        'pieces_count': 0,
    }

    materiales = _materiales_desde_resultado(resultado)
    if not materiales:
        # Página mínima informativa si no hay resultado
        p.setFont("Helvetica-Bold", 16)
        p.drawString(40, height-70, f"{proyecto.nombre}")
        y = height-110
        p.setFont("Helvetica", 10)
        p.drawString(40, y, f"Cliente: {proyecto.cliente.nombre if proyecto.cliente_id else '-'}"); y -= 16
        p.drawString(40, y, f"Código de proyecto: {proyecto.codigo}"); y -= 16
        p.drawString(40, y, "No hay resultado de optimización guardado.")
        p.showPage(); p.save(); data = buf.getvalue(); buf.close(); return data

    # Página(s) de resumen con logo
    # Cache de logo para mejorar rendimiento
    _logo_reader = None
    try:
        _logo_path = finders.find('images/logo.png') or finders.find('logo.png')
        if _logo_path:
            _logo_reader = ImageReader(_logo_path)
    except Exception:
        _logo_reader = None

    def draw_logo(top_right_x, top_right_y):
        try:
            if _logo_reader:
                p.drawImage(_logo_reader, top_right_x-80, top_right_y-50, width=70, preserveAspectRatio=True, mask='auto')
        except Exception:
            pass

    def draw_table_header(y, cols):
        # Minimizar cambios de fuente
        p.setFont("Helvetica-Bold", 10)
        x=40
        for label,wc in cols:
            p.drawString(x, y, label)
            x += wc
        p.line(40, y-4, width-40, y-4)

    def draw_table_header_at(x0, y, cols, total_w):
        """Dibuja cabecera de tabla en una X específica y dentro de un ancho total dado.
        cols: lista de (label, width) cuyos anchos deben sumar <= total_w
        """
        p.setFont("Helvetica-Bold", 9)
        x = x0
        for label, wc in cols:
            p.drawString(x, y, label)
            x += wc
        # línea inferior de la cabecera limitada al ancho de la tabla
        p.line(x0, y-3, x0 + total_w, y-3)

    def normalizar_taps(taps: dict):
        """Devuelve tupla ordenada de lados con tapacanto activos.
        Nota: ya no se usa para agrupar en tablas, solo para cálculos auxiliares.
        """
        try:
            lados = tuple(sorted([k for k,v in (taps or {}).items() if v]))
            return lados
        except Exception:
            return tuple()

    def agrupar_piezas_por_material(mat):
        """Agrupa piezas por nombre y dimensiones ignorando rotación y sin dividir por veta/tapacantos.
        - Cuenta total por tipo (min(ancho, largo), max(ancho, largo)).
        - Veta: marca 'Libre' si alguna instancia del nombre/dim tiene veta libre, de lo contrario '-'.
        - Observación: si todas las instancias comparten el mismo número de lados con tapacanto
          (1, 2 o 4) se muestra, en caso contrario 'Mixto' o vacío.
        """
        # Construir lookup de veta libre a partir de 'entrada'
        veta_lookup = {}
        veta_por_nombre = {}
        try:
            for e in (mat.get('entrada') or []):
                nombre_e = e.get('nombre')
                a = int(e.get('ancho',0)); l = int(e.get('largo',0))
                # Para lookup por orientación directa y rotada
                key = (nombre_e, min(a,l), max(a,l))
                is_libre = bool(e.get('veta_libre'))
                veta_lookup[key] = 'Libre' if is_libre else '-'
                # Guardar por nombre para fallback
                if nombre_e not in veta_por_nombre:
                    veta_por_nombre[nombre_e] = is_libre
                else:
                    veta_por_nombre[nombre_e] = veta_por_nombre[nombre_e] or is_libre
        except Exception:
            pass

        grupos = {}
        for t in (mat.get('tableros') or []):
            for pz in (t.get('piezas') or []):
                a = int(pz.get('ancho',0)); l = int(pz.get('largo',0))
                key = (
                    pz.get('nombre'),
                    min(a,l),
                    max(a,l)
                )
                g = grupos.get(key)
                if not g:
                    taps = pz.get('tapacantos') or {}
                    n_lados = len([k for k,v in taps.items() if v])
                    # Veta: preferir por nombre+dimensiones sin importar rotación
                    nombre_p = pz.get('nombre')
                    veta = veta_lookup.get((nombre_p, min(a,l), max(a,l)))
                    if not veta:
                        veta = 'Libre' if veta_por_nombre.get(nombre_p) else '-'
                    g = grupos[key] = {
                        'nombre': pz.get('nombre',''),
                        'ancho': min(a,l),
                        'largo': max(a,l),
                        'veta': veta,
                        'observacion': '',
                        'cantidad': 0,
                        '_lados_set': set([n_lados]),
                    }
                else:
                    # Agregar variación de lados para decidir observación agregada
                    taps2 = pz.get('tapacantos') or {}
                    n_lados2 = len([k for k,v in taps2.items() if v])
                    g.setdefault('_lados_set', set()).add(n_lados2)
                g['cantidad'] += 1
        # Consolidar observación agregada
        for v in grupos.values():
            lados_set = v.pop('_lados_set', set())
            if len(lados_set) == 1:
                n = next(iter(lados_set))
                if n == 4:
                    v['observacion'] = '4 lados'
                elif n == 2:
                    v['observacion'] = '2 lados'
                elif n == 1:
                    v['observacion'] = '1 lado'
                else:
                    v['observacion'] = ''
            elif len(lados_set) > 1:
                v['observacion'] = 'Mixto'
        grouped_list = sorted(grupos.values(), key=lambda r: (r['nombre'], r['ancho'], r['largo']))
        return grouped_list

    # Portada global: información del proyecto + resumen de TODOS los materiales seleccionados
    try:
        materiales = _materiales_desde_resultado(resultado)
    except Exception:
        materiales = _materiales_desde_resultado(resultado)
    if materiales:
        _t_sum0 = _t.perf_counter() if PROFILE else None
        draw_logo(width-40, height-40)
        # Título e ID del proyecto
        p.setFont("Helvetica-Bold", 16)
        p.drawString(40, height-60, f"{proyecto.nombre} - {datetime.now().strftime('%d-%m-%Y')}")
        try:
            folio_txt = str(getattr(proyecto, 'public_id', '') or '') or (resultado.get('folio_proyecto') if isinstance(resultado, dict) else '')
        except Exception:
            folio_txt = ''
        if not folio_txt:
            try:
                # Compatibilidad: si aún no hay public_id, mostrar correlativo-versión
                folio_txt = f"{proyecto.correlativo}-{proyecto.version}"
            except Exception:
                folio_txt = ''
        if folio_txt:
            p.setFont("Helvetica", 10)
            p.drawRightString(width-40, height-60, f"ID del proyecto: {folio_txt}")
        # Datos base (espaciado más compacto)
        y = height-88
        p.setFont("Helvetica", 10)
        cliente_txt = (proyecto.cliente.nombre if getattr(proyecto, 'cliente_id', None) else '-')
        p.drawString(40, y, f"Cliente:  {cliente_txt}"); y -= 12
        p.drawString(40, y, f"Proyecto: {proyecto.nombre} ({proyecto.codigo})"); y -= 14
        # Resumen de materiales seleccionados
        p.setFont("Helvetica-Bold", 12)
        p.drawString(40, y, "Resumen de materiales seleccionados"); y -= 18
        draw_table_header(y, [("Material",200),("Tableros",80),("Piezas",80),("Aprovech.",100)]); y -= 18
        p.setFont("Helvetica", 10)
        for idx_mat_tbl, m in enumerate(materiales, start=1):
            mat_name_base = (m.get('material') or {}).get('nombre') or (m.get('material_nombre') or 'Material')
            mat_name = f"{idx_mat_tbl}. {mat_name_base}"
            tabs = len(m.get('tableros') or [])
            piezas_cnt = sum(len(t.get('piezas',[])) for t in (m.get('tableros') or []))
            eff = m.get('eficiencia') or m.get('eficiencia_promedio') or (resultado.get('eficiencia_promedio') if isinstance(resultado, dict) else 0) or 0
            x = 40
            p.drawString(x, y, str(mat_name)); x += 200
            p.drawString(x, y, str(tabs)); x += 80
            p.drawString(x, y, str(piezas_cnt)); x += 80
            p.drawString(x, y, f"{eff}%");
            y -= 14
            if y < 120:
                p.showPage(); draw_logo(width-40, height-40)
                y = height-90
                p.setFont("Helvetica-Bold", 12)
                p.drawString(40, y, "Resumen de materiales seleccionados (cont.)"); y -= 18
                draw_table_header(y, [("Material",200),("Tableros",80),("Piezas",80),("Aprovech.",100)]); y -= 18
                p.setFont("Helvetica", 10)
        # Resumen de piezas ubicadas (agregado por material+pieza+dimensiones+lados)
        def _taps_key_and_str(taps: dict):
            try:
                lados = []
                if (taps or {}).get('arriba'): lados.append('A')
                if (taps or {}).get('derecha'): lados.append('D')
                if (taps or {}).get('abajo'): lados.append('B')
                if (taps or {}).get('izquierda'): lados.append('I')
                return tuple(lados), (','.join(lados) if lados else '—')
            except Exception:
                return tuple(), '—'

        # Añadir un pequeño espacio extra antes del resumen de piezas
        if y >= 140:
            y -= 10
        # Si queda poco espacio, pasar a la siguiente página antes de iniciar la tabla
        if y < 120:
            p.showPage(); draw_logo(width-40, height-40)
            y = height-90
        p.setFont("Helvetica-Bold", 12)
        p.drawString(40, y, "Resumen de piezas ubicadas"); y -= 18
        piezas_cols = [("Pieza",160),("Cant.",40),("Ancho",50),("Alto",50),("Material",80),("Tapacanto",80),("Lados (A/D/B/I)",70)]
        draw_table_header(y, piezas_cols); y -= 18
        p.setFont("Helvetica", 9)

        agregados = {}
        for idx_mat, mat in enumerate(materiales, start=1):
            tap_code = (mat.get('tapacanto') or {}).get('codigo') or '—'
            for t in (mat.get('tableros') or []):
                for pz in (t.get('piezas') or []):
                    try:
                        nombre = pz.get('nombre', '')
                        a = int(pz.get('ancho', 0)); l = int(pz.get('largo', pz.get('alto', 0)))
                        w, h = (a if a <= l else l), (l if l >= a else a)
                        k_t, s_t = _taps_key_and_str(pz.get('tapacantos') or {})
                        key = (idx_mat, nombre, w, h, k_t, tap_code)
                        if key not in agregados:
                            agregados[key] = {
                                'pieza': nombre,
                                'cant': 0,
                                'ancho': w,
                                'alto': h,
                                'material': f"Material {idx_mat}",
                                'tapacanto': tap_code,
                                'lados': s_t,
                            }
                        agregados[key]['cant'] += 1
                    except Exception:
                        continue

        filas = list(agregados.values())
        filas.sort(key=lambda r: (r['material'], r['pieza'], r['ancho'], r['alto'], r['lados']))
        for row in filas:
            if y < 80:
                p.showPage(); draw_logo(width-40, height-40)
                y = height-90
                p.setFont("Helvetica-Bold", 12)
                p.drawString(40, y, "Resumen de piezas ubicadas (cont.)"); y -= 18
                draw_table_header(y, piezas_cols); y -= 18
                p.setFont("Helvetica", 9)
            x = 40
            p.drawString(x, y, str(row['pieza'])); x += piezas_cols[0][1]
            p.drawString(x, y, str(row['cant'])); x += piezas_cols[1][1]
            p.drawString(x, y, str(row['ancho'])); x += piezas_cols[2][1]
            p.drawString(x, y, str(row['alto'])); x += piezas_cols[3][1]
            p.drawString(x, y, str(row['material'])); x += piezas_cols[4][1]
            p.drawString(x, y, str(row['tapacanto'])); x += piezas_cols[5][1]
            p.drawString(x, y, str(row['lados']))
            y -= 12

        # Añadir espacio antes del detalle por material
        y -= 12
        # Detalle por material (compacto en 3 columnas)
        p.setFont("Helvetica-Bold", 12)
        p.drawString(40, y, "Detalle por material"); y -= 14
        # Config columnas: 3 columnas compactas
        col_count = 3
        col_gap = 14
        col_left_x = 40
        total_w = (width - 80)
        col_width = (total_w - (col_count-1)*col_gap) / float(col_count)
        col_mid_x = col_left_x + col_width + col_gap
        col_right_x = col_mid_x + col_width + col_gap
        line_h = 10
        from reportlab.pdfbase.pdfmetrics import stringWidth

        def wrap_text(txt, font_name, font_size, max_w):
            words = str(txt).split(' ')
            lines = []
            cur = ''
            for w in words:
                cand = (cur + (' ' if cur else '') + w)
                if stringWidth(cand, font_name, font_size) <= max_w:
                    cur = cand
                else:
                    if cur:
                        lines.append(cur)
                    cur = w
            if cur:
                lines.append(cur)
            return lines

        def material_block_lines(idx, mat):
            try:
                kerf = (mat.get('config') or {}).get('kerf', mat.get('desperdicio_sierra', 0))
                mx = (mat.get('margenes') or {}).get('margen_x', (mat.get('config') or {}).get('margen_x', 0))
                my = (mat.get('margenes') or {}).get('margen_y', (mat.get('config') or {}).get('margen_y', 0))
                orig_w = int(mat.get('tablero_ancho_original', (mat.get('material') or {}).get('ancho_original', 0)))
                orig_h = int(mat.get('tablero_largo_original', (mat.get('material') or {}).get('largo_original', 0)))
                util_w = int(mat.get('tablero_ancho_efectivo', max(0, (orig_w - 2*int(mx)))))
                util_h = int(mat.get('tablero_largo_efectivo', max(0, (orig_h - 2*int(my)))))
                tap_info = (mat.get('tapacanto') or {})
                tapc_name = tap_info.get('nombre') or ''
                tapc_code = tap_info.get('codigo') or ''
                tapc = (f"{tapc_name} ({tapc_code})".strip() if (tapc_name or tapc_code) else '—')
                tabs = len(mat.get('tableros') or [])
                pzs = sum(len(t.get('piezas',[])) for t in (mat.get('tableros') or []))
                eff = mat.get('eficiencia') or mat.get('eficiencia_promedio') or (resultado.get('eficiencia_promedio') if isinstance(resultado, dict) else 0) or 0
            except Exception:
                kerf, mx, my, orig_w, orig_h, util_w, util_h, tapc, tabs, pzs, eff = 0,0,0,0,0,0,0,'—',0,0,0
            mat_title = (mat.get('material') or {}).get('nombre') or 'Material'
            header = f"Material {idx}: {mat_title}"
            # Devuelve (texto, bold) para permitir resaltar el tapacanto sin usar **
            details = [
                (f"Kerf: {kerf} mm", False),
                (f"Márgenes: x={mx} y={my}", False),
                (f"Tablero (orig/útil): {orig_w}×{orig_h} / {util_w}×{util_h} mm", False),
                ("Tapacanto:", False),
                (tapc, True),
                (f"Tableros: {tabs}   Piezas: {pzs}", False),
                (f"Aprovechamiento: {eff}%", False),
            ]
            return header, details

        i = 1
        y_row_top = y
        while i <= len(materiales):
            # Preparar bloques para 3 columnas
            left_mat = materiales[i-1]
            mid_mat = materiales[i] if (i) < len(materiales) else None
            right_mat = materiales[i+1] if (i+1) < len(materiales) else None

            left_header, left_details = material_block_lines(i, left_mat)
            mid_header = mid_details = right_header = right_details = None
            if mid_mat is not None:
                mid_header, mid_details = material_block_lines(i+1, mid_mat)
            if right_mat is not None:
                right_header, right_details = material_block_lines(i+2, right_mat)

            # Calcular alturas (compactas)
            def block_height(header, details):
                if not header:
                    return 0
                h = len(wrap_text(header, 'Helvetica-Bold', 9, col_width)) * line_h
                if details:
                    for d, is_bold in details:
                        font = 'Helvetica-Bold' if is_bold else 'Helvetica'
                        h += len(wrap_text(d, font, 8, col_width)) * line_h
                return h

            left_height = block_height(left_header, left_details)
            mid_height = block_height(mid_header, mid_details)
            right_height = block_height(right_header, right_details)
            row_height = max(left_height, mid_height, right_height)

            if y_row_top - row_height < 80:
                # Nueva página para continuar el detalle en columnas
                p.showPage(); draw_logo(width-40, height-40)
                y_row_top = height-90
                p.setFont('Helvetica-Bold', 12)
                p.drawString(40, y_row_top, 'Detalle por material (cont.)'); y_row_top -= 14

            # Dibujar bloque izquierdo
            ycur = y_row_top
            p.setFont('Helvetica-Bold', 9)
            for line in wrap_text(left_header, 'Helvetica-Bold', 9, col_width):
                p.drawString(col_left_x, ycur, line)
                ycur -= line_h
            if left_details:
                for d, is_bold in left_details:
                    font = 'Helvetica-Bold' if is_bold else 'Helvetica'
                    p.setFont(font, 8)
                    for line in wrap_text(d, font, 8, col_width):
                        p.drawString(col_left_x, ycur, line)
                        ycur -= line_h

            # Bloque medio
            if mid_header:
                ycur_m = y_row_top
                p.setFont('Helvetica-Bold', 9)
                for line in wrap_text(mid_header, 'Helvetica-Bold', 9, col_width):
                    p.drawString(col_mid_x, ycur_m, line)
                    ycur_m -= line_h
                if mid_details:
                    for d, is_bold in mid_details:
                        font = 'Helvetica-Bold' if is_bold else 'Helvetica'
                        p.setFont(font, 8)
                        for line in wrap_text(d, font, 8, col_width):
                            p.drawString(col_mid_x, ycur_m, line)
                            ycur_m -= line_h

            # Bloque derecho
            if right_header:
                ycur_r = y_row_top
                p.setFont('Helvetica-Bold', 9)
                for line in wrap_text(right_header, 'Helvetica-Bold', 9, col_width):
                    p.drawString(col_right_x, ycur_r, line)
                    ycur_r -= line_h
                if right_details:
                    for d, is_bold in right_details:
                        font = 'Helvetica-Bold' if is_bold else 'Helvetica'
                        p.setFont(font, 8)
                        for line in wrap_text(d, font, 8, col_width):
                            p.drawString(col_right_x, ycur_r, line)
                            ycur_r -= line_h

            # Avanzar a la siguiente fila
            y_row_top -= row_height + 8
            i += 3
    if PROFILE:
        _prof['summary_s'] += (_t.perf_counter() - _t_sum0)
    p.showPage()

    # Un tablero por página, por cada material (páginas horizontales sin tabla inferior)
    for m_idx, mat in enumerate(materiales, start=1):
        # Precalcular totales globales por tipo (nombre + dimensiones normalizadas) en TODO el material
        # para que las etiquetas (i/j) coincidan con el visualizador (no por tablero).
        totales_global_por_tipo = {}
        for t_all in (mat.get('tableros') or []):
            for pz_all in (t_all.get('piezas') or []):
                a_all = int(pz_all.get('ancho', 0)); l_all = int(pz_all.get('largo', 0))
                k_all = (pz_all.get('nombre'), min(a_all, l_all), max(a_all, l_all))
                totales_global_por_tipo[k_all] = totales_global_por_tipo.get(k_all, 0) + 1

        # Contadores de corrida globales por tipo (persisten a través de todos los tableros del material)
        corridas_global_por_tipo = {}
        # Medidas efectivas
        try:
            margen_x = float((mat.get('margenes') or {}).get('margen_x', (mat.get('config') or {}).get('margen_x', 0)))
        except Exception:
            margen_x = 0.0
        try:
            margen_y = float((mat.get('margenes') or {}).get('margen_y', (mat.get('config') or {}).get('margen_y', 0)))
        except Exception:
            margen_y = 0.0

        tableros_mat = (mat.get('tableros') or [])
        total_tabs_mat = len(tableros_mat)
        for t_idx, t in enumerate(tableros_mat, start=1):
            # Preparar layout de página: logo y áreas reservadas (cabecera y tabla inferior)
            draw_logo(width-40, height-40)
            header_reserved = 90  # reservar un poco más para evitar solapes
            bottom_reserved = 20  # sin tabla inferior aquí
            margin_lr = 20
            box_w = width - 2*margin_lr
            box_h = height - (header_reserved + bottom_reserved)

            # Dimensiones del tablero (mm)
            tw = float(t.get('ancho', mat.get('tablero_ancho_original') or 1))
            th = float(t.get('largo', mat.get('tablero_largo_original') or 1))
            scale = min(box_w/tw, box_h/th) * 0.92  # hacer el tablero un poco más pequeño

            # Tablero centrado
            tW = tw*scale
            tH = th*scale
            tX = margin_lr + (box_w - tW)/2
            tY = bottom_reserved + (box_h - tH)/2

            # Helper: hachurado en un rectángulo (para márgenes/áreas)
            def hatch_rect(xh, yh, wh, hh, spacing=None, lw=None, *, cross=False, force_lines=False, stroke_gray=0.7):
                if wh <= 0 or hh <= 0:
                    return
                spacing = float(_opts.get('hatch_spacing', 6.0)) if spacing is None else spacing
                lw = float(_opts.get('hatch_lw', 0.5)) if lw is None else lw
                if FAST_PDF and not force_lines:
                    # Relleno gris muy suave sin recortes ni múltiples líneas
                    p.saveState()
                    p.setFillGray(0.95)
                    p.rect(xh, yh, wh, hh, stroke=0, fill=1)
                    p.restoreState()
                else:
                    p.saveState()
                    path = p.beginPath()
                    path.rect(xh, yh, wh, hh)
                    p.clipPath(path, stroke=0, fill=0)
                    p.setLineWidth(lw)
                    # Gris claro para no competir con piezas
                    p.setStrokeGray(stroke_gray)
                    # Dibujar líneas 45°
                    import math as _m
                    # Extender para cubrir el área recortada
                    start = -int(hh)
                    end = int(wh) + int(hh)
                    # Limitar número máximo de líneas para rendimiento
                    total_span = max(end - start, 1)
                    max_lines = 400
                    eff_spacing = max(spacing, total_span / max_lines)
                    i = start
                    while i <= end:
                        x1 = xh + i
                        y1 = yh
                        x2 = xh + i + hh
                        y2 = yh + hh
                        p.line(x1, y1, x2, y2)
                        i += eff_spacing
                    # Si se solicita hachurado cruzado, dibujar el set inverso (-45°)
                    if cross:
                        i = start
                        while i <= end:
                            x1 = xh + i
                            y1 = yh + hh
                            x2 = xh + i + hh
                            y2 = yh
                            p.line(x1, y1, x2, y2)
                            i += eff_spacing
                    p.restoreState()

            # Cabecera del tablero con resumen
            # Línea principal grande con Material y contador de tablero dentro del material (i/n)
            p.setFont("Helvetica-Bold", 14)
            header_title = (mat.get('material') or {}).get('nombre') or 'Material'
            titulo_tablero = f"Material {m_idx}: {header_title}  •  Tablero {t_idx}/{total_tabs_mat}"
            p.drawString(30, height-40, titulo_tablero)
            # ID del proyecto en esquina derecha
            try:
                folio_txt = str(getattr(proyecto, 'public_id', '') or '') or getattr(proyecto, 'folio', f"{proyecto.correlativo}-{proyecto.version}")
            except Exception:
                folio_txt = ''
            if folio_txt:
                p.setFont("Helvetica", 9)
                p.drawRightString(width-110, height-40, f"ID: {folio_txt}")  # dejar espacio para el logo
            p.setFont("Helvetica", 10)
            # Recalcular útil desde márgenes para coherencia ante cambios
            effW_mm = max(float(tw) - 2*float(margen_x), 0.0)
            effH_mm = max(float(th) - 2*float(margen_y), 0.0)
            piezas_cnt = len(t.get('piezas') or [])
            # Medidas a los costados: mostrar original y útil (líneas compactas)
            p.drawString(30, height-52, f"{int(tw)}×{int(th)} mm  •  Útil: {int(effW_mm)}×{int(effH_mm)} mm")
            kerf = (mat.get('config') or {}).get('kerf', mat.get('desperdicio_sierra', 0))
            mx = (mat.get('margenes') or {}).get('margen_x', (mat.get('config') or {}).get('margen_x', 0))
            my = (mat.get('margenes') or {}).get('margen_y', (mat.get('config') or {}).get('margen_y', 0))
            p.drawString(40, height-96, f"Piezas: {piezas_cnt}    Kerf: {kerf} mm    Márgenes: x={mx} ; y={my}")
            # Tapacanto: código y ML por tablero
            tap_info_hdr = (mat.get('tapacanto') or {})
            tap_code = tap_info_hdr.get('codigo') or ''
            tap_name = tap_info_hdr.get('nombre') or ''
            # Calcular ML del tapacanto para las piezas de este tablero
            try:
                ml_mm = 0
                for pz in (t.get('piezas') or []):
                    tc = pz.get('tapacantos') or {}
                    if tc.get('arriba'): ml_mm += int(pz.get('ancho',0))
                    if tc.get('abajo'): ml_mm += int(pz.get('ancho',0))
                    if tc.get('derecha'): ml_mm += int(pz.get('largo',0))
                    if tc.get('izquierda'): ml_mm += int(pz.get('largo',0))
                ml_txt = f"{(ml_mm/1000):.2f} m" if ml_mm else "0.00 m"
            except Exception:
                ml_txt = "—"
            # Encabezado: mostrar nombre completo del tapacanto + código
            if tap_name or tap_code:
                full_tap = f"{tap_name} ({tap_code})".strip() if tap_name or tap_code else '—'
                # Si es muy largo, recortar
                try:
                    from reportlab.pdfbase.pdfmetrics import stringWidth
                    maxW = width - 160
                    while stringWidth(f"Tapacanto: {full_tap}  |  ML: {ml_txt}", 'Helvetica', 10) > maxW and len(full_tap) > 3:
                        full_tap = full_tap[:-4] + '…'
                except Exception:
                    pass
                p.drawString(30, height-64, f"Tapacanto: {full_tap}  |  ML: {ml_txt}")
            else:
                p.drawString(30, height-64, f"Tapacanto: —  |  ML: {ml_txt}")
            # Resumen de piezas por tablero
            resumen_items = {}
            for pz in (t.get('piezas') or []):
                nombre = str(pz.get('nombre','Pieza'))
                a = int(pz.get('ancho',0)); l = int(pz.get('largo',0))
                key = (nombre, a, l)
                entry = resumen_items.get(key) or {'count': 0, 'libre': False}
                entry['count'] += 1
                entry['libre'] = entry['libre'] or bool(pz.get('veta_libre'))
                resumen_items[key] = entry
            resumen_list = []
            for (n,a,l), data in resumen_items.items():
                libre_tag = " (Libre)" if data.get('libre') else ""
                resumen_list.append(f"{n}{libre_tag} {a}×{l} × {data['count']}")
            y_summary = height-86
            max_width = (width - 80)
            line = ""; printed = 0
            from reportlab.pdfbase.pdfmetrics import stringWidth
            # Cache simple de widths para evitar recomputar
            cache_w = {}
            for item in sorted(resumen_list):
                s = (item + "; ")
                w_prev = cache_w.get(line, stringWidth(line, 'Helvetica', 9))
                w_s = cache_w.get(s, stringWidth(s, 'Helvetica', 9))
                cache_w[line] = w_prev; cache_w[s] = w_s
                if (w_prev + w_s) > max_width:
                    p.setFont("Helvetica", 9)
                    p.drawString(40, y_summary, line.rstrip())
                    y_summary -= 12
                    line = s
                    printed += 1
                    if printed >= 2:  # limitar a 2 líneas para evitar solapes
                        break
                else:
                    line += s
            if printed < 6 and line:
                p.setFont("Helvetica", 9)
                p.drawString(40, y_summary, line.rstrip(' ;'))

            # Dibujar tablero
            p.setLineWidth(1)
            p.rect(tX, tY, tW, tH)

            # Área útil y márgenes (hachurado diagonal en márgenes)
            effW = effW_mm * scale
            effH = effH_mm * scale
            offX = max(min(margen_x, tw/2.0), 0.0) * scale
            offY_top = max(min(margen_y, th/2.0), 0.0) * scale
            offYBL = tH - (offY_top + effH)

            # Rect de área útil (sin punteado, solo referencia visual opcional)
            # p.rect(tX + offX, tY + offYBL, effW, effH)

            # Márgenes: izquierda, derecha, abajo, arriba (SIEMPRE con líneas entrecruzadas)
            _tm0 = _t.perf_counter() if PROFILE else None
            # Izquierda
            hatch_rect(tX, tY, offX, tH, spacing=6, lw=0.5, cross=True, force_lines=True)
            # Derecha
            hatch_rect(tX + offX + effW, tY, max(tW - (offX + effW), 0), tH, spacing=6, lw=0.5, cross=True, force_lines=True)
            # Abajo
            hatch_rect(tX + offX, tY, effW, max(offYBL, 0), spacing=6, lw=0.5, cross=True, force_lines=True)
            # Arriba
            top_h = max(tH - (offYBL + effH), 0)
            hatch_rect(tX + offX, tY + offYBL + effH, effW, top_h, spacing=6, lw=0.5, cross=True, force_lines=True)
            if PROFILE:
                _prof['boards_hatch_margin_s'] += (_t.perf_counter() - _tm0)

            # Piezas y cortes (dos pasadas):
            # 1) Recorrer piezas para calcular posiciones y recolectar segmentos de corte
            piezas_tab = (t.get('piezas') or [])
            _cut_xs = set()
            _cut_ys = set()
            _vert_segments = {}  # x -> list[(y0,y1)]
            _horiz_segments = {} # y -> list[(x0,x1)]
            piezas_geom = []     # guardar geometría para dibujar después del kerf

            # Opcional: hachurar el área útil completa (por defecto desactivado)
            if bool(_opts.get('hatch_useful', False)):
                _tu0 = _t.perf_counter() if PROFILE else None
                try:
                    hatch_rect(tX + offX, tY + offYBL, effW, effH, cross=False, force_lines=False, stroke_gray=0.85)
                except Exception:
                    pass
                if PROFILE:
                    _prof['boards_hatch_useful_s'] += (_t.perf_counter() - _tu0)

            # Cuadrícula de alineación para evitar artefactos de anti-alias
            snap_step = float(_opts.get('snap_step', 0.5))
            def _q(v: float) -> float:
                try:
                    return round(v / snap_step) * snap_step
                except Exception:
                    return v

            raw_xs = []
            raw_ys = []
            for pieza in piezas_tab:
                aN = int(pieza.get('ancho',0)); lN = int(pieza.get('largo',0))
                rot_flag = bool(pieza.get('rotada'))
                # Dimensiones para conteo por tipo (independiente de orientación)
                kN = (pieza.get('nombre'), min(aN,lN), max(aN,lN))
                corridas_global_por_tipo[kN] = corridas_global_por_tipo.get(kN, 0) + 1
                running_tipo = pieza.get('indiceUnidad') or corridas_global_por_tipo[kN]
                total_tipo = pieza.get('totalUnidades') or totales_global_por_tipo.get(kN, 1)

                # Normalización robusta de coordenadas a relativas al área útil
                px_mm = float(pieza.get('x',0)); py_mm = float(pieza.get('y',0))
                # Usar las dimensiones tal como vienen en JSON; 'rotada' solo afecta la etiqueta/orientación.
                pa0 = float(aN); pl0 = float(lN)
                pw_mm = pa0
                ph_mm = pl0
                mx_val = float(margen_x); my_val = float(margen_y)
                def _fits(rx, ry, eps=2.0):
                    return (
                        rx >= -eps and ry >= -eps and
                        rx + pw_mm <= effW_mm + eps and
                        ry + ph_mm <= effH_mm + eps
                    )
                candA = (px_mm, py_mm)
                candB = (px_mm - mx_val, py_mm - my_val)
                if _fits(candB[0], candB[1], eps=2.0):
                    px_rel_mm, py_rel_mm = candB
                elif _fits(candA[0], candA[1], eps=2.0):
                    px_rel_mm, py_rel_mm = candA
                else:
                    rx, ry = candB
                    rx = max(0.0, min(rx, max(effW_mm - pw_mm, 0.0)))
                    ry = max(0.0, min(ry, max(effH_mm - ph_mm, 0.0)))
                    px_rel_mm, py_rel_mm = rx, ry

                px = px_rel_mm * scale
                py = py_rel_mm * scale
                w = pw_mm * scale
                h = ph_mm * scale
                # Posición superior-izquierda de la pieza en puntos PDF (snapped)
                x_raw = tX + offX + px
                y_raw = tY + offYBL + (effH - (py + h))
                x0 = _q(x_raw)
                y0 = _q(y_raw)
                x1 = _q(x_raw + w)
                y1 = _q(y_raw + h)
                x = x0; y = y0; w = max(0.0, x1 - x0); h = max(0.0, y1 - y0)
                # Guardar bordes RAW para canónico posterior
                x0_raw = x_raw; x1_raw = x_raw + w
                y0_raw = y_raw; y1_raw = y_raw + h
                raw_xs.extend([x0_raw, x1_raw]); raw_ys.extend([y0_raw, y1_raw])

                # Guardar geometría y metadatos mínimos para el dibujado posterior
                piezas_geom.append({
                    'x': x, 'y': y, 'w': w, 'h': h,
                    'x0_raw': x0_raw, 'x1_raw': x1_raw, 'y0_raw': y0_raw, 'y1_raw': y1_raw,
                    'nombre': str(pieza.get('nombre','Pieza')),
                    'pa': int(aN),
                    'pl': int(lN),
                    'rotada': rot_flag,
                    'running_tipo': running_tipo,
                    'total_tipo': total_tipo,
                    'taps': pieza.get('tapacantos') or {},
                })

                # Registrar bordes para líneas de corte globales y segmentos útiles (solo sobre rango de piezas)
                try:
                    rx0 = _q(float(x)); rx1 = _q(float(x + w))
                    ry0 = _q(float(y)); ry1 = _q(float(y + h))
                    _cut_xs.add(rx0); _cut_xs.add(rx1)
                    _cut_ys.add(ry0); _cut_ys.add(ry1)
                    _vert_segments.setdefault(rx0, []).append((ry0, ry1))
                    _vert_segments.setdefault(rx1, []).append((ry0, ry1))
                    _horiz_segments.setdefault(ry0, []).append((rx0, rx1))
                    _horiz_segments.setdefault(ry1, []).append((rx0, rx1))
                except Exception:
                    pass

            # Unificar coordenadas a valores canónicos (columnas/filas) para evitar solapes
            try:
                canon_eps = max(float(_opts.get('snap_step', 0.5)) * 0.75, 0.3)
                def build_canonical(vals, eps):
                    if not vals:
                        return []
                    arr = sorted(float(v) for v in vals)
                    groups = []
                    cur = [arr[0]]
                    for v in arr[1:]:
                        if abs(v - cur[-1]) <= eps:
                            cur.append(v)
                        else:
                            groups.append(cur); cur = [v]
                    groups.append(cur)
                    step = float(_opts.get('snap_step', 0.5))
                    reps = []
                    for gvals in groups:
                        m = sum(gvals)/len(gvals)
                        reps.append(round(m/step)*step)
                    return reps
                canon_xs = build_canonical(raw_xs, canon_eps)
                canon_ys = build_canonical(raw_ys, canon_eps)
                import bisect as _bs
                def nearest(sorted_vals, v):
                    if not sorted_vals:
                        return v
                    i = _bs.bisect_left(sorted_vals, v)
                    if i == 0:
                        return sorted_vals[0]
                    if i == len(sorted_vals):
                        return sorted_vals[-1]
                    a = sorted_vals[i-1]; b = sorted_vals[i]
                    return a if abs(v-a) <= abs(v-b) else b

                # Recalcular geometría de piezas y segmentos con coordenadas canónicas
                _vert_segments.clear(); _horiz_segments.clear()
                for g in piezas_geom:
                    x0c = nearest(canon_xs, g['x0_raw']); x1c = nearest(canon_xs, g['x1_raw'])
                    y0c = nearest(canon_ys, g['y0_raw']); y1c = nearest(canon_ys, g['y1_raw'])
                    if x1c < x0c: x0c, x1c = x1c, x0c
                    if y1c < y0c: y0c, y1c = y1c, y0c
                    g['x'] = x0c; g['y'] = y0c; g['w'] = max(0.0, x1c - x0c); g['h'] = max(0.0, y1c - y0c)
                    _vert_segments.setdefault(x0c, []).append((y0c, y1c))
                    _vert_segments.setdefault(x1c, []).append((y0c, y1c))
                    _horiz_segments.setdefault(y0c, []).append((x0c, x1c))
                    _horiz_segments.setdefault(y1c, []).append((x0c, x1c))
            except Exception:
                pass

            # Dibujar líneas de corte (kerf)
            # - visible si draw_kerf=True
            # - invisible (color de fondo) si draw_kerf_invisible=True
            if bool(_opts.get('draw_kerf', False)) or bool(_opts.get('draw_kerf_invisible', False)):
                try:
                    _tk0 = _t.perf_counter() if PROFILE else None
                    p.saveState()
                    # Grosor del kerf en puntos PDF
                    try:
                        kerf_mm = float((mat.get('config') or {}).get('kerf', mat.get('desperdicio_sierra', 0)) or 0)
                    except Exception:
                        kerf_mm = 0.0
                    # Grosor parametrizable
                    k_min = float(_opts.get('kerf_min_lw', 0.6))
                    k_max = float(_opts.get('kerf_max_lw', 3.0))
                    k_scale = float(_opts.get('kerf_scale', 1.0))
                    lw = max(k_min, min(k_max, kerf_mm * float(scale) * k_scale))
                    p.setLineWidth(lw)
                    if bool(_opts.get('draw_kerf', False)):
                        p.setStrokeGray(0.15)  # visible, gris oscuro
                    else:
                        # invisible: color de fondo del área útil (gris muy claro / blanco)
                        # Usamos blanco para minimizar cualquier huella visual.
                        p.setStrokeGray(1.0)
                    # Sin dash: línea normal continua
                    # Limitar a área útil para no marcar en puro desperdicio
                    x_min = tX + offX + 0.1
                    x_max = tX + offX + effW - 0.1
                    y_min = tY + offYBL + 0.1
                    y_max = tY + offYBL + effH - 0.1
                    # Helper: fusionar intervalos sin unir huecos visibles
                    def merge_intervals(intervals, eps=0.8):
                        if not intervals:
                            return []
                        ivs = sorted([(min(a,b), max(a,b)) for a,b in intervals], key=lambda t: t[0])
                        merged = []
                        cs, ce = ivs[0]
                        for s,e in ivs[1:]:
                            if s <= ce + eps:  # solape o muy pegado -> fusionar
                                ce = max(ce, e)
                            else:
                                merged.append((cs, ce))
                                cs, ce = s, e
                        merged.append((cs, ce))
                        return merged

                    # Verticales: dibujar cada intervalo fusionado dentro del área útil
                    for cx, segs in _vert_segments.items():
                        if cx <= x_min or cx >= x_max:
                            continue  # evitar bordes
                        for s,e in merge_intervals(segs):
                            y0 = max(y_min, s)
                            y1 = min(y_max, e)
                            if y1 - y0 > 0.5:
                                p.line(cx, y0, cx, y1)
                    # Horizontales
                    for cy, segs in _horiz_segments.items():
                        if cy <= y_min or cy >= y_max:
                            continue
                        for s,e in merge_intervals(segs):
                            x0 = max(x_min, s)
                            x1 = min(x_max, e)
                            if x1 - x0 > 0.5:
                                p.line(x0, cy, x1, cy)
                    p.restoreState()
                except Exception:
                    try:
                        p.restoreState()
                    except Exception:
                        pass
                if PROFILE:
                    _prof['boards_kerf_s'] += (_t.perf_counter() - _tk0)

            # 2) DIBUJAR PIEZAS y etiquetas/tapacantos por ENCIMA
            _tp0 = _t.perf_counter() if PROFILE else None
            for g in piezas_geom:
                x, y, w, h = g['x'], g['y'], g['w'], g['h']
                nombre = g['nombre']
                pa, pl = g['pa'], g['pl']
                rot_flag = g['rotada']
                running_tipo = g['running_tipo']
                total_tipo = g['total_tipo']
                taps = g['taps']

                # Rectángulo de la pieza: relleno blanco + borde fino independiente del kerf
                p.setFillGray(1.0)
                p.setStrokeGray(float(_opts.get('piece_border_gray', 0.0)))
                p.setLineWidth(float(_opts.get('piece_border_lw', 0.8)))
                try:
                    p.setLineCap(0); p.setLineJoin(0)
                except Exception:
                    pass
                p.rect(x, y, w, h, stroke=1, fill=1)

                # Etiquetas mínimas
                rot = ' ↻' if rot_flag else ''
                et1 = f"{nombre} ({running_tipo}/{total_tipo}){rot}"
                et2 = f"{pa}×{pl} mm"
                try:
                    from reportlab.pdfbase.pdfmetrics import stringWidth
                    fs1, fs2 = 7.5, 7
                    is_vertical = h >= w
                    maxW = max((h if is_vertical else w) - 6, 10)
                    while fs1 > 4 and stringWidth(et1, 'Helvetica-Bold', fs1) > maxW:
                        fs1 -= 0.5
                    while fs2 > 4 and stringWidth(et2, 'Helvetica', fs2) > maxW:
                        fs2 -= 0.5
                except Exception:
                    fs1, fs2 = 7.5, 7
                    is_vertical = h >= w

                # Clip y nombre orientado
                p.saveState()
                clip = p.beginPath(); clip.rect(x, y, w, h); p.clipPath(clip, stroke=0, fill=0)
                p.setFillGray(0)
                try:
                    from reportlab.pdfbase.pdfmetrics import stringWidth
                    orient_vertical = h >= w
                    max_font = max(4.0, min(fs1, (min(w, h) - 6) * 0.9))
                    fs_name = max_font
                    max_run = max((h if orient_vertical else w) - 6, 8)
                    while fs_name > 4 and stringWidth(et1, 'Helvetica-Bold', fs_name) > max_run:
                        fs_name -= 0.5
                    p.setFont('Helvetica-Bold', fs_name)
                    cx, cy = (x + w/2.0, y + h/2.0)
                    if orient_vertical:
                        p.saveState(); p.translate(cx, cy); p.rotate(90)
                        p.drawCentredString(0, -fs_name/3.0, et1)
                        p.restoreState()
                    else:
                        p.drawCentredString(cx, cy - fs_name/3.0, et1)
                except Exception:
                    try:
                        p.setFont('Helvetica-Bold', fs1)
                        p.drawCentredString(x + w/2.0, y + h/2.0, et1)
                    except Exception:
                        pass

                # Medidas en lados (usar valores del JSON directo; la rotación solo gira el texto)
                label_w = f"{pa} mm"; label_h = f"{pl} mm"
                try:
                    from reportlab.pdfbase.pdfmetrics import stringWidth
                    fw = fs2; fh = fs2
                    max_w_w = max(w - 6, 6); max_w_h = max(h - 6, 6)
                    while fw > 4 and stringWidth(label_w, 'Helvetica', fw) > max_w_w:
                        fw -= 0.5
                    while fh > 4 and stringWidth(label_h, 'Helvetica', fh) > max_w_h:
                        fh -= 0.5
                except Exception:
                    fw = fs2; fh = fs2

                try:
                    p.setFont('Helvetica', fw)
                    y_label = y + h - (fw + 2)
                    p.drawCentredString(x + w/2, y_label, label_w)
                except Exception:
                    pass

                try:
                    p.saveState(); p.setFont('Helvetica', fh)
                    rx = x + w - (fh/2) - 2; ry = y + h/2
                    p.translate(rx, ry); p.rotate(90)
                    p.drawCentredString(0, 0, label_h)
                    p.restoreState()
                except Exception:
                    try: p.restoreState()
                    except Exception: pass

                p.restoreState()

                # Tapacantos internos
                if any((taps or {}).values()):
                    p.saveState()
                    # Estilo B/N: trazo negro en vez de rojo
                    p.setStrokeGray(0.0)
                    p.setLineWidth(1.2)
                    p.setDash(3, 2)
                    inset = 6.0 * scale
                    inset = max(0.5, min(inset, (min(w, h) / 2.0) - 0.5))
                    if taps.get('arriba'):
                        p.line(x + inset, y + h - inset, x + w - inset, y + h - inset)
                    if taps.get('abajo'):
                        p.line(x + inset, y + inset, x + w - inset, y + inset)
                    if taps.get('izquierda'):
                        p.line(x + inset, y + inset, x + inset, y + h - inset)
                    if taps.get('derecha'):
                        p.line(x + w - inset, y + inset, x + w - inset, y + h - inset)
                    p.restoreState()
            if PROFILE:
                _prof['boards_pieces_s'] += (_t.perf_counter() - _tp0)
                _prof['pieces_count'] += len(piezas_geom)

            # 3) DIBUJAR REJILLA (opcional). Si kerf visible activo, no dibujar rejilla.
            if (not bool(_opts.get('draw_kerf', False))) and bool(_opts.get('piece_grid', False)):
                try:
                    p.saveState()
                    p.setStrokeGray(float(_opts.get('piece_border_gray', 0.0)))
                    p.setLineWidth(float(_opts.get('piece_border_lw', 0.8)))
                    try:
                        p.setLineCap(0)   # butt cap: sin sobresalir
                        p.setLineJoin(0)  # miter join: esquinas nítidas
                    except Exception:
                        pass
                    def merge_intervals(intervals, eps=0.2):
                        """Fusiona intervalos [a,b] que se solapan o están muy cerca."""
                        if not intervals:
                            return []
                        ivs = sorted([(min(a, b), max(a, b)) for a, b in intervals], key=lambda t: t[0])
                        merged = []
                        cs, ce = ivs[0]
                        for s, e in ivs[1:]:
                            if s <= ce + eps:
                                ce = max(ce, e)
                            else:
                                merged.append((cs, ce))
                                cs, ce = s, e
                        merged.append((cs, ce))
                        return merged
                    # Verticales
                    for cx, segs in _vert_segments.items():
                        for s,e in merge_intervals(segs):
                            if e - s > 0.3:
                                p.line(cx, s, cx, e)
                    # Horizontales
                    for cy, segs in _horiz_segments.items():
                        for s,e in merge_intervals(segs):
                            if e - s > 0.3:
                                p.line(s, cy, e, cy)
                    p.restoreState()
                except Exception:
                    try: p.restoreState()
                    except Exception: pass

            # En esta sección ya no se imprime tabla inferior; se dedica toda la página al tablero
            p.showPage()
            if PROFILE:
                _prof['boards_count'] += 1

        # Tras imprimir los tableros de este material, agregar hoja(s) resumen del material
        # 1) Resumen general del material + (en la misma hoja) resumen de piezas por tablero
        draw_logo(width-40, height-40)
        p.setFont('Helvetica-Bold', 13)
        mat_title = (mat.get('material') or {}).get('nombre') or 'Material'
        p.drawString(30, height-40, f"Resumen Material {m_idx}: {mat_title}")
        # Datos generales del material
        try:
            orig_w = int(mat.get('tablero_ancho_original', (mat.get('material') or {}).get('ancho_original', 0)))
            orig_h = int(mat.get('tablero_largo_original', (mat.get('material') or {}).get('largo_original', 0)))
            mx = int((mat.get('margenes') or {}).get('margen_x', (mat.get('config') or {}).get('margen_x', 0)))
            my = int((mat.get('margenes') or {}).get('margen_y', (mat.get('config') or {}).get('margen_y', 0)))
            util_w = max(0, orig_w - 2*mx)
            util_h = max(0, orig_h - 2*my)
        except Exception:
            orig_w = orig_h = util_w = util_h = mx = my = 0
        tap_info = mat.get('tapacanto') or {}
        tap_txt = (f"{tap_info.get('nombre','')} ({tap_info.get('codigo','')})".strip() if (tap_info.get('nombre') or tap_info.get('codigo')) else '—')
        p.setFont('Helvetica', 10)
        p.drawString(30, height-60, f"Tableros: {len(mat.get('tableros') or [])}")
        p.drawString(150, height-60, f"Medidas tablero: {orig_w}×{orig_h} mm  |  Útil: {util_w}×{util_h} mm (mx={mx}, my={my})")
        p.drawString(30, height-76, f"Tapacanto: {tap_txt}")

        # Tabla de todas las piezas del material (agregada por tipo)
        def _agregar_por_tipo(mat):
            agg = {}
            for t in (mat.get('tableros') or []):
                for pz in (t.get('piezas') or []):
                    key = (pz.get('nombre'), int(pz.get('ancho',0)), int(pz.get('largo',0)))
                    item = agg.get(key) or {'nombre': key[0], 'ancho': key[1], 'largo': key[2], 'cantidad': 0}
                    item['cantidad'] += 1
                    agg[key] = item
            return sorted(agg.values(), key=lambda r: (r['nombre'], r['ancho'], r['largo']))

        rows = _agregar_por_tipo(mat)
        ycur = height-100
        draw_table_header(ycur, [("Pieza",180),("Cantidad",80),("Ancho",80),("Alto",80)])
        ycur -= 18
        p.setFont('Helvetica', 9)
        for r in rows:
            if ycur < 60:
                p.showPage(); draw_logo(width-40, height-40)
                p.setFont('Helvetica-Bold', 12); p.drawString(30, height-40, f"Resumen Material {m_idx}: {mat_title} (cont.)")
                ycur = height-70
                draw_table_header(ycur, [("Pieza",180),("Cantidad",80),("Ancho",80),("Alto",80)])
                ycur -= 18
                p.setFont('Helvetica', 9)
            x = 30
            p.drawString(x, ycur, str(r['nombre'])); x += 180
            p.drawString(x, ycur, str(r['cantidad'])); x += 80
            p.drawString(x, ycur, str(r['ancho'])); x += 80
            p.drawString(x, ycur, str(r['largo']))
            ycur -= 12

        # 2) Una o más tablas por tablero: piezas que contiene, cantidad, ancho, alto, si lleva tapacanto y lados
        def _label_lados_tuple(lados_tuple):
            try:
                if not lados_tuple:
                    return '—'
                # Usar iniciales compactas para evitar solapes en la tabla resumen
                orden = ['arriba','derecha','abajo','izquierda']
                iniciales = {'arriba':'A','derecha':'D','abajo':'B','izquierda':'I'}
                parts = [iniciales[k] for k in orden if k in set(lados_tuple)]
                return '—' if not parts else ','.join(parts)
            except Exception:
                return '—'

        # 2) Resumen por tablero (dos tablas paralelas, compactas)
        # Configuración de columnas compactas
        left_x = 30
        gap_x = 20
        table_w = (width - 2*left_x - gap_x) / 2.0  # ancho de cada tabla
        cols = [("Pieza", 140), ("Cant.", 40), ("Ancho", 60), ("Alto", 60), ("Tapacanto", table_w - (140+40+60+60))]
        row_h = 11  # altura de fila compacta

        col_idx = 0  # 0: izquierda, 1: derecha
        col_x = [left_x, left_x + table_w + gap_x]
        col_y = [ycur, ycur]

        for t_idx2, t2 in enumerate(tableros_mat, start=1):
            # Decidir la columna donde dibujar este tablero
            x0 = col_x[col_idx]
            y0 = col_y[col_idx]

            # Si no hay espacio suficiente para el título + cabecera + al menos 1 fila, saltar página y resetear columnas
            min_block_h = 14 + 15 + row_h  # título + cabecera + 1 fila
            if y0 < 40 + min_block_h:
                p.showPage(); draw_logo(width-40, height-40)
                p.setFont('Helvetica-Bold', 12); p.drawString(30, height-40, f"Resumen Material {m_idx}: {mat_title} (cont.)")
                # resetear columnas al tope
                col_y = [height-70, height-70]
                y0 = col_y[col_idx]

            # Título del tablero (separado del bloque superior por el salto lógico previo; aquí pegado a su propia tabla)
            p.setFont('Helvetica-Bold', 11)
            p.drawString(x0, y0, f"Tablero {t_idx2}/{total_tabs_mat}")
            y0 -= 14

            # Agrupar filas del tablero actual
            grupos = {}
            for pz in (t2.get('piezas') or []):
                key = (pz.get('nombre'), int(pz.get('ancho',0)), int(pz.get('largo',0)), tuple(sorted([k for k,v in (pz.get('tapacantos') or {}).items() if v])))
                it = grupos.get(key) or {
                    'nombre': key[0], 'ancho': key[1], 'largo': key[2], 'cantidad': 0,
                    'tapacanto': _label_lados_tuple(key[3])
                }
                it['cantidad'] += 1
                grupos[key] = it
            filas = sorted(grupos.values(), key=lambda r: (r['nombre'], r['ancho'], r['largo']))

            # Cabecera en la columna
            draw_table_header_at(x0, y0, cols, table_w)
            y0 -= 15
            p.setFont('Helvetica', 8.8)

            # Filas compactas sin espaciado extra entre líneas
            for row in filas:
                # Si no cabe en la columna actual, pasar a la otra columna o nueva página si ya estamos en derecha
                if y0 < 40 + row_h:
                    if col_idx == 0:
                        # Pasar a la columna derecha, usando su y actual
                        col_idx = 1
                        x0 = col_x[col_idx]
                        y0 = col_y[col_idx]
                        # Asegurar espacio en la derecha; si no hay, nueva página
                        if y0 < 40 + (14 + 15 + row_h):
                            p.showPage(); draw_logo(width-40, height-40)
                            p.setFont('Helvetica-Bold', 12); p.drawString(30, height-40, f"Resumen Material {m_idx}: {mat_title} (cont.)")
                            col_y = [height-70, height-70]
                            y0 = col_y[col_idx]
                        # Redibujar título y cabecera en la nueva columna
                        p.setFont('Helvetica-Bold', 11)
                        p.drawString(x0, y0, f"Tablero {t_idx2}/{total_tabs_mat}"); y0 -= 14
                        draw_table_header_at(x0, y0, cols, table_w); y0 -= 15
                        p.setFont('Helvetica', 8.8)
                    else:
                        # Ya estamos en derecha -> nueva página y reset de ambas columnas
                        p.showPage(); draw_logo(width-40, height-40)
                        p.setFont('Helvetica-Bold', 12); p.drawString(30, height-40, f"Resumen Material {m_idx}: {mat_title} (cont.)")
                        col_y = [height-70, height-70]
                        # Continuar en izquierda (más natural)
                        col_idx = 0
                        x0 = col_x[col_idx]
                        y0 = col_y[col_idx]
                        # Redibujar título y cabecera
                        p.setFont('Helvetica-Bold', 11)
                        p.drawString(x0, y0, f"Tablero {t_idx2}/{total_tabs_mat}"); y0 -= 14
                        draw_table_header_at(x0, y0, cols, table_w); y0 -= 15
                        p.setFont('Helvetica', 8.8)

                # Dibujar la fila
                x = x0
                p.drawString(x, y0, str(row['nombre'])); x += cols[0][1]
                p.drawString(x, y0, str(row['cantidad'])); x += cols[1][1]
                p.drawString(x, y0, str(row['ancho'])); x += cols[2][1]
                p.drawString(x, y0, str(row['largo'])); x += cols[3][1]
                p.drawString(x, y0, row.get('tapacanto','—'))
                y0 -= row_h

            # Guardar la Y final de esta columna y alternar columna para el siguiente tablero
            col_y[col_idx] = y0 - 6  # pequeño colchón entre tablas dentro de la misma columna
            col_idx = 1 - col_idx
        # Ajustar ycur al mínimo de ambas columnas para no interferir con el salto final
        ycur = min(col_y)

        # Asegurar separación: tras terminar el resumen del material actual,
        # forzar salto de página si no es el último material, para que
        # el próximo bloque de tableros comience en una página nueva.
        try:
            if m_idx < len(materiales):
                p.showPage()
        except Exception:
            # Si por alguna razón no podemos evaluar la longitud, 
            # no forzar salto adicional para evitar página en blanco final.
            pass

    p.save()
    if PROFILE:
        total_s = (_t.perf_counter() - _t_total_start)
        try:
            print("PDF_PROFILE | resumen_s=%.3fs boards_hatch_margin_s=%.3fs boards_hatch_useful_s=%.3fs boards_kerf_s=%.3fs boards_pieces_s=%.3fs boards=%d piezas=%d total=%.3fs" % (
                _prof['summary_s'], _prof['boards_hatch_margin_s'], _prof['boards_hatch_useful_s'], _prof['boards_kerf_s'], _prof['boards_pieces_s'], _prof['boards_count'], _prof['pieces_count'], total_s
            ))
        except Exception:
            pass
    data = buf.getvalue(); buf.close(); return data

# ------------------------------
# Utilidades: reconstrucción del resultado desde configuración
# ------------------------------
def _optimizar_desde_conf_mat(conf_mat: dict, piezas_in: list):
    """Ejecuta el motor de optimización para un material+lista de piezas del payload de configuración."""
    if not (conf_mat and piezas_in and conf_mat.get('material_id')):
        return None
    material_id = conf_mat.get('material_id')
    material = get_object_or_404(Material, id=material_id)
    ancho_tablero = conf_mat.get('ancho_custom') or material.ancho
    largo_tablero = conf_mat.get('largo_custom') or material.largo
    margen_x = conf_mat.get('margen_x', 0)
    margen_y = conf_mat.get('margen_y', 0)
    desperdicio_sierra = conf_mat.get('desperdicio_sierra', 3)
    tapacanto_codigo = conf_mat.get('tapacanto_codigo', '')
    tapacanto_nombre = conf_mat.get('tapacanto_nombre', '')
    engine = OptimizationEngine(ancho_tablero, largo_tablero, margen_x, margen_y, desperdicio_sierra)
    piezas_proc = []
    for p in piezas_in:
        piezas_proc.append({
            'nombre': p['nombre'],
            'ancho': p['ancho'],
            'largo': p['largo'],
            'cantidad': p.get('cantidad', 1),
            'veta_libre': p.get('veta_libre', False),
            'tapacantos': p.get('tapacantos', {}) or {}
        })
    r = engine.optimizar_piezas(piezas_proc)
    r['entrada'] = piezas_proc
    r['material'] = {
        'nombre': material.nombre,
        'codigo': material.codigo,
        'ancho_original': material.ancho,
        'largo_original': material.largo,
        'ancho_usado': ancho_tablero,
        'largo_usado': largo_tablero
    }
    r['config'] = {'margen_x': margen_x, 'margen_y': margen_y, 'kerf': desperdicio_sierra}
    r['tapacanto'] = { 'codigo': tapacanto_codigo, 'nombre': tapacanto_nombre }
    return r

def _resultado_desde_configuracion(proyecto):
    """Intenta construir un resultado completo desde proyecto.configuracion (1 o varios materiales)."""
    if not proyecto.configuracion:
        return None
    try:
        cfg = json.loads(proyecto.configuracion) if isinstance(proyecto.configuracion, str) else proyecto.configuracion
    except Exception:
        return None

    materiales = []
    try:
        if isinstance(cfg, dict) and isinstance(cfg.get('materiales'), list):
            for mcfg in cfg['materiales']:
                conf_mat = mcfg.get('configuracion_material') or mcfg.get('config')
                piezas_in = mcfg.get('piezas') or mcfg.get('entrada')
                r = _optimizar_desde_conf_mat(conf_mat, piezas_in)
                if r:
                    materiales.append(r)
        else:
            conf_mat = cfg.get('configuracion_material') or cfg.get('config')
            piezas_in = cfg.get('piezas') or cfg.get('entrada')
            r = _optimizar_desde_conf_mat(conf_mat, piezas_in)
            if r:
                materiales.append(r)
    except Exception:
        return None

    if not materiales:
        return None

    total_tableros = sum(len(m.get('tableros', [])) for m in materiales)
    total_piezas = sum(sum(len(t.get('piezas', [])) for t in m.get('tableros', [])) for m in materiales)
    eficiencias = [m.get('eficiencia') or m.get('eficiencia_promedio') for m in materiales if m]
    eff_vals = [e for e in eficiencias if e]
    eficiencia_promedio = (sum(eff_vals) / len(eff_vals)) if eff_vals else 0
    folio = f"OPT-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    resultado_persist = {
        'materiales': materiales,
        'total_tableros': total_tableros,
        'total_piezas': total_piezas,
        'eficiencia_promedio': eficiencia_promedio,
        'ultimo_folio': folio,
        'historial': [{
            'folio': folio,
            'fecha': datetime.now().isoformat(),
            'materiales': materiales,
            'total_tableros': total_tableros,
            'total_piezas': total_piezas,
            'eficiencia_promedio': eficiencia_promedio,
        }]
    }
    return resultado_persist

@login_required
def optimizador_home_nuevo(request):
    """Alias: redirige a la versión clásica (hoja final)."""
    return redirect('optimizador_home')

@login_required
def optimizador_home(request):
    """Vista principal del optimizador. Por ahora redirige a la versión clásica."""
    # Unificación de acceso: si rol autoservicio, delegar a vista especializada
    try:
        perfil = getattr(request.user, 'usuarioperfiloptimizador', None)
        if perfil and getattr(perfil, 'rol', None) == 'autoservicio':
            return optimizador_autoservicio(request)
    except Exception:
        pass
    return optimizador_home_clasico(request)

def optimizador_home_test(request):
    """Vista de prueba del optimizador (sin auth en urls se marca temporal)."""
    return optimizador_home_clasico(request)

def js_test(request):
    """Vista de test de JavaScript simple."""
    return HttpResponse("OK")

@login_required
def optimizador_abrir(request, proyecto_id:int):
    """Abrir el optimizador precargando un proyecto existente (por id)."""
    try:
        # Validar existencia (y permisos) de proyecto, pero no cargar aquí la data
        get_object_or_404(Proyecto, id=proyecto_id)
        # Redirigir con query param para que el frontend se encargue de cargar datos
        return redirect(f"{reverse('optimizador_home')}?proyecto_id={proyecto_id}")
    except Exception:
        return redirect('optimizador_home')

@login_required
def preview_proyecto_json(request, proyecto_id:int):
    """Stub: devuelve un JSON básico de preview para el modal de organización."""
    try:
        proyecto = get_object_or_404(Proyecto, id=proyecto_id)
        resumen = {
            'success': True,
            'proyecto': {
                'codigo': proyecto.codigo,
                'nombre': proyecto.nombre,
                'cliente': (proyecto.cliente.nombre if proyecto.cliente_id else '-'),
                'estado': proyecto.estado,
                'fecha': proyecto.fecha_creacion.strftime('%d-%m-%Y %H:%M') if proyecto.fecha_creacion else ''
            }
        }
        return JsonResponse(resumen)
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=500)

@login_required 
@csrf_exempt
def crear_proyecto_optimizacion(request):
    """Crea un nuevo proyecto de optimización con todos los campos requeridos"""
    if request.method == 'POST':
        try:
            data = json.loads(request.body or '{}')
            nombre = data.get('nombre') or 'Proyecto sin nombre'
            cliente_id = data.get('cliente_id')
            descripcion = data.get('descripcion', '')
            # Solo guardar configuración si viene explícitamente; evitar guardar el payload completo
            configuracion = data.get('configuracion') if isinstance(data.get('configuracion'), (dict, list)) else None

            # Para autoservicio: priorizar cliente de sesión, pero permitir actualizarlo
            try:
                perfil = getattr(request.user, 'usuarioperfiloptimizador', None)
                if perfil and perfil.rol == 'autoservicio':
                    from WowDash.autoservicio_views import SESSION_KEY_CLIENTE
                    session_cliente_id = request.session.get(SESSION_KEY_CLIENTE)
                    
                    # Si NO hay cliente en sesión, requerir que venga en la petición
                    if not session_cliente_id:
                        if not cliente_id:
                            return JsonResponse({'success': False, 'message': 'Debe seleccionar o ingresar un cliente primero'}, status=400)
                        # Guardar el cliente seleccionado en sesión para futuros proyectos
                        request.session[SESSION_KEY_CLIENTE] = cliente_id
                    else:
                        # Ya hay cliente en sesión: usarlo
                        # Si viene un cliente_id diferente, actualizarlo en sesión
                        if cliente_id and cliente_id != session_cliente_id:
                            request.session[SESSION_KEY_CLIENTE] = cliente_id
                        else:
                            cliente_id = session_cliente_id
            except Exception:
                pass

            # Si no llega cliente_id, intentar crear/buscar por nombre+rut
            if not cliente_id:
                nombre_cliente = (data.get('cliente_nombre') or '').strip()
                rut_cliente_raw = (data.get('cliente_rut') or '')
                rut_cliente = _normalize_rut(rut_cliente_raw)
                if nombre_cliente and rut_cliente:
                    # Determinar organización desde el usuario autenticado
                    org = None
                    try:
                        if hasattr(request.user, 'usuarioperfiloptimizador') and request.user.usuarioperfiloptimizador.organizacion:
                            org = request.user.usuarioperfiloptimizador.organizacion
                        elif hasattr(request.user, 'usuario_perfil_optimizador') and request.user.usuario_perfil_optimizador.organizacion:
                            org = request.user.usuario_perfil_optimizador.organizacion
                    except Exception:
                        org = None

                    # Buscar/crear cliente por RUT dentro del alcance de la organización
                    if org:
                        cliente, creado = Cliente.objects.get_or_create(
                            rut=rut_cliente,
                            organizacion=org,
                            defaults={'nombre': nombre_cliente, 'activo': True}
                        )
                    else:
                        # Sin organización asociada al usuario: usar NULL como scope
                        cliente, creado = Cliente.objects.get_or_create(
                            rut=rut_cliente,
                            organizacion__isnull=True,
                            defaults={'nombre': nombre_cliente, 'activo': True, 'organizacion': None}
                        )
                    # Si ya existía y no tenía organización, asignarla
                    if not creado and org and not cliente.organizacion:
                        cliente.organizacion = org
                        cliente.save(update_fields=['organizacion'])
                    cliente_id = cliente.id
                else:
                    return JsonResponse({'success': False, 'message': 'cliente_id es requerido'})

            # Generar código único
            base = 'PROJ'
            sec = datetime.now().strftime('%Y%m%d%H%M%S')
            codigo = f"{base}-{sec}"

            # Asignar correlativo único por cliente: max+1
            try:
                ultimo = Proyecto.objects.filter(cliente_id=cliente_id).order_by('-correlativo').first()
                correlativo = (ultimo.correlativo + 1) if ultimo and (ultimo.correlativo is not None) else 1
            except Exception:
                correlativo = 1

            # Determinar siguiente public_id global iniciando en 100
            try:
                ultimo_pub = Proyecto.objects.exclude(public_id__isnull=True).order_by('-public_id').first()
                next_public_id = (ultimo_pub.public_id + 1) if ultimo_pub and ultimo_pub.public_id and ultimo_pub.public_id >= 100 else 100
            except Exception:
                next_public_id = 100

            ctx = get_auth_context(request)
            proyecto = Proyecto.objects.create(
                codigo=codigo,
                nombre=nombre,
                cliente_id=cliente_id,
                descripcion=descripcion,
                estado='borrador',
                fecha_inicio=timezone.now().date(),
                total_materiales=0,
                total_tableros=0,
                total_piezas=0,
                eficiencia_promedio=0,
                costo_total=0,
                usuario=request.user,
                creado_por=request.user,
                configuracion=configuracion,
                correlativo=correlativo,
                version=0,
                public_id=next_public_id,
                organizacion_id=ctx.get('organization_id'),
            )
            # Auditoría de creación de proyecto
            try:
                AuditLog.objects.create(
                    actor=request.user,
                    organizacion=proyecto.organizacion,
                    verb='CREATE',
                    target_model='Proyecto',
                    target_id=str(proyecto.id),
                    target_repr=f"{proyecto.codigo} - {proyecto.nombre}",
                    changes={'cliente_id': cliente_id}
                )
            except Exception:
                pass

            return JsonResponse({
                'success': True,
                'proyecto_id': proyecto.id,
                'codigo': proyecto.codigo,
                'folio': str(proyecto.public_id) if proyecto.public_id else getattr(proyecto, 'folio', f"{proyecto.correlativo}-{proyecto.version}"),
                'message': 'Proyecto creado exitosamente'
            })

        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': f'Error al crear proyecto: {str(e)}'
            })

    return JsonResponse({'success': False, 'message': 'Método no permitido'})

@login_required
@csrf_exempt  
def optimizar_material(request):
    """Ejecuta la optimización del material"""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            # Idempotencia: si viene desde frontend con tableros y firma igual a la última, devolver sin cambios
            try:
                tableros_in = data.get('tableros')
                if isinstance(tableros_in, list) and tableros_in:
                    # Construir firma estable
                    sig_parts = []
                    for t in tableros_in[:50]:
                        piezas_sig = []
                        for p in (t.get('piezas') or [])[:1000]:
                            piezas_sig.append(f"{p.get('nombre','')}@{p.get('x')}:{p.get('y')}:{p.get('ancho')}x{p.get('largo') or p.get('alto')}:{int(bool(p.get('rotada')))}")
                        sig_parts.append(f"T{t.get('numero')}|{','.join(piezas_sig)}")
                    layout_signature = hashlib.sha256(('|'.join(sig_parts)).encode('utf-8')).hexdigest()
                    last_sig = request.session.get('last_layout_signature')
                    last_sig_ts = request.session.get('last_layout_sig_ts') or 0
                    now_ts = time.time()
                    if last_sig and last_sig == layout_signature and (now_ts - last_sig_ts) < 5:
                        # Responder éxito sin recalcular ni actualizar folio/version
                        return JsonResponse({'success': True, 'idempotent': True, 'mensaje': 'Layout repetido (omitido)', 'folio': None})
                    request.session['last_layout_signature'] = layout_signature
                    request.session['last_layout_sig_ts'] = now_ts
            except Exception:
                pass
            
            # Obtener configuración del material
            config = data['configuracion_material']
            material_id = config['material_id']
            material = get_object_or_404(Material, id=material_id)
            
            # Dimensiones del tablero - SIEMPRE usar las medidas de los campos editables
            # Estas son la fuente de verdad para la optimización
            ancho_tablero = config.get('ancho_custom') or material.ancho
            largo_tablero = config.get('largo_custom') or material.largo
            
            print(f"Optimización usando dimensiones del tablero: {ancho_tablero}mm x {largo_tablero}mm")
            print(f"Material original: {material.ancho}mm x {material.largo}mm")
            
            # Parámetros de optimización
            margen_x = config.get('margen_x', 0)
            margen_y = config.get('margen_y', 0)
            desperdicio_sierra = config.get('desperdicio_sierra', 3)
            tapacanto_codigo = config.get('tapacanto_codigo', '')
            tapacanto_nombre = config.get('tapacanto_nombre', '')
            
            # Crear motor de optimización
            engine = OptimizationEngine(
                ancho_tablero, largo_tablero,
                margen_x, margen_y, desperdicio_sierra
            )
            
            # Procesar piezas
            piezas = data['piezas']
            piezas_procesadas = []
            
            for pieza in piezas:
                piezas_procesadas.append({
                    'nombre': pieza['nombre'],
                    'ancho': pieza['ancho'],
                    'largo': pieza['largo'],
                    'cantidad': pieza['cantidad'],
                    'veta_libre': pieza.get('veta_libre', False),
                    'tapacantos': pieza.get('tapacantos', [])
                })
            
            # Si el frontend ya realizó la optimización y envía "tableros", evitar recomputar para no duplicar costo.
            resultado = None
            try:
                frontend_tableros = data.get('tableros')
                if isinstance(frontend_tableros, list) and frontend_tableros:
                    # Sanitizar estructura básica de tableros y piezas
                    tableros_sanitizados = []
                    total_piece_area_mm2 = 0
                    for t in frontend_tableros[:200]:  # límite defensivo
                        piezas_t = []
                        for p in (t.get('piezas') or [])[:2000]:  # límite defensivo
                            try:
                                ancho_p = float(p.get('ancho') or p.get('width') or 0)
                                alto_p = float(p.get('alto') if p.get('alto') is not None else (p.get('largo') if p.get('largo') is not None else p.get('height') or 0))
                                if ancho_p <= 0 or alto_p <= 0:
                                    continue
                                total_piece_area_mm2 += ancho_p * alto_p
                                piezas_t.append({
                                    'nombre': (p.get('nombre') or '').strip(),
                                    'ancho': int(ancho_p),
                                    'largo': int(alto_p),
                                    'x': float(p.get('x') or 0),
                                    'y': float(p.get('y') or 0),
                                    'rotada': bool(p.get('rotada')),
                                    'indiceUnidad': p.get('indiceUnidad'),
                                    'totalUnidades': p.get('totalUnidades'),
                                    'tapacantos': p.get('tapacantos') if isinstance(p.get('tapacantos'), dict) else {'arriba': False, 'derecha': False, 'abajo': False, 'izquierda': False}
                                })
                            except Exception:
                                continue
                        if piezas_t:
                            tableros_sanitizados.append({
                                'numero': t.get('numero') or (len(tableros_sanitizados) + 1),
                                'ancho': float(t.get('ancho') or ancho_tablero),
                                'largo': float(t.get('alto') or t.get('largo') or largo_tablero),
                                'piezas': piezas_t,
                                'eficiencia_tablero': t.get('eficiencia_tablero')  # opcional
                            })
                    # Calcular métricas agregadas si hay tableros válidos
                    if tableros_sanitizados:
                        area_total_mm2 = 0
                        for tb in tableros_sanitizados:
                            area_total_mm2 += tb['ancho'] * tb['largo']
                        area_utilizada_mm2 = total_piece_area_mm2
                        eficiencia = (area_utilizada_mm2 / area_total_mm2 * 100) if area_total_mm2 > 0 else 0
                        resultado = {
                            'tableros': tableros_sanitizados,
                            'area_total': round(area_total_mm2 / 1_000_000, 6),  # m²
                            'area_utilizada': round(area_utilizada_mm2 / 1_000_000, 6),  # m²
                            'eficiencia': round(eficiencia, 4),
                            'margenes': {'margen_x': margen_x, 'margen_y': margen_y},
                            'desperdicio_sierra': desperdicio_sierra,
                            'tablero_ancho_original': ancho_tablero,
                            'tablero_largo_original': largo_tablero,
                            'tiempo_optimizacion': 0,
                            'origen': 'frontend'
                        }
            except Exception:
                resultado = None
            if resultado is None:
                # Ejecutar optimización en backend (fuente de verdad)
                resultado = engine.optimizar_piezas(piezas_procesadas)
                resultado['origen'] = 'backend'
            # Conservar entrada original de piezas para futura rehidratación fiel de la grilla
            try:
                resultado['entrada'] = piezas_procesadas
            except Exception:
                pass
            
            # Agregar información del material
            resultado['material'] = {
                'nombre': material.nombre,
                'codigo': material.codigo,
                'ancho_original': material.ancho,
                'largo_original': material.largo,
                'ancho_usado': ancho_tablero,
                'largo_usado': largo_tablero
            }
            # Metadatos de tapacanto a nivel de material
            resultado['tapacanto'] = {
                'codigo': tapacanto_codigo,
                'nombre': tapacanto_nombre,
            }
            
            # Guardar/Acumular resultado si hay proyecto_id
            if data.get('proyecto_id'):
                proyecto = get_object_or_404(Proyecto, id=data['proyecto_id'])
                existente = {}
                try:
                    if proyecto.resultado_optimizacion:
                        existente = json.loads(proyecto.resultado_optimizacion)
                except Exception:
                    existente = {}

                # Si el frontend indicó reset total, descartar resultado previo
                try:
                    if data.get('resetear_resultado'):
                        existente = {}
                except Exception:
                    pass

                materiales = existente.get('materiales', [])
                material_index = data.get('material_index', 1)

                # Enriquecer resultado con metadatos del material
                resultado['material_index'] = material_index
                resultado['config'] = {
                    'margen_x': margen_x,
                    'margen_y': margen_y,
                    'kerf': desperdicio_sierra,
                }
                # Guardar también el tapacanto de esta pestaña/material
                resultado['tapacanto'] = {
                    'codigo': tapacanto_codigo,
                    'nombre': tapacanto_nombre,
                }

                # Reemplazar si ya existe ese índice, si no, agregar
                reemplazado = False
                for i, m in enumerate(materiales):
                    if m.get('material_index') == material_index:
                        materiales[i] = resultado
                        reemplazado = True
                        break
                if not reemplazado:
                    materiales.append(resultado)

                # Actualizar totales del proyecto
                total_tableros = sum(len(m.get('tableros', [])) for m in materiales)
                total_piezas = sum(sum(len(t.get('piezas', [])) for t in m.get('tableros', [])) for m in materiales)
                eficiencias = [m.get('eficiencia_promedio') or m.get('eficiencia') for m in materiales if m]
                eficiencia_promedio = sum(eficiencias)/len(eficiencias) if eficiencias else 0

                existente['materiales'] = materiales
                existente['total_tableros'] = total_tableros
                existente['total_piezas'] = total_piezas
                existente['eficiencia_promedio'] = eficiencia_promedio

                # Snapshot del historial se agregará luego de asignar el nuevo ID público

                # Persistir resultado y actualizar configuración del proyecto para soportar forzar_optimizacion
                try:
                    # Construir configuración agregada (multi-material) mínima
                    cfg_actual = None
                    # Rehidratar desde lo que exista
                    try:
                        cfg_actual = json.loads(proyecto.configuracion) if proyecto.configuracion else None
                    except Exception:
                        cfg_actual = None
                    # Normalizar a lista de materiales
                    materiales_cfg = []
                    if isinstance(cfg_actual, dict) and isinstance(cfg_actual.get('materiales'), list):
                        materiales_cfg = cfg_actual['materiales']
                    elif isinstance(cfg_actual, dict) and (cfg_actual.get('configuracion_material') or cfg_actual.get('config')):
                        materiales_cfg = [cfg_actual]
                    # Payload de configuración para el material actual
                    mat_cfg_payload = {
                        'configuracion_material': {
                            'material_id': material_id,
                            'ancho_custom': ancho_tablero,
                            'largo_custom': largo_tablero,
                            'margen_x': margen_x,
                            'margen_y': margen_y,
                            'desperdicio_sierra': desperdicio_sierra,
                            'tapacanto_codigo': tapacanto_codigo,
                            'tapacanto_nombre': tapacanto_nombre,
                        },
                        'piezas': piezas_procesadas,
                    }
                    # Insertar/reemplazar por índice de material
                    idx_um = max(0, int(material_index) - 1)
                    while len(materiales_cfg) <= idx_um:
                        materiales_cfg.append({})
                    materiales_cfg[idx_um] = mat_cfg_payload
                    cfg_agg = { 'materiales': materiales_cfg }
                    proyecto.configuracion = json.dumps(cfg_agg, ensure_ascii=False)
                except Exception:
                    pass

                # Incrementar versión y asignar nuevo ID público SOLO si origen backend (recalculo real) y no proviene de layout frontend
                origen_frontend = (resultado.get('origen') == 'frontend')
                try:
                    logger.info(
                        'OPTIMIZAR_MATERIAL llamada: origen=%s proyecto_id=%s version_pre=%s public_id_pre=%s tableros_frontend=%s will_recalc=%s',
                        resultado.get('origen'),
                        data.get('proyecto_id'),
                        getattr(proyecto, 'version', None),
                        getattr(proyecto, 'public_id', None),
                        len(data.get('tableros') or []) if isinstance(data.get('tableros'), list) else 0,
                        'YES' if not origen_frontend else 'NO'
                    )
                except Exception:
                    pass
                if not origen_frontend:
                    try:
                        proyecto.version = (proyecto.version or 0) + 1
                    except Exception:
                        proyecto.version = 1
                    try:
                        ultimo_pub = Proyecto.objects.exclude(public_id__isnull=True).order_by('-public_id').first()
                        next_public_id = (ultimo_pub.public_id + 1) if ultimo_pub and ultimo_pub.public_id and ultimo_pub.public_id >= 100 else 100
                    except Exception:
                        next_public_id = 100
                    proyecto.public_id = next_public_id
                existente['folio_proyecto'] = str(proyecto.public_id)
                # Agregar snapshot al historial con el nuevo ID
                try:
                    snapshot = {
                        'folio': str(proyecto.public_id),
                        'fecha': datetime.now().isoformat(),
                        'materiales': materiales,
                        'total_tableros': total_tableros,
                        'total_piezas': total_piezas,
                        'eficiencia_promedio': eficiencia_promedio,
                    }
                    historial = existente.get('historial') or []
                    historial.append(snapshot)
                    if len(historial) > 20:
                        historial = historial[-20:]
                    existente['historial'] = historial
                    existente['ultimo_folio'] = str(proyecto.public_id)
                except Exception:
                    pass
                proyecto.resultado_optimizacion = json.dumps(existente)
                proyecto.total_materiales = len(materiales)
                proyecto.total_tableros = total_tableros
                proyecto.total_piezas = total_piezas
                proyecto.eficiencia_promedio = eficiencia_promedio
                proyecto.estado = 'optimizado'
                proyecto.save()

                # Registrar ejecución y auditoría
                try:
                    OptimizationRun.objects.create(
                        organizacion=proyecto.organizacion,
                        proyecto=proyecto,
                        run_by=request.user,
                        porcentaje_uso=eficiencia_promedio,
                        tiempo_ms=int(resultado.get('tiempo_optimizacion', 0) * 1000) if resultado.get('tiempo_optimizacion') else None,
                    )
                    AuditLog.objects.create(
                        actor=request.user,
                        organizacion=proyecto.organizacion,
                        verb='RUN_OPT',
                        target_model='Proyecto',
                        target_id=str(proyecto.id),
                        target_repr=proyecto.codigo,
                        changes={'material_id': material_id}
                    )
                except Exception:
                    pass

                # Generar y persistir PDF sólo si la optimización fue realizada en backend (evitar duplicado en origen frontend)
                if resultado.get('origen') != 'frontend':
                    try:
                        from django.conf import settings
                        import os
                        pdf_data = _pdf_from_result(proyecto, existente)
                        folio_actual = str(proyecto.public_id) if proyecto.public_id else f"{proyecto.correlativo}-{proyecto.version}"
                        try:
                            cliente_slug = slugify(proyecto.cliente.nombre) if proyecto.cliente_id else 'cliente'
                        except Exception:
                            cliente_slug = 'cliente'
                        rel_dir = f"proyectos/{proyecto.id}"
                        rel_path = f"{rel_dir}/optimizacion_{folio_actual}_{cliente_slug}.pdf"
                        abs_dir = os.path.join(settings.MEDIA_ROOT, rel_dir)
                        os.makedirs(abs_dir, exist_ok=True)
                        abs_path = os.path.join(settings.MEDIA_ROOT, rel_path)
                        with open(abs_path, 'wb') as fh:
                            fh.write(pdf_data)
                        proyecto.archivo_pdf = rel_path
                        proyecto.save(update_fields=['archivo_pdf'])
                    except Exception:
                        pass
            
            resp = {
                'success': True,
                'resultado': resultado
            }
            try:
                if data.get('proyecto_id'):
                    resp['proyecto_id'] = data.get('proyecto_id')
                    # incluir ID actualizado (usamos clave 'folio' por compatibilidad del frontend)
                    try:
                        resp['folio'] = str(proyecto.public_id) if proyecto.public_id else f"{proyecto.correlativo}-{proyecto.version}"
                    except Exception:
                        pass
            except Exception:
                pass
            return JsonResponse(resp)
            
        except Exception as e:
            import traceback
            print(f"Error en optimización: {str(e)}")
            print(traceback.format_exc())
            return JsonResponse({
                'success': False,
                'message': f'Error en la optimización: {str(e)}'
            })
    
    return JsonResponse({'success': False, 'message': 'Método no permitido'})

@login_required
def obtener_material_info(request, material_id):
    """Obtiene información detallada de un material"""
    try:
        material = get_object_or_404(Material, id=material_id)
        
        return JsonResponse({
            'success': True,
            'material': {
                'id': material.id,
                'nombre': material.nombre,
                'codigo': material.codigo,
                'ancho': material.ancho,
                'largo': material.largo,
                'espesor': material.espesor,
                'tipo': material.tipo,
                'precio': float(material.precio) if material.precio else 0
            }
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'Error al obtener información del material: {str(e)}'
        })

@login_required
def exportar_json_entrada(request, proyecto_id):
    """Exporta la configuración de entrada en formato JSON"""
    try:
        proyecto = get_object_or_404(Proyecto, id=proyecto_id)
        
        if not proyecto.configuracion:
            messages.error(request, 'No hay configuración para exportar')
            return redirect('optimizador_home')
        
        configuracion = json.loads(proyecto.configuracion)
        
        response = HttpResponse(
            json.dumps(configuracion, indent=2, ensure_ascii=False),
            content_type='application/json; charset=utf-8'
        )
        response['Content-Disposition'] = f'attachment; filename="config_{proyecto.nombre}_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json"'
        
        return response
        
    except Exception as e:
        messages.error(request, f'Error al exportar configuración: {str(e)}')
        return redirect('optimizador_home')

@login_required  
def exportar_json_salida(request, proyecto_id):
    """Exporta el resultado de optimización en formato JSON"""
    try:
        proyecto = get_object_or_404(Proyecto, id=proyecto_id)
        
        if not proyecto.resultado_optimizacion:
            # No redirigir al optimizador; devolver mensaje de error simple
            return HttpResponse('No hay resultado de optimización para exportar', status=400, content_type='text/plain; charset=utf-8')
        
        resultado = json.loads(proyecto.resultado_optimizacion)
        
        response = HttpResponse(
            json.dumps(resultado, indent=2, ensure_ascii=False),
            content_type='application/json; charset=utf-8'
        )
        response['Content-Disposition'] = f'attachment; filename="resultado_{proyecto.nombre}_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json"'
        
        return response
        
    except Exception as e:
        messages.error(request, f'Error al exportar resultado: {str(e)}')
        return redirect('optimizador_home')

@login_required
def exportar_pdf(request, proyecto_id):
    """[LEGACY] Generación/regeneración de PDF con layout pesado.
    Marcado como legado: preferir exportar_pdf_snapshot / exportar_pdf_snapshot_cached.
    Puede deshabilitarse estableciendo DISABLE_LEGACY_PDF=1 en variables de entorno.
    """
    import os
    from django.conf import settings
    
    if os.getenv('DISABLE_LEGACY_PDF', '').lower() in ('1','true','yes','y','on'):
        return JsonResponse({'success': False, 'message': 'Ruta legacy PDF deshabilitada. Use snapshot.'}, status=410)
    proyecto = get_object_or_404(Proyecto, id=proyecto_id)

    # Leer flags/opciones de query
    q = request.GET
    def _get_bool(key, default=False):
        v = q.get(key)
        if v is None:
            return default
        return str(v).lower() in ('1','true','yes','y','on')
    def _get_float(key, default=None):
        try:
            if q.get(key) is None:
                return default
            return float(q.get(key))
        except Exception:
            return default

    force_regen = _get_bool('force', False)
    pdf_opts = {
        'fast': _get_bool('fast', True),
        'hatch_spacing': _get_float('hatch_spacing', None),
        'hatch_lw': _get_float('hatch_lw', None),
        'profile': _get_bool('profile', False),
        'kerf_min_lw': _get_float('kerf_min', None),
        'kerf_max_lw': _get_float('kerf_max', None),
        'kerf_scale': _get_float('kerf_scale', None),
    }

    # Priorizar servir el PDF del ID del proyecto si existe (rápido y consistente) salvo force=1
    try:
        folio_actual = str(proyecto.public_id) if proyecto.public_id else f"{proyecto.correlativo}-{proyecto.version}"
    except Exception:
        folio_actual = None

    from django.conf import settings
    import os
    if folio_actual and not force_regen:
        rel_dir = f"proyectos/{proyecto.id}"
        # Primero buscar con cliente en nombre
        try:
            cliente_slug = slugify(proyecto.cliente.nombre) if proyecto.cliente_id else 'cliente'
        except Exception:
            cliente_slug = 'cliente'
        rel_path1 = f"{rel_dir}/optimizacion_{folio_actual}_{cliente_slug}.pdf"
        abs_path1 = os.path.join(settings.MEDIA_ROOT, rel_path1)
        rel_path2 = f"{rel_dir}/optimizacion_{folio_actual}.pdf"
        abs_path2 = os.path.join(settings.MEDIA_ROOT, rel_path2)
        serve_path = None
        serve_name = None
        if os.path.exists(abs_path1):
            serve_path = abs_path1
            serve_name = f"optimizacion_{folio_actual}_{cliente_slug}.pdf"
        elif os.path.exists(abs_path2):
            serve_path = abs_path2
            serve_name = f"optimizacion_{folio_actual}.pdf"
        if serve_path:
            with open(serve_path, 'rb') as f:
                data = f.read()
            resp = HttpResponse(data, content_type='application/pdf')
            resp['Content-Disposition'] = f'inline; filename="{serve_name}"'
            resp['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
            resp['Pragma'] = 'no-cache'
            return resp

    # Si no existe el PDF del folio actual, regenerar rápido desde el resultado guardado
    try:
        resultado = json.loads(proyecto.resultado_optimizacion) if proyecto.resultado_optimizacion else {}
    except Exception:
        resultado = {}
    pdf_bytes = _pdf_from_result(proyecto, resultado, opts=pdf_opts)

    # Guardar como PDF del ID/folio actual (si se pudo obtener)
    rel_dir = f"proyectos/{proyecto.id}"
    if folio_actual:
        try:
            cliente_slug = slugify(proyecto.cliente.nombre) if proyecto.cliente_id else 'cliente'
        except Exception:
            cliente_slug = 'cliente'
        rel_path = f"{rel_dir}/optimizacion_{folio_actual}_{cliente_slug}.pdf"
    else:
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        try:
            cliente_slug = slugify(proyecto.cliente.nombre) if proyecto.cliente_id else 'cliente'
        except Exception:
            cliente_slug = 'cliente'
        rel_path = f"{rel_dir}/optimizacion_{proyecto.codigo}_{cliente_slug}_{ts}.pdf"
    abs_dir = os.path.join(settings.MEDIA_ROOT, rel_dir)
    os.makedirs(abs_dir, exist_ok=True)
    abs_path = os.path.join(settings.MEDIA_ROOT, rel_path)
    with open(abs_path, 'wb') as f:
        f.write(pdf_bytes)
    proyecto.archivo_pdf = rel_path
    proyecto.save(update_fields=['archivo_pdf'])

    resp = HttpResponse(pdf_bytes, content_type='application/pdf')
    resp['Content-Disposition'] = f'inline; filename="{os.path.basename(rel_path)}"'
    resp['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    resp['Pragma'] = 'no-cache'
    return resp

@login_required
@csrf_exempt
def exportar_pdf_snapshot(request, proyecto_id: int):
    """Genera PDF rápido desde snapshot HTML enviado por el frontend (sin recalcular optimización).
    Espera POST con JSON: { materiales: [ { titulo, eficiencia, layout_html, piezas: [...] } ] }
    Guarda caché en MEDIA_ROOT/proyectos/<id>/materiales_snapshot.json y snapshot.html.
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Método no permitido'}, status=405)
    proyecto = get_object_or_404(Proyecto, id=proyecto_id)
    try:
        payload = json.loads(request.body.decode('utf-8') or '{}')
    except Exception:
        return JsonResponse({'success': False, 'message': 'JSON inválido'}, status=400)
    materiales = payload.get('materiales') or payload.get('materiales_json') or []
    if not isinstance(materiales, list) or not materiales:
        return JsonResponse({'success': False, 'message': 'Faltan materiales para generar PDF'}, status=400)
    import re, os
    # Compactar HTML de cada material
    for m in materiales:
        html = m.get('layout_html', '') or ''
        html = re.sub(r'>\s+<', '><', html)
        html = re.sub(r'\s{2,}', ' ', html)
        m['layout_html'] = html
        # Normalizar eficiencia numérica
        try:
            m['eficiencia'] = float(m.get('eficiencia') or 0)
        except Exception:
            m['eficiencia'] = 0.0
        # Asegurar piezas lista
        piezas = m.get('piezas') or []
        if not isinstance(piezas, list):
            m['piezas'] = []
    # Eficiencia global ligera (promedio simple)
    if materiales:
        eficiencia_global = sum(m.get('eficiencia', 0) for m in materiales) / len(materiales)
    else:
        eficiencia_global = 0
    from django.conf import settings
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    context = {
        'proyecto': proyecto,
        'materiales': materiales,
        'eficiencia_global': eficiencia_global,
        'timestamp': timestamp,
    }
    if WEASY_HTML is None:
        return JsonResponse({'success': False, 'message': 'WeasyPrint no disponible en el servidor'}, status=500)
    from django.template.loader import render_to_string
    html_out = render_to_string('pdf/materiales_snapshot.html', context)
    t0 = time.time()
    pdf_bytes = WEASY_HTML(string=html_out).write_pdf()
    t1 = time.time()
    logger.info('Snapshot PDF generado en %.2fs (materiales=%d)', t1 - t0, len(materiales))
    # Guardar caché
    rel_dir = f"proyectos/{proyecto.id}"
    abs_dir = os.path.join(settings.MEDIA_ROOT, rel_dir)
    os.makedirs(abs_dir, exist_ok=True)
    import uuid as _uuid
    # Persistir JSON y HTML para posteriores descargas rápidas
    json_path = os.path.join(abs_dir, 'materiales_snapshot.json')
    html_path = os.path.join(abs_dir, 'snapshot.html')
    try:
        with open(json_path, 'w', encoding='utf-8') as fjson:
            json.dump({'materiales': materiales, 'eficiencia_global': eficiencia_global, 'timestamp': timestamp}, fjson, ensure_ascii=False)
        with open(html_path, 'w', encoding='utf-8') as fhtml:
            fhtml.write(html_out)
    except Exception:
        pass  # Caché opcional
    # Si se solicita solo la portada (primera página), extraerla
    portada_only = request.GET.get('portada_only', '').lower() in ('1', 'true', 'yes')
    if portada_only:
        try:
            from PyPDF2 import PdfReader, PdfWriter
            import io
            reader = PdfReader(io.BytesIO(pdf_bytes))
            if len(reader.pages) > 0:
                writer = PdfWriter()
                writer.add_page(reader.pages[0])
                output_buffer = io.BytesIO()
                writer.write(output_buffer)
                pdf_bytes = output_buffer.getvalue()
        except ImportError:
            logger.warning('PyPDF2 no disponible, enviando PDF completo')
        except Exception as e:
            logger.warning('Error extrayendo primera página: %s', e)
    
    resp = HttpResponse(pdf_bytes, content_type='application/pdf')
    filename = 'portada_optimizacion.pdf' if portada_only else 'snapshot_optimizacion.pdf'
    resp['Content-Disposition'] = f'inline; filename="{filename}"'
    resp['Cache-Control'] = 'no-store'
    return resp

@login_required
def exportar_pdf_snapshot_cached(request, proyecto_id: int):
    """Segunda descarga rápida: reutiliza archivos de caché si existen."""
    proyecto = get_object_or_404(Proyecto, id=proyecto_id)
    portada_only = request.GET.get('portada_only', '').lower() in ('1', 'true', 'yes')
    from django.conf import settings
    import os, json
    rel_dir = f"proyectos/{proyecto.id}"
    abs_dir = os.path.join(settings.MEDIA_ROOT, rel_dir)
    json_path = os.path.join(abs_dir, 'materiales_snapshot.json')
    if not os.path.exists(json_path):
        return JsonResponse({'success': False, 'message': 'No hay snapshot en caché'}, status=404)
    try:
        with open(json_path, 'r', encoding='utf-8') as fjson:
            data = json.load(fjson)
    except Exception:
        return JsonResponse({'success': False, 'message': 'Snapshot corrupto'}, status=500)
    materiales = data.get('materiales') or []
    eficiencia_global = data.get('eficiencia_global', 0)
    timestamp = data.get('timestamp') or datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    if WEASY_HTML is None:
        return JsonResponse({'success': False, 'message': 'WeasyPrint no disponible'}, status=500)
    from django.template.loader import render_to_string
    context = {
        'proyecto': proyecto,
        'materiales': materiales,
        'eficiencia_global': eficiencia_global,
        'timestamp': timestamp,
    }
    html_out = render_to_string('pdf/materiales_snapshot.html', context)
    t0 = time.time()
    pdf_bytes = WEASY_HTML(string=html_out).write_pdf()
    t1 = time.time()
    logger.info('Snapshot PDF (cached) generado en %.2fs (materiales=%d)', t1 - t0, len(materiales))
    
    # Si se solicita solo la portada (primera página), extraerla
    if portada_only:
        try:
            from PyPDF2 import PdfReader, PdfWriter
            import io
            reader = PdfReader(io.BytesIO(pdf_bytes))
            if len(reader.pages) > 0:
                writer = PdfWriter()
                writer.add_page(reader.pages[0])
                output_buffer = io.BytesIO()
                writer.write(output_buffer)
                pdf_bytes = output_buffer.getvalue()
        except ImportError:
            logger.warning('PyPDF2 no disponible, enviando PDF completo')
        except Exception as e:
            logger.warning('Error extrayendo primera página: %s', e)
    
    resp = HttpResponse(pdf_bytes, content_type='application/pdf')
    filename = 'portada_optimizacion_cached.pdf' if portada_only else 'snapshot_optimizacion_cached.pdf'
    resp['Content-Disposition'] = f'inline; filename="{filename}"'
    resp['Cache-Control'] = 'no-store'
    return resp

@login_required
def exportar_pdf_json(request, proyecto_id: int):
    """Genera PDF usando el estilo legacy (ReportLab) pero sin recalcular:
    toma el `Proyecto.resultado_optimizacion` actual y lo dibuja.
    """
    proyecto = get_object_or_404(Proyecto, id=proyecto_id)
    try:
        if not proyecto.resultado_optimizacion:
            return JsonResponse({'success': False, 'message': 'El proyecto no tiene resultado guardado'}, status=400)
        try:
            resultado = json.loads(proyecto.resultado_optimizacion)
        except Exception:
            # Si ya es dict (guardado sin dumps)
            resultado = proyecto.resultado_optimizacion if isinstance(proyecto.resultado_optimizacion, dict) else None
        if not isinstance(resultado, dict):
            return JsonResponse({'success': False, 'message': 'Resultado inválido o corrupto'}, status=500)

        pdf_bytes = _pdf_from_result(
            proyecto,
            resultado,
            opts={'fast': True, 'draw_kerf': False, 'draw_kerf_invisible': False, 'piece_grid': False}
        )
        resp = HttpResponse(pdf_bytes, content_type='application/pdf')
        try:
            folio_txt = str(getattr(proyecto, 'public_id', '') or proyecto.codigo)
        except Exception:
            folio_txt = str(proyecto.id)
        resp['Content-Disposition'] = f'inline; filename="optimizacion_{folio_txt}.pdf"'
        resp['Cache-Control'] = 'no-store'
        return resp
    except Exception as e:
        return JsonResponse({'success': False, 'message': f'Error generando PDF desde JSON: {str(e)}'}, status=500)

 

@login_required
@csrf_exempt
@require_http_methods(["POST"])
def guardar_layout_manual(request):
    """Guarda posiciones/rotaciones manuales de piezas en el resultado del proyecto.
    Espera JSON: { proyecto_id, material_index, updates: [{tablero_num, piezas:[{index,x,y,ancho,largo,rotada}]}] }
    """
    try:
        payload = json.loads(request.body.decode('utf-8') or '{}')
    except Exception:
        return JsonResponse({'success': False, 'message': 'Payload inválido'}, status=400)

    proyecto_id = payload.get('proyecto_id')
    material_index = int(payload.get('material_index') or 1)
    updates = payload.get('updates') or []
    if not proyecto_id:
        return JsonResponse({'success': False, 'message': 'Falta proyecto_id'}, status=400)

    proyecto = get_object_or_404(Proyecto, id=proyecto_id)
    if not proyecto.resultado_optimizacion:
        return JsonResponse({'success': False, 'message': 'Proyecto sin resultado para actualizar'}, status=400)

    try:
        resultado = json.loads(proyecto.resultado_optimizacion)
    except Exception:
        return JsonResponse({'success': False, 'message': 'Resultado inválido en proyecto'}, status=500)

    materiales = resultado.get('materiales') or [resultado]
    # Resolver material (1-based index del UI)
    mat_idx = max(0, material_index - 1)
    if mat_idx >= len(materiales):
        mat_idx = 0
    mat = materiales[mat_idx]

    tableros = mat.get('tableros') or []
    if not isinstance(tableros, list) or not tableros:
        return JsonResponse({'success': False, 'message': 'No hay tableros para actualizar en el material seleccionado'}, status=400)

    # Aplicar updates por tablero
    for upd in updates:
        try:
            tnum = int(upd.get('tablero_num') or 1)
        except Exception:
            tnum = 1
        t_index = max(0, tnum - 1)
        if t_index >= len(tableros):
            continue
        piezas = tableros[t_index].get('piezas') or []
        for pu in (upd.get('piezas') or []):
            try:
                idx = int(pu.get('index') if pu.get('index') is not None else -1)
            except Exception:
                idx = -1
            if idx < 0 or idx >= len(piezas):
                continue
            p = piezas[idx]
            # Actualizar coordenadas y dimensiones (usar claves del esquema backend)
            try:
                x = float(pu.get('x'))
                y = float(pu.get('y'))
                w = float(pu.get('ancho'))
                l = float(pu.get('largo'))
            except Exception:
                continue
            p['x'] = max(0, round(x, 3))
            p['y'] = max(0, round(y, 3))
            p['ancho'] = max(0, round(w, 3))
            # Normalizamos a 'largo'
            p['largo'] = max(0, round(l, 3))
            # Bandera de rotación
            if 'rotada' in pu:
                p['rotada'] = bool(pu.get('rotada'))

    # Persistir cambios
    if 'materiales' in resultado:
        resultado['materiales'][mat_idx] = mat
    else:
        resultado = mat

    proyecto.resultado_optimizacion = json.dumps(resultado, ensure_ascii=False)
    proyecto.save(update_fields=['resultado_optimizacion'])

    return JsonResponse({'success': True, 'resultado': resultado})

@login_required
def proyectos_optimizador(request):
    """Lista de proyectos de optimización"""
    search = request.GET.get('search', '')
    
    proyectos = Proyecto.objects.filter(usuario=request.user)
    
    if search:
        proyectos = proyectos.filter(
            Q(nombre__icontains=search) |
            Q(descripcion__icontains=search)
        )
    
    proyectos = proyectos.order_by('-fecha_creacion')
    
    paginator = Paginator(proyectos, 20)
    page_number = request.GET.get('page')
    proyectos_page = paginator.get_page(page_number)
    
    context = {
        'proyectos': proyectos_page,
        'search': search,
    }
    return render(request, 'optimizador/proyectos.html', context)


@login_required
@require_http_methods(["POST"])
def forzar_optimizacion(request, proyecto_id:int):
    """Genera y persiste el resultado de optimización desde la configuración del proyecto.
    Útil cuando el proyecto no tiene resultado guardado aún y se quiere exportar PDF o previsualizar.
    """
    proyecto = get_object_or_404(Proyecto, id=proyecto_id)
    # Si ya tiene resultado válido, no recalcular
    try:
        if proyecto.resultado_optimizacion:
            existente = json.loads(proyecto.resultado_optimizacion)
            mats = existente.get('materiales') or [existente]
            if any(len(m.get('tableros') or []) for m in mats):
                return JsonResponse({'success': True, 'message': 'El proyecto ya cuenta con un resultado de optimización.'})
    except Exception:
        pass

    # Intentar construir desde configuración (soporta 1 o varios materiales)
    try:
        if not proyecto.configuracion:
            return JsonResponse({'success': False, 'message': 'El proyecto no tiene configuración guardada para optimizar.'}, status=400)
        cfg = json.loads(proyecto.configuracion) if isinstance(proyecto.configuracion, str) else proyecto.configuracion

        def optimizar_desde(conf_mat, piezas_in):
            material_id = (conf_mat or {}).get('material_id')
            if not (conf_mat and piezas_in and material_id):
                return None
            material = get_object_or_404(Material, id=material_id)
            ancho_tablero = conf_mat.get('ancho_custom') or material.ancho
            largo_tablero = conf_mat.get('largo_custom') or material.largo
            margen_x = conf_mat.get('margen_x', 0)
            margen_y = conf_mat.get('margen_y', 0)
            desperdicio_sierra = conf_mat.get('desperdicio_sierra', 3)
            tapacanto_codigo = conf_mat.get('tapacanto_codigo', '')
            tapacanto_nombre = conf_mat.get('tapacanto_nombre', '')
            engine = OptimizationEngine(ancho_tablero, largo_tablero, margen_x, margen_y, desperdicio_sierra)
            piezas_proc = []
            for p in piezas_in:
                piezas_proc.append({
                    'nombre': p['nombre'],
                    'ancho': p['ancho'],
                    'largo': p['largo'],
                    'cantidad': p.get('cantidad', 1),
                    'veta_libre': p.get('veta_libre', False),
                    'tapacantos': p.get('tapacantos', {}) or {}
                })
            r = engine.optimizar_piezas(piezas_proc)
            r['entrada'] = piezas_proc
            r['material'] = {
                'nombre': material.nombre,
                'codigo': material.codigo,
                'ancho_original': material.ancho,
                'largo_original': material.largo,
                'ancho_usado': ancho_tablero,
                'largo_usado': largo_tablero
            }
            r['config'] = {'margen_x': margen_x, 'margen_y': margen_y, 'kerf': desperdicio_sierra}
            r['tapacanto'] = { 'codigo': tapacanto_codigo, 'nombre': tapacanto_nombre }
            return r

        materiales = []
        if isinstance(cfg, dict) and isinstance(cfg.get('materiales'), list):
            for mcfg in cfg['materiales']:
                conf_mat = mcfg.get('configuracion_material') or mcfg.get('config')
                piezas_in = mcfg.get('piezas') or mcfg.get('entrada')
                r = optimizar_desde(conf_mat, piezas_in)
                if r: materiales.append(r)
        else:
            conf_mat = cfg.get('configuracion_material') or cfg.get('config')
            piezas_in = cfg.get('piezas') or cfg.get('entrada')
            r = optimizar_desde(conf_mat, piezas_in)
            if r: materiales.append(r)

        if not materiales:
            return JsonResponse({'success': False, 'message': 'No hay configuración suficiente (material y piezas) para optimizar.'}, status=400)

        total_tableros = sum(len(m.get('tableros', [])) for m in materiales)
        total_piezas = sum(sum(len(t.get('piezas', [])) for t in m.get('tableros', [])) for m in materiales)
        eficiencias = [m.get('eficiencia') or m.get('eficiencia_promedio') for m in materiales if m]
        eficiencia_promedio = sum(e for e in eficiencias if e) / max(1, len([e for e in eficiencias if e]))
        folio = f"OPT-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        resultado_persist = {
            'materiales': materiales,
            'total_tableros': total_tableros,
            'total_piezas': total_piezas,
            'eficiencia_promedio': eficiencia_promedio,
            'ultimo_folio': folio,
            'historial': [{
                'folio': folio,
                'fecha': datetime.now().isoformat(),
                'materiales': materiales,
                'total_tableros': total_tableros,
                'total_piezas': total_piezas,
                'eficiencia_promedio': eficiencia_promedio,
            }]
        }
        proyecto.resultado_optimizacion = json.dumps(resultado_persist, ensure_ascii=False)
        proyecto.total_materiales = len(materiales)
        proyecto.total_tableros = total_tableros
        proyecto.total_piezas = total_piezas
        proyecto.eficiencia_promedio = eficiencia_promedio
        proyecto.estado = 'optimizado'
        proyecto.save()

        return JsonResponse({'success': True, 'message': 'Optimización generada y guardada', 'resumen': {
            'materiales': len(materiales), 'tableros': total_tableros, 'piezas': total_piezas, 'eficiencia': eficiencia_promedio, 'folio': folio
        }})

    except Exception as e:
        return JsonResponse({'success': False, 'message': f'Error al optimizar: {str(e)}'}, status=500)

def js_test(request):
    """Vista de prueba para JavaScript"""
    return render(request, 'optimizador/test.html')

def optimizador_clean(request):
    """Vista limpia del optimizador sin complejidades"""
    return render(request, 'optimizador/home-clean.html')

# ====================================================
# ENDPOINTS PARA BÚSQUEDA Y GESTIÓN DE CLIENTES
# ====================================================

@csrf_exempt
def buscar_clientes_ajax(request):
    """Búsqueda en tiempo real de clientes"""
    if request.method == 'GET':
        query = request.GET.get('q', '').strip()
        
        if len(query) < 2:
            return JsonResponse({'clientes': []})
        
        # Buscar clientes por nombre o RUT
        clientes = Cliente.objects.filter(
            activo=True
        ).filter(
            Q(nombre__icontains=query) | Q(rut__icontains=query) | Q(organizacion__nombre__icontains=query)
        ).select_related('organizacion').order_by('nombre')[:10]
        
        resultados = []
        for cliente in clientes:
            resultados.append({
                'id': cliente.id,
                'nombre': cliente.nombre,
                'rut': cliente.rut,
                'organizacion': cliente.organizacion.nombre if cliente.organizacion else '',
                'telefono': cliente.telefono or '',
                'email': cliente.email or ''
            })
        
        return JsonResponse({
            'clientes': resultados,
            'total': len(resultados),
            'query': query
        })
    
    return JsonResponse({'error': 'Método no permitido'}, status=405)

@csrf_exempt
def crear_cliente_ajax(request):
    """Crear nuevo cliente desde el optimizador"""
    if request.method == 'POST':
        try:
            # Manejar tanto JSON como FormData
            if request.content_type == 'application/json':
                data = json.loads(request.body)
            else:
                data = request.POST
            
            # Validar datos requeridos
            nombre = data.get('nombre', '').strip()
            rut = _normalize_rut(data.get('rut', '') or '')
            
            if not nombre:
                return JsonResponse({'success': False, 'mensaje': 'El nombre es requerido'})
            
            # Si no hay RUT, generar uno temporal basado en el nombre (normalizado)
            if not rut:
                import time
                rut_temporal = f"TEMP-{int(time.time())}"
                rut = _normalize_rut(rut_temporal)

            # Asignar organización del usuario que crea el cliente
            org = None
            try:
                # Intentamos tomar la organización desde el perfil del usuario, si existe
                if hasattr(request.user, 'usuarioperfiloptimizador') and request.user.usuarioperfiloptimizador.organizacion:
                    org = request.user.usuarioperfiloptimizador.organizacion
                elif hasattr(request.user, 'usuario_perfil_optimizador') and request.user.usuario_perfil_optimizador.organizacion:
                    org = request.user.usuario_perfil_optimizador.organizacion
            except Exception:
                org = None

            # Verificar si el RUT ya existe en la misma organización (comparación normalizada)
            if rut:
                if org:
                    exists = Cliente.objects.filter(rut=rut, organizacion=org).exists()
                else:
                    exists = Cliente.objects.filter(rut=rut, organizacion__isnull=True).exists()
                if exists:
                    return JsonResponse({'success': False, 'mensaje': 'Ya existe un cliente con este RUT en esta organización'})

            # Crear nuevo cliente con campos válidos del modelo actual
            cliente = Cliente.objects.create(
                nombre=nombre,
                rut=rut,
                organizacion=org,
                telefono=data.get('telefono', '') or None,
                email=data.get('email', '') or None,
                direccion=data.get('direccion', '') or None,
                activo=True
            )
            # Auditoría: registrar creación de cliente
            try:
                from core.models import AuditLog
                AuditLog.objects.create(
                    actor=request.user if getattr(request, 'user', None) and request.user.is_authenticated else None,
                    organizacion=org,
                    verb='CREATE',
                    target_model='Cliente',
                    target_id=str(cliente.id),
                    target_repr=cliente.nombre,
                    changes=None
                )
            except Exception:
                pass
            
            return JsonResponse({
                'success': True,
                'cliente': {
                    'id': cliente.id,
                    'nombre': cliente.nombre,
                    'rut': cliente.rut,
                    'organizacion': (cliente.organizacion.nombre if getattr(cliente, 'organizacion', None) else ''),
                    'telefono': cliente.telefono or '',
                    'email': cliente.email or ''
                },
                'message': f'Cliente {cliente.nombre} creado exitosamente'
            })
            
        except json.JSONDecodeError:
            return JsonResponse({'success': False, 'mensaje': 'Datos JSON inválidos'})
        except Exception as e:
            return JsonResponse({'success': False, 'mensaje': f'Error interno: {str(e)}'})
    
    return JsonResponse({'success': False, 'mensaje': 'Método no permitido'})