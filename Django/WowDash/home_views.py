from django.shortcuts import render
from django.http import HttpResponse
from django.contrib.auth.decorators import login_required
from core.auth_utils import get_auth_context
from django.contrib.auth.models import User
from core.models import UsuarioPerfilOptimizador, Proyecto, Organizacion

def blankpage(request):
    context={
        "title": "Blank Page",
        "subTitle": "Blank Page",
    }
    return render(request,"blankpage.html", context)
    
def calendar(request):
    context={
        "title": "Calendar",
        "subTitle": "Components / Calendar",
    }
    return render(request,"calendar.html", context)
    
def chat(request):
    context={
        "title": "Chat",
        "subTitle": "Chat",
    }
    return render(request,"chat.html", context)
    
def chatProfile(request):
    context={
        "title": "Chat",
        "subTitle": "Chat",
    }
    return render(request,"chatProfile.html", context)
    
def comingsoon(request):
    context={
        "title": "",
        "subTitle": "",
    }
    return render(request,"comingsoon.html", context)
    
def email(request):
    context={
        "title": "Email",
        "subTitle": "Components / Email",
    }
    return render(request,"email.html", context)
    
def faqs(request):
    context={
        "title": "Preguntas frecuentes",
        "subTitle": "Ayuda / Preguntas frecuentes",
    }
    return render(request,"faqs.html", context)
    
def gallery(request):
    context={
        "title": "Gallery",
        "subTitle": "Gallery",
    }
    return render(request,"gallery.html", context)
    
@login_required
def index(request):
    ctx = get_auth_context(request)
    perfil = None
    try:
        perfil = request.user.usuarioperfiloptimizador
    except UsuarioPerfilOptimizador.DoesNotExist:
        perfil = None

    # Si es usuario de autoservicio, redirigir directamente al optimizador de autoservicio
    if perfil and perfil.rol == 'autoservicio':
        from django.shortcuts import redirect
        return redirect('optimizador_autoservicio_home_clone')

    # Métricas básicas: limitar por organización si aplica
    org = None
    if ctx.get('organization_id') and not ctx.get('organization_is_general') and not ctx.get('is_support'):
        try:
            org = Organizacion.objects.get(id=ctx['organization_id'])
        except Organizacion.DoesNotExist:
            org = None

    # Usuarios activos
    users_qs = User.objects.filter(is_active=True)
    if org:
        users_qs = users_qs.filter(usuarioperfiloptimizador__organizacion_id=org.id)
    total_usuarios = users_qs.count()

    # Proyectos del usuario (y de la organización para resumen)
    proyectos_qs = Proyecto.objects.all()
    if org:
        proyectos_qs = proyectos_qs.filter(organizacion_id=org.id)
    total_proyectos = proyectos_qs.count()

    ultimos_proyectos = proyectos_qs.select_related('cliente').order_by('-fecha_creacion')[:5]

    # Organizaciones activas (si soporte o general, global; si no, 1 si org existe)
    if ctx.get('is_support') or ctx.get('organization_is_general') or not org:
        try:
            organizaciones_activas = Organizacion.objects.filter(activo=True).count()
        except Exception:
            organizaciones_activas = 0
    else:
        organizaciones_activas = 1

    context={
        "title": "Dashboard",
        "subTitle": "Panel",
        "perfil": perfil,
        "organizacion": org,
        "total_usuarios": total_usuarios,
        "total_proyectos": total_proyectos,
        "ultimos_proyectos": ultimos_proyectos,
        "organizaciones_activas": organizaciones_activas,
    }
    return render(request,"index.html", context)
    
def kanban(request):
    context={
        "title": "Kanban",
        "subTitle": "Kanban",
    }
    return render(request,"kanban.html", context)
    
def maintenance(request):
    context={
        "title": "",
        "subTitle": "",
    }
    return render(request,"maintenance.html", context)
    
def notFound(request):
    context={
        "title": "404",
        "subTitle": "404",
    }
    return render(request,"notFound.html", context)
    
def pricing(request):
    context={
        "title": "Pricing",
        "subTitle": "Pricing",
    }
    return render(request,"pricing.html", context)
    
def stared(request):
    context={
        "title": "Email",
        "subTitle": "Components / Email",
    }
    return render(request,"stared.html", context)
    
def termsAndConditions(request):
    context={
        "title": "Terms & Condition",
        "subTitle": "Terms & Condition",
    }
    return render(request,"termsAndConditions.html", context)
    
def testimonials(request):
    context={
        "title": "Testimonials",
        "subTitle": "Testimonials",
    }
    return render(request,"testimonials.html", context)
    
def viewDetails(request):
    context={
        "title": "Email",
        "subTitle": "Components / Email",
    }
    return render(request,"viewDetails.html", context)
    
def widgets(request):
    context={
        "title": "Widgets",
        "subTitle": "Widgets",
    }
    return render(request,"widgets.html", context)


def public(request):
    """Endpoint público y sencillo para comprobar que el servidor responde.

    No requiere autenticación. Usar para verificar forwards/túneles cuando la raíz
    está protegida por login.
    """
    return HttpResponse("OK - App running (public endpoint)")
    