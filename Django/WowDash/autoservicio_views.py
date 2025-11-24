from django.shortcuts import render, redirect
from django.urls import reverse
from django.http import JsonResponse, HttpResponse
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_GET, require_POST
from django.views.decorators.csrf import ensure_csrf_cookie
from django.utils import timezone
from core.models import Cliente, Organizacion, UsuarioPerfilOptimizador
from core.models import Proyecto

SESSION_KEY_CLIENTE = 'autoservicio_cliente_id'
SESSION_KEY_TS = 'autoservicio_cliente_ts'
INACTIVIDAD_MINUTOS = 3

def _perfil(request):
    try:
        return request.user.usuarioperfiloptimizador
    except Exception:
        return None

def _es_autoservicio(request):
    p = _perfil(request)
    return bool(p and p.rol == 'autoservicio')

def _org(request):
    p = _perfil(request)
    return getattr(p, 'organizacion', None)

def _check_inactividad(request):
    ts = request.session.get(SESSION_KEY_TS)
    if ts:
        try:
            dt = timezone.datetime.fromisoformat(ts)
        except Exception:
            dt = None
        if dt and timezone.now() - dt > timezone.timedelta(minutes=INACTIVIDAD_MINUTOS):
            for k in (SESSION_KEY_CLIENTE, SESSION_KEY_TS):
                request.session.pop(k, None)

def _touch(request):
    request.session[SESSION_KEY_TS] = timezone.now().isoformat()

@login_required
@ensure_csrf_cookie  # Garantiza cookie CSRF para llamadas fetch POST (crear-cliente)
def autoservicio_landing(request):
    if not _es_autoservicio(request):
        return redirect('/')
    _check_inactividad(request)
    # Debug: verificar si es autoservicio
    perfil = _perfil(request)
    print(f"DEBUG autoservicio_landing: usuario={request.user.username}, rol={getattr(perfil, 'rol', None)}, es_autoservicio={_es_autoservicio(request)}")
    # Solo redirigir cuando venga con parámetro continue=1 (del botón Continuar)
    if request.GET.get('continue') == '1':
        print(f"DEBUG: Redirigiendo a optimizador_autoservicio_home_clone por botón continuar")
        return redirect('optimizador_autoservicio_home_clone')
    # Modo stay: mostrar página por compatibilidad/diagnóstico
    cliente_id = request.session.get(SESSION_KEY_CLIENTE)
    cliente = None
    if cliente_id:
        cliente = Cliente.objects.filter(id=cliente_id).first()
    return render(request, 'autoservicio/landing.html', {
        'cliente': cliente,
        'inactividad_min': INACTIVIDAD_MINUTOS,
    })

@login_required
def autoservicio_hub(request):
    if not _es_autoservicio(request):
        return redirect('/')
    _check_inactividad(request)
    cliente_id = request.session.get(SESSION_KEY_CLIENTE)
    if not cliente_id:
        return redirect('/autoservicio/')
    cliente = Cliente.objects.filter(id=cliente_id).first()
    if not cliente:
        request.session.pop(SESSION_KEY_CLIENTE, None)
        return redirect('/autoservicio/')
    _touch(request)
    # Nuevo: redirigir directamente al clon del optimizador tras tener cliente en sesión
    return redirect('optimizador_autoservicio_home_clone')

@login_required
def autoservicio_mis_proyectos(request):
    """Listado de proyectos filtrados por cliente en sesión para autoservicio."""
    if not _es_autoservicio(request):
        return redirect('/')
    _check_inactividad(request)
    cliente_id = request.session.get(SESSION_KEY_CLIENTE)
    if not cliente_id:
        return redirect('/autoservicio/')
    cliente = Cliente.objects.filter(id=cliente_id).first()
    if not cliente:
        request.session.pop(SESSION_KEY_CLIENTE, None)
        return redirect('/autoservicio/')
    _touch(request)
    proyectos = Proyecto.objects.filter(cliente_id=cliente_id).order_by('-fecha_creacion')[:50]
    return render(request, 'autoservicio/mis_proyectos.html', {
        'cliente': cliente,
        'proyectos': proyectos,
    })

