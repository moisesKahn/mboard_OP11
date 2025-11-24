from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden, JsonResponse, HttpResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.csrf import csrf_exempt
from django.db.models import Q
from core.models import Material, Tapacanto, Proyecto
from WowDash.material_views import get_user_organization
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib import colors
from reportlab.lib.units import mm
import json
from django.utils import timezone


@login_required
def configurador_3d(request):
    """Vista del Configurador 3D. Accesible para superusuarios/administradores de organización y autoservicio."""
    allowed = False
    es_autoservicio = False
    try:
        perfil = getattr(request.user, 'usuarioperfiloptimizador', None)
        rol = getattr(perfil, 'rol', None)
        allowed = request.user.is_superuser or rol in ('super_admin', 'org_admin', 'autoservicio')
        es_autoservicio = rol == 'autoservicio'
    except Exception:
        allowed = request.user.is_superuser
    if not allowed:
        return render(request, "403.html", status=403)
    
    # Pasar flag autoservicio al template para modificar redirección del botón
    context = {
        'es_autoservicio': es_autoservicio
    }
    return render(request, "tools/configurador_3d.html", context)


@login_required
def materiales_json(request):
    """Devuelve materiales activos filtrados por organización del usuario (o todos si es super admin)."""
    # Superusers: acceso a todos
    if request.user.is_superuser:
        org, err = (None, None)
    else:
        org, err = get_user_organization(request)
    if err:
        return JsonResponse({'success': False, 'message': 'Organización inválida'}, status=400)
    qs = Material.objects.filter(activo=True)
    if org is not None:
        qs = qs.filter(organizacion=org)
    # Colores sugeridos por tipo
    tipo_color = {
        'melamina': '#d7ccc8', 'mdf': '#bdbdbd', 'osb': '#ffecb3',
        'terciado': '#ffe0b2', 'aglomerado': '#c8e6c9', 'otro': '#e0e0e0'
    }
    data = [
        {
            'id': m.id,
            'codigo': m.codigo,
            'nombre': m.nombre,
            'tipo': m.tipo,
            'espesor': float(m.espesor),
            'ancho': m.ancho,
            'largo': m.largo,
            'color': tipo_color.get(m.tipo, '#e0e0e0'),
        }
        for m in qs.order_by('nombre')
    ]
    return JsonResponse({'success': True, 'materiales': data})


@login_required
def tapacantos_json(request):
    """Devuelve tapacantos activos filtrados por organización del usuario (o todos si es super admin)."""
    # Superusers: acceso a todos
    if request.user.is_superuser:
        org, err = (None, None)
    else:
        org, err = get_user_organization(request)
    if err:
        return JsonResponse({'success': False, 'message': 'Organización inválida'}, status=400)
    qs = Tapacanto.objects.filter(activo=True)
    if org is not None:
        qs = qs.filter(organizacion=org)
    data = [
        {
            'id': t.id,
            'codigo': t.codigo,
            'nombre': t.nombre,
            'color': t.color,
            'ancho': float(t.ancho),
            'espesor': float(t.espesor),
            'precio_metro': float(t.precio_metro),
        }
        for t in qs.order_by('nombre')
    ]
    return JsonResponse({'success': True, 'tapacantos': data})


