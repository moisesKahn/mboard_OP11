from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, HttpResponse
from core.models import ConfiguracionEtiqueta
import json
import math


def company(request):
    context={
        "title": "Company",
        "subTitle": "Settings - Company",
    }
    return render(request,"settings/company.html", context)

def currencies(request):
    context={
        "title": "Currrencies",
        "subTitle": "Settings - Currencies",
    }
    return render(request,"settings/currencies.html", context)

def languages(request):
    context={
        "title": "Languages",
        "subTitle": "Settings - Languages",
    }
    return render(request,"settings/languages.html", context)

def notification(request):
    context={
        "title": "Notification",
        "subTitle": "Settings - Notification",
    }
    return render(request,"settings/notification.html", context)

def notificationAlert(request):
    context={
        "title": "Notification Alert",
        "subTitle": "Settings - Notification Alert",
    }
    return render(request,"settings/notificationAlert.html", context)

def paymentGetway(request):
    context={
        "title": "Payment Getway",
        "subTitle": "Settings - Payment Getway",
    }
    return render(request,"settings/paymentGetway.html", context)

def theme(request):
    context={
        "title": "Theme",
        "subTitle": "Settings - Theme",
    }
    return render(request,"settings/theme.html", context)


# ── Configuración de etiqueta ZPL ─────────────────────────────────────────────

@login_required
def etiqueta_config(request):
    """Vista del configurador visual de etiqueta."""
    perfil = getattr(request.user, 'usuarioperfiloptimizador', None)
    org = getattr(perfil, 'organizacion', None) if perfil else None
    config = ConfiguracionEtiqueta.get_config(org)
    context = {
        "title": "Diseño de Etiqueta",
        "subTitle": "Ajustes - Diseño de Etiqueta",
        "config": config,
        "escala_pct": int(config.escala_dibujo * 100),
        "posiciones_json": json.dumps(config.posiciones or {}),
    }
    return render(request, "settings/etiqueta.html", context)


@login_required
def api_label_config_save(request):
    """POST: Guarda la configuración de etiqueta."""
    if request.method != 'POST':
        return JsonResponse({'error': 'POST requerido'}, status=405)
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'JSON inválido'}, status=400)

    perfil = getattr(request.user, 'usuarioperfiloptimizador', None)
    org = getattr(perfil, 'organizacion', None) if perfil else None
    config = ConfiguracionEtiqueta.get_config(org)

    config.ancho_mm = max(20, min(150, int(data.get('ancho_mm', 70))))
    config.alto_mm = max(15, min(150, int(data.get('alto_mm', 50))))
    config.mostrar_nombre = bool(data.get('mostrar_nombre', True))
    config.mostrar_material = bool(data.get('mostrar_material', True))
    config.mostrar_cliente = bool(data.get('mostrar_cliente', False))
    config.mostrar_proyecto_id = bool(data.get('mostrar_proyecto_id', False))
    config.mostrar_dibujo = bool(data.get('mostrar_dibujo', True))
    config.mostrar_cotas = bool(data.get('mostrar_cotas', True))
    config.mostrar_tapacantos = bool(data.get('mostrar_tapacantos', True))
    config.mostrar_veta = bool(data.get('mostrar_veta', True))
    config.fuente_nombre = max(16, min(96, int(data.get('fuente_nombre', 32))))
    config.fuente_material = max(16, min(80, int(data.get('fuente_material', 24))))
    config.fuente_cotas = max(14, min(64, int(data.get('fuente_cotas', 22))))
    config.fuente_pie = max(14, min(64, int(data.get('fuente_pie', 22))))
    config.fuente_cliente = max(14, min(64, int(data.get('fuente_cliente', 20))))
    config.fuente_proyecto_id = max(14, min(64, int(data.get('fuente_proyecto_id', 20))))
    config.escala_dibujo = max(0.3, min(1.0, float(data.get('escala_dibujo', 0.75))))
    config.grosor_borde = max(1, min(10, int(data.get('grosor_borde', 2))))
    config.posiciones = data.get('posiciones', {})
    config.save()
    return JsonResponse({'ok': True})