@login_required
def autoservicio_finalizar_proyecto(request, proyecto_id:int):
    """Marca un proyecto como completado (estado 'completado') asegurando pertenencia al cliente en sesión.
    Si no tiene resultado_optimizacion aún, se bloquea la finalización.
    """
    if not _es_autoservicio(request):
        return JsonResponse({'success': False, 'message': 'forbidden'}, status=403)
    _check_inactividad(request)
    from django.shortcuts import get_object_or_404
    proyecto = get_object_or_404(Proyecto, id=proyecto_id)
    cliente_id = request.session.get(SESSION_KEY_CLIENTE)
    if not cliente_id or proyecto.cliente_id != cliente_id:
        return JsonResponse({'success': False, 'message': 'proyecto no corresponde al cliente actual'}, status=403)
    if not proyecto.resultado_optimizacion:
        return JsonResponse({'success': False, 'message': 'Debe generar la optimización antes de finalizar.'}, status=400)
    if proyecto.estado == 'completado':
        return JsonResponse({'success': True, 'message': 'Proyecto ya estaba finalizado.'})
    proyecto.estado = 'completado'
    proyecto.save(update_fields=['estado', 'fecha_modificacion'])
    return JsonResponse({'success': True, 'message': 'Proyecto finalizado correctamente.'})

@login_required
@require_GET
def autoservicio_buscar_rut(request):
    if not _es_autoservicio(request):
        return JsonResponse({'error': 'forbidden'}, status=403)
    rut = request.GET.get('rut', '').strip()
    if not rut:
        return JsonResponse({'found': False, 'rut': rut})
    org = _org(request)
    qs = Cliente.objects.filter(rut__iexact=rut)
    if org and not org.is_general:
        qs = qs.filter(organizacion=org)
    cliente = qs.first()
    if cliente:
        request.session[SESSION_KEY_CLIENTE] = cliente.id
        _touch(request)
        return JsonResponse({'found': True, 'cliente': {
            'id': cliente.id,
            'rut': cliente.rut,
            'nombre': cliente.nombre,
            'email': cliente.email,
            'telefono': cliente.telefono,
        }, 'redirect_clone': reverse('optimizador_autoservicio_home_clone')})
    return JsonResponse({'found': False, 'rut': rut})

@login_required
@require_POST
def autoservicio_crear_cliente(request):
    if not _es_autoservicio(request):
        return JsonResponse({'error': 'forbidden'}, status=403)
    rut = request.POST.get('rut', '').strip()
    nombre = request.POST.get('nombre', '').strip()
    email = request.POST.get('email', '').strip()
    telefono = request.POST.get('telefono', '').strip()
    direccion = request.POST.get('direccion', '').strip()
    if not rut or not nombre:
        return JsonResponse({'error': 'RUT y Nombre son requeridos'}, status=400)
    org = _org(request)
    # Ver si ya existe
    qs = Cliente.objects.filter(rut__iexact=rut)
    if org and not org.is_general:
        qs = qs.filter(organizacion=org)
    existente = qs.first()
    if existente:
        return JsonResponse({'error': 'Cliente ya existe', 'cliente_id': existente.id}, status=409)
    cliente = Cliente.objects.create(
        rut=rut,
        nombre=nombre,
        email=email or None,
        telefono=telefono or None,
        direccion=direccion or None,
        organizacion=org,
        created_by=request.user
    )
    request.session[SESSION_KEY_CLIENTE] = cliente.id
    _touch(request)
    return JsonResponse({'created': True, 'cliente': {
        'id': cliente.id,
        'rut': cliente.rut,
        'nombre': cliente.nombre,
        'email': cliente.email,
        'telefono': cliente.telefono,
    }, 'redirect_clone': reverse('optimizador_autoservicio_home_clone')})

@login_required
def autoservicio_logout_cliente(request):
    if _es_autoservicio(request):
        for k in (SESSION_KEY_CLIENTE, SESSION_KEY_TS):
            request.session.pop(k, None)
    return redirect('/autoservicio/')