@login_required
def configurador_pdf(request, proyecto_id: int):
    """Genera un PDF simple del proyecto del configurador 3D usando la lista de cortes en `proyecto.configuracion`."""
    proyecto = get_object_or_404(Proyecto, pk=proyecto_id)
    if proyecto.usuario != request.user and not request.user.is_superuser:
        return HttpResponseForbidden("No autorizado")

    # Configuración guardada puede venir como JSON string
    cfg_raw = proyecto.configuracion or {}
    try:
        cfg = json.loads(cfg_raw) if isinstance(cfg_raw, str) else (cfg_raw or {})
    except Exception:
        cfg = {}
    cut_list = cfg.get('cut_list') or []
    material = cfg.get('material') or {}
    tapacanto = cfg.get('tapacanto') or {}
    modulo = cfg.get('modulo') or {}

    # Crear PDF
    from io import BytesIO
    buffer = BytesIO()
    p = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    # Encabezado
    p.setFont("Helvetica-Bold", 14)
    p.drawString(40, height - 40, "Proyecto - Configurador 3D")
    p.setFont("Helvetica", 10)
    y = height - 60
    p.drawString(40, y, f"Proyecto: {proyecto.nombre}  |  Código: {proyecto.codigo}  |  Folio: {proyecto.public_id or ''}")
    y -= 16
    p.drawString(40, y, f"Cliente: {getattr(proyecto.cliente, 'nombre', '')}  |  Organización: {getattr(proyecto.organizacion, 'nombre', '')}")
    y -= 16
    p.drawString(40, y, f"Módulo: {modulo.get('name','')}  |  Material: {material.get('nombre','')} ({material.get('espesor','')}mm)")
    y -= 10
    p.line(40, y, width - 40, y)
    y -= 20

    # Tabla lista de cortes
    p.setFont("Helvetica-Bold", 11)
    p.drawString(40, y, "Lista de Corte")
    y -= 16
    p.setFont("Helvetica-Bold", 9)
    p.drawString(40, y, "Pieza")
    p.drawString(200, y, "Cant.")
    p.drawString(240, y, "Ancho")
    p.drawString(300, y, "Alto")
    p.drawString(360, y, "Tapacanto (A/D/B/I)")
    y -= 12
    p.setFont("Helvetica", 9)

    def draw_row(nombre, cant, ancho, alto, taps_txt):
        nonlocal y
        if y < 60:
            p.showPage()
            y = height - 60
        p.drawString(40, y, nombre)
        p.drawString(200, y, str(cant))
        p.drawString(240, y, f"{int(ancho)}")
        p.drawString(300, y, f"{int(alto)}")
        p.drawString(360, y, taps_txt)
        y -= 12

    def taps_to_txt(taps):
        # taps: dict con keys arriba, derecha, abajo, izquierda (bool)
        if not isinstance(taps, dict):
            return '—'
        def b(v):
            return '1' if v else '0'
        return f"{b(taps.get('arriba'))}/{b(taps.get('derecha'))}/{b(taps.get('abajo'))}/{b(taps.get('izquierda'))}"

    for item in cut_list:
        draw_row(
            item.get('nombre', 'Pieza'),
            item.get('cantidad', 1),
            item.get('ancho', 0),
            item.get('alto', 0),
            taps_to_txt(item.get('tapacantos') or {})
        )

    p.showPage()
    p.save()
    pdf = buffer.getvalue()
    buffer.close()
    resp = HttpResponse(pdf, content_type='application/pdf')
    resp['Content-Disposition'] = f"inline; filename=proyecto_{proyecto.public_id or proyecto.id}.pdf"
    return resp


@login_required
@csrf_exempt
def configurador_autosave(request):
    """Guarda (o actualiza) la configuración del proyecto del Configurador 3D.
    Espera JSON: { proyecto_id, configuracion, nombre? }
    Devuelve: { success, proyecto_id, folio }
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Método no permitido'}, status=405)
    try:
        payload = json.loads(request.body or '{}')
        proyecto_id = payload.get('proyecto_id')
        if not proyecto_id:
            return JsonResponse({'success': False, 'message': 'proyecto_id es requerido'}, status=400)

        proyecto = get_object_or_404(Proyecto, pk=proyecto_id)
        # Permisos: dueño del proyecto o superusuario
        if proyecto.usuario_id and proyecto.usuario_id != request.user.id and not request.user.is_superuser:
            return JsonResponse({'success': False, 'message': 'No autorizado'}, status=403)

        # Actualizar nombre si llega
        nombre = payload.get('nombre')
        if isinstance(nombre, str) and nombre.strip():
            proyecto.nombre = nombre.strip()

        # Guardar configuración completa tal como viene (dict/list)
        cfg = payload.get('configuracion')
        if isinstance(cfg, (dict, list)):
            try:
                proyecto.configuracion = json.dumps(cfg, ensure_ascii=False)
            except Exception:
                proyecto.configuracion = cfg

        # Mantener estado en borrador si aún no está optimizado
        if not proyecto.estado or proyecto.estado == 'borrador':
            proyecto.estado = 'borrador'

        # No tocamos public_id aquí (solo al optimizar o al crear)
        proyecto.save()
        return JsonResponse({'success': True, 'proyecto_id': proyecto.id, 'folio': str(proyecto.public_id or '')})
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=500)