@login_required
def api_label_config_get(request):
    """GET: Devuelve la configuración de etiqueta como JSON (para el operador)."""
    perfil = getattr(request.user, 'usuarioperfiloptimizador', None)
    org = getattr(perfil, 'organizacion', None) if perfil else None
    config = ConfiguracionEtiqueta.get_config(org)
    return JsonResponse(config.to_dict())


@login_required
def api_label_test_zpl(request):
    """POST: Genera ZPL de prueba con la configuración recibida."""
    if request.method != 'POST':
        return JsonResponse({'error': 'POST requerido'}, status=405)
    try:
        c = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'JSON inválido'}, status=400)

    zpl = _generar_zpl_con_config(c, {
        'nombre': 'Puerta Sup',
        'ancho': 600,
        'largo': 400,
        'pieza_idx': 3,
        'pieza_count': 8,
        'material': 'Melamina Blanco',
        'cliente': 'Demo S.A.',
        'proyecto_id': 'PRJ-2026032314',
        'tapacantos': {'arriba': True, 'derecha': True, 'abajo': False, 'izquierda': False},
        'veta': 'vertical',
    })
    return HttpResponse(zpl, content_type='text/plain; charset=utf-8')


def _generar_zpl_con_config(cfg, pieza):
    """Genera ZPL usando la configuración dinámica con posiciones arrastrables."""
    DPI = 300
    def mm2d(v): return round(v * DPI / 25.4)
    def _z(s, mx): return str(s or '')[:mx].replace('^', '').replace('~', '')

    ancho_mm = int(cfg.get('ancho_mm', 70))
    alto_mm = int(cfg.get('alto_mm', 50))
    LW = mm2d(ancho_mm)
    LH = mm2d(alto_mm)

    pw_mm = int(pieza.get('ancho', 0))
    ph_mm = int(pieza.get('largo', 0))
    nombre = pieza.get('nombre', '')
    tc = pieza.get('tapacantos', {})
    veta = pieza.get('veta', '')
    mat = pieza.get('material', '')
    cliente = pieza.get('cliente', '')
    proy_id = pieza.get('proyecto_id', '')
    p_idx = pieza.get('pieza_idx', '')
    p_count = pieza.get('pieza_count', '')
    count_str = f' ({p_idx}/{p_count})' if p_count else ''

    f_nombre = int(cfg.get('fuente_nombre', 32))
    f_material = int(cfg.get('fuente_material', 24))
    f_cotas = int(cfg.get('fuente_cotas', 22))
    f_pie = int(cfg.get('fuente_pie', 22))
    f_cliente = int(cfg.get('fuente_cliente', 20))
    f_proyid = int(cfg.get('fuente_proyecto_id', 20))
    escala = float(cfg.get('escala_dibujo', 0.75))
    grosor = max(1, int(cfg.get('grosor_borde', 2)))

    # Posiciones (porcentaje → dots)
    posiciones = cfg.get('posiciones', {})
    def pos_x(field, default_pct=3):
        p = posiciones.get(field, {})
        return round(float(p.get('x', default_pct)) / 100 * LW)
    def pos_y(field, default_pct=10):
        p = posiciones.get(field, {})
        return round(float(p.get('y', default_pct)) / 100 * LH)

    lines = [
        '^XA', '^LH0,0',
        f'^PW{LW}', f'^LL{LH}',
        '^MNY', '^MTT', f'^LL{LH}',
        '^CI28',
    ]

    if cfg.get('mostrar_proyecto_id'):
        x = pos_x('proyid', 3)
        y = pos_y('proyid', 2)
        lines.append(f'^FO{x},{y}^CF0,{f_proyid}^FD#{_z(proy_id, 20)}^FS')

    if cfg.get('mostrar_nombre'):
        x = pos_x('nombre', 3)
        y = pos_y('nombre', 14)
        lines.append(f'^FO{x},{y}^CF0,{f_nombre}^FD{_z(nombre + count_str, 30)}^FS')

    if cfg.get('mostrar_material'):
        x = pos_x('material', 3)
        y = pos_y('material', 30)
        lines.append(f'^FO{x},{y}^CF0,{f_material}^FD{_z(mat, 30)}^FS')

    if cfg.get('mostrar_cliente'):
        x = pos_x('cliente', 3)
        y = pos_y('cliente', 44)
        lines.append(f'^FO{x},{y}^CF0,{f_cliente}^FD{_z("Cli: " + cliente, 28)}^FS')

    if cfg.get('mostrar_dibujo'):
        dx = pos_x('dibujo', 10)
        dy = pos_y('dibujo', 48)
        da_w = LW - dx - mm2d(2)
        da_h = LH - dy - (f_pie + mm2d(3) if (cfg.get('mostrar_tapacantos') or cfg.get('mostrar_veta')) else mm2d(2))
        sc = min(da_w / max(pw_mm, 1), da_h / max(ph_mm, 1)) * escala
        rw = round(pw_mm * sc)
        rh = round(ph_mm * sc)
        rx = dx
        ry = dy

        lines.append(f'^FO{rx},{ry}^GB{rw},{rh},{grosor},W^FS')
        lines.append(f'^FO{rx},{ry}^GB{rw},{rh},{grosor}^FS')

        if cfg.get('mostrar_tapacantos'):
            tc_t = max(2, grosor + 1)
            tc_off = max(3, round(min(rw, rh) * 0.07))
            if tc.get('arriba'):    lines.append(f'^FO{rx},{ry+tc_off}^GB{rw},{tc_t},{tc_t}^FS')
            if tc.get('abajo'):     lines.append(f'^FO{rx},{ry+rh-tc_off-tc_t}^GB{rw},{tc_t},{tc_t}^FS')
            if tc.get('izquierda'): lines.append(f'^FO{rx+tc_off},{ry}^GB{tc_t},{rh},{tc_t}^FS')
            if tc.get('derecha'):   lines.append(f'^FO{rx+rw-tc_off-tc_t},{ry}^GB{tc_t},{rh},{tc_t}^FS')

        if cfg.get('mostrar_cotas'):
            lines.append(f'^FO{rx},{max(0, ry - mm2d(4))}^CF0,{f_cotas}^FD{pw_mm}mm^FS')
            lines.append(f'^FO{rx+rw+mm2d(1)},{ry+round(rh/2)-round(f_cotas/2)}^CF0,{f_cotas}^FD{ph_mm}mm^FS')

    # Pie (Tc + Veta)
    if cfg.get('mostrar_tapacantos') or cfg.get('mostrar_veta'):
        tc_parts = []
        if tc.get('arriba'):    tc_parts.append('Arr')
        if tc.get('derecha'):   tc_parts.append('Der')
        if tc.get('abajo'):     tc_parts.append('Aba')
        if tc.get('izquierda'): tc_parts.append('Izq')
        pie = ''
        if cfg.get('mostrar_tapacantos'):
            pie += 'Tc:' + (' '.join(tc_parts) if tc_parts else '-')
        veta_str = 'H' if veta == 'horizontal' else 'V' if veta == 'vertical' else ''
        if cfg.get('mostrar_veta') and veta_str:
            pie += ('  ' if pie else '') + 'V:' + veta_str
        px = pos_x('pie', 3)
        py = pos_y('pie', 88)
        lines.append(f'^FO{px},{py}^CF0,{f_pie}^FD{_z(pie, 30)}^FS')

    lines += ['^JUS', '^PQ1', '^XZ']
    return '\n'.join(lines)
