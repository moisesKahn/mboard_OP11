import json
from datetime import datetime
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse, HttpResponse
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
from django.utils.text import slugify

# Reutilizamos modelos y utilidades del proyecto
from core.models import Proyecto, Cliente, Material, Tapacanto, OptimizationRun, AuditLog
from core.auth_utils import get_auth_context

# Importar funciones del optimizador original para reutilizarlas
from WowDash.optimizer_views import OptimizationEngine, _pdf_from_result, _normalize_rut

@login_required
def optimizador_autoservicio_home_clone(request):
    """Clon del optimizador específico para autoservicio.
    Usa el mismo template pero con el flag autoservicio=True para mostrar la interfaz personalizada.
    """
    # Verificar que el usuario sea autoservicio
    perfil = getattr(request.user, 'usuarioperfiloptimizador', None)
    if not (perfil and perfil.rol == 'autoservicio'):
        return redirect('/')
    
    from WowDash.autoservicio_views import SESSION_KEY_CLIENTE
    
    # Obtener cliente de la sesión (si existe)
    cliente_id = request.session.get(SESSION_KEY_CLIENTE)
    cliente = None
    if cliente_id:
        cliente = Cliente.objects.filter(id=cliente_id).first()
        if not cliente:
            # Cliente de sesión ya no existe, limpiar
            request.session.pop(SESSION_KEY_CLIENTE, None)
            cliente_id = None
    
    # Preparar contexto similar al optimizador original pero con flag autoservicio
    ctx = get_auth_context(request)
    
    # Verificar si hay un proyecto a copiar en sesión
    proyecto_copiado_id = request.session.pop('autoservicio_proyecto_copiado', None)
    proyecto_a_cargar = None
    modo_copia = False
    
    if proyecto_copiado_id:
        try:
            proyecto_a_cargar = Proyecto.objects.select_related('cliente').get(id=proyecto_copiado_id)
            modo_copia = True  # Indicar que es una copia, no el original
            print(f"DEBUG: Cargando proyecto original ID={proyecto_copiado_id} en MODO COPIA")
            print(f"  - Nombre: {proyecto_a_cargar.nombre}")
            print(f"  - Cliente: {proyecto_a_cargar.cliente.nombre if proyecto_a_cargar.cliente else 'Sin cliente'}")
            print(f"  - Tiene configuracion: {bool(proyecto_a_cargar.configuracion)}")
            print(f"  - Tiene resultado_optimizacion: {bool(proyecto_a_cargar.resultado_optimizacion)}")
            
            # Actualizar el cliente en sesión si el proyecto tiene uno diferente
            if proyecto_a_cargar.cliente and proyecto_a_cargar.cliente.id != cliente_id:
                request.session[SESSION_KEY_CLIENTE] = proyecto_a_cargar.cliente.id
                cliente = proyecto_a_cargar.cliente
                print(f"  - Cliente actualizado en sesión: {cliente.nombre}")
        except Proyecto.DoesNotExist:
            print(f"ERROR: Proyecto {proyecto_copiado_id} no existe")
            proyecto_a_cargar = None
    
    # Obtener materiales y tapacantos
    materiales_qs = Material.objects.all()
    tapacantos_qs = Tapacanto.objects.all()
    
    if not (ctx.get('organization_is_general') or ctx.get('is_support')):
        if hasattr(Material, 'organizacion'):
            materiales_qs = materiales_qs.filter(organizacion_id=ctx.get('organization_id'))
        if hasattr(Tapacanto, 'organizacion'):
            tapacantos_qs = tapacantos_qs.filter(organizacion_id=ctx.get('organization_id'))
    
    # Fallback si los filtros devolvieron vacío
    mats_list = list(materiales_qs[:50])
    if not mats_list:
        mats_list = list(Material.objects.all()[:50])
    
    taps_list = list(tapacantos_qs[:50])
    if not taps_list:
        taps_list = list(Tapacanto.objects.all()[:50])
    
    context = {
        'title': 'Optimizador Autoservicio',
        'subTitle': f'Copiando: {proyecto_a_cargar.nombre}' if proyecto_a_cargar else 'Proyecto Nuevo',
        'cliente_autoservicio': cliente,
        'autoservicio': True,  # FLAG CRÍTICO para mostrar interfaz personalizada
        'tableros': mats_list,
        'tapacantos': taps_list,
        'proyecto_precargado': proyecto_a_cargar,  # Cargar datos del proyecto original
        'modo_copia': modo_copia,  # Indicar que se está copiando, no editando
    }
    
    return render(request, 'optimizador/home.html', context)

@login_required
@csrf_exempt
def crear_proyecto_optimizacion_clone(request):
    """Clon que usa la función original"""
    from WowDash.optimizer_views import crear_proyecto_optimizacion
    return crear_proyecto_optimizacion(request)

@login_required
@csrf_exempt
def optimizar_material_clone(request):
    """Ejecuta la optimizaci\u00f3n (versi\u00f3n clon - reutiliza motor original)"""
    # Importar la funci\u00f3n original y reutilizarla
    from WowDash.optimizer_views import optimizar_material
    return optimizar_material(request)

@login_required
def exportar_json_entrada_clone(request, proyecto_id):
    """Exporta JSON de entrada (versi\u00f3n clon)"""
    from WowDash.optimizer_views import exportar_json_entrada
    return exportar_json_entrada(request, proyecto_id)

@login_required
def exportar_json_salida_clone(request, proyecto_id):
    """Exporta JSON de salida (versi\u00f3n clon)"""
    from WowDash.optimizer_views import exportar_json_salida
    return exportar_json_salida(request, proyecto_id)

@login_required
def exportar_pdf_clone(request, proyecto_id):
    """Exporta PDF (versi\u00f3n clon)"""
    from WowDash.optimizer_views import exportar_pdf
    return exportar_pdf(request, proyecto_id)
