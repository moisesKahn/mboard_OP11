from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from core.models import Organizacion, UsuarioPerfilOptimizador, Material, Tapacanto, Cliente, Proyecto
from django.utils import timezone
from django.utils.text import slugify
from django.conf import settings
import os
import json

try:
    # Reusar motor y renderer del PDF para consistencia
    from WowDash.optimizer_views import OptimizationEngine, _pdf_from_result
except Exception:  # pragma: no cover - fallback si la importación falla
    OptimizationEngine = None
    _pdf_from_result = None


class Command(BaseCommand):
    help = "Crea datos de ejemplo: 3 organizaciones, usuarios (admin org, 3 agentes, 3 operarios) y catálogos (materiales y tapacantos) por organización."

    def add_arguments(self, parser):
        parser.add_argument(
            '--reset-passwords', action='store_true', default=False,
            help='Reestablece las contraseñas de los usuarios demo si ya existen.'
        )

    def handle(self, *args, **options):
        reset_passwords = bool(options.get('reset_passwords'))

        org_specs = [
            ("ORG001", "Organización Alfa"),
            ("ORG002", "Organización Beta"),
            ("ORG003", "Organización Gamma"),
        ]

        demo_users = []  # para imprimir credenciales

        for idx, (code, name) in enumerate(org_specs, start=1):
            org, _ = Organizacion.objects.get_or_create(
                codigo=code,
                defaults={
                    'nombre': name,
                    'is_general': False,
                    'direccion': f"Calle Demo {idx} #123",
                    'telefono': f"+34 600 000 00{idx}",
                    'email': f"contacto{idx}@demo.local",
                    'activo': True,
                }
            )

            # Usuarios
            def ensure_user(username, password, first_name, last_name, email, rol):
                user, created = User.objects.get_or_create(
                    username=username,
                    defaults={
                        'first_name': first_name,
                        'last_name': last_name,
                        'email': email,
                        'is_active': True,
                    }
                )
                if created or reset_passwords:
                    user.set_password(password)
                    user.save()
                # Perfil/rol
                perfil, _ = UsuarioPerfilOptimizador.objects.get_or_create(
                    user=user,
                    defaults={'rol': rol, 'organizacion': org, 'activo': True}
                )
                # Si existe y no coincide organización/rol, actualizar suavemente
                changed = False
                if perfil.organizacion_id != org.id:
                    perfil.organizacion = org
                    changed = True
                if perfil.rol != rol:
                    perfil.rol = rol
                    changed = True
                if changed:
                    perfil.save(update_fields=['organizacion', 'rol'])
                demo_users.append((org.nombre, username, password, rol))

            # Admin organizador
            ensure_user(
                username=f"org{idx}_admin",
                password=f"Org{idx}!Admin123",
                first_name="Admin",
                last_name=f"Org{idx}",
                email=f"admin{idx}@demo.local",
                rol='org_admin'
            )

            # Agentes (3)
            for a in range(1, 4):
                ensure_user(
                    username=f"org{idx}_agente{a}",
                    password=f"Org{idx}!Agente{a}#",
                    first_name=f"Agente{a}",
                    last_name=f"Org{idx}",
                    email=f"agente{a}.{idx}@demo.local",
                    rol='agente'
                )

            # Operarios (3)
            for o in range(1, 4):
                ensure_user(
                    username=f"org{idx}_operador{o}",
                    password=f"Org{idx}!Oper{o}$",
                    first_name=f"Operador{o}",
                    last_name=f"Org{idx}",
                    email=f"operador{o}.{idx}@demo.local",
                    rol='operador'
                )

            # Catálogo de materiales (tableros) para la organización
            materiales_specs = [
                (f"MEL-{idx}01", "Melamina Blanca 15mm", 'melamina', 15.0, 2750, 1830, 10.50, 20, "Proveedor A"),
                (f"MDF-{idx}02", "MDF Crudo 18mm", 'mdf', 18.0, 2440, 1830, 9.90, 15, "Proveedor B"),
                (f"TER-{idx}03", "Terciado Pino 18mm", 'terciado', 18.0, 2440, 1220, 8.75, 10, "Proveedor C"),
            ]
            for codigo, nombre, tipo, espesor, ancho, largo, precio_m2, stock, proveedor in materiales_specs:
                Material.objects.get_or_create(
                    codigo=codigo,
                    organizacion=org,
                    defaults={
                        'nombre': nombre,
                        'tipo': tipo,
                        'espesor': espesor,
                        'ancho': ancho,
                        'largo': largo,
                        'precio_m2': precio_m2,
                        'stock': stock,
                        'proveedor': proveedor,
                        'activo': True,
                    }
                )

            # Catálogo de tapacantos para la organización
            tapacantos_specs = [
                (f"TAP-{idx}10", "Tapa Blanco", "Blanco", 22.0, 0.45, 0.25, 100, "Proveedor A"),
                (f"TAP-{idx}11", "Tapa Roble", "Roble", 22.0, 0.45, 0.35, 80, "Proveedor B"),
                (f"TAP-{idx}12", "Tapa Gris", "Gris", 22.0, 0.45, 0.30, 60, "Proveedor C"),
            ]
            for codigo, nombre, color, ancho, espesor, precio_m, stock_m, proveedor in tapacantos_specs:
                Tapacanto.objects.get_or_create(
                    codigo=codigo,
                    organizacion=org,
                    defaults={
                        'nombre': nombre,
                        'color': color,
                        'ancho': ancho,
                        'espesor': espesor,
                        'precio_metro': precio_m,
                        'stock_metros': stock_m,
                        'proveedor': proveedor,
                        'activo': True,
                    }
                )

            # ==========================
            # Clientes y Proyectos demo
            # ==========================
            # Crear 15 clientes por organización
            clientes = []
            for cidx in range(1, 16):
                rut = f"{code}-C{cidx:03d}"
                nombre_cli = f"Cliente {name.split()[1]} {cidx:02d}" if ' ' in name else f"Cliente {name} {cidx:02d}"
                cli, _ = Cliente.objects.get_or_create(
                    rut=rut,
                    organizacion=org,
                    defaults={
                        'nombre': nombre_cli,
                        'activo': True,
                    }
                )
                if not cli.organizacion:
                    cli.organizacion = org
                    cli.save(update_fields=['organizacion'])
                clientes.append(cli)

            # Elegir admin como propietario de proyectos
            try:
                admin_user = User.objects.get(username=f"org{idx}_admin")
            except User.DoesNotExist:
                admin_user = User.objects.filter(is_superuser=True).first() or User.objects.first()

            # Material y tapacanto por defecto
            mat_default = Material.objects.filter(organizacion=org, activo=True).order_by('id').first()
            tap_default = Tapacanto.objects.filter(organizacion=org, activo=True).order_by('id').first()

            # Crear 15 proyectos por organización (uno por cliente)
            public_id_seed = (Proyecto.objects.exclude(public_id__isnull=True).order_by('-public_id').first().public_id + 1) if Proyecto.objects.exclude(public_id__isnull=True).exists() else 100

            for pidx, cli in enumerate(clientes, start=1):
                codigo = f"PROJ-{code}-{pidx:03d}"
                nombre_proy = f"Muebles Demo {pidx:02d}"
                proyecto, created = Proyecto.objects.get_or_create(
                    codigo=codigo,
                    defaults={
                        'organizacion': org,
                        'nombre': nombre_proy,
                        'cliente': cli,
                        'descripcion': 'Proyecto de ejemplo generado por seed_demo',
                        'estado': 'borrador',
                        'fecha_inicio': timezone.now().date(),
                        'usuario': admin_user,
                        'creado_por': admin_user,
                        'correlativo': 1,
                        'version': 0,
                    }
                )

                # Configuración mínima del proyecto (1 material + piezas)
                if mat_default:
                    piezas_demo = [
                        { 'nombre': 'Lateral', 'ancho': 400, 'largo': 700, 'cantidad': 2, 'veta_libre': False, 'tapacantos': {'arriba': True, 'abajo': True} },
                        { 'nombre': 'Base',    'ancho': 600, 'largo': 500, 'cantidad': 1, 'veta_libre': True,  'tapacantos': {'derecha': True} },
                        { 'nombre': 'Puerta',  'ancho': 300, 'largo': 450, 'cantidad': 2, 'veta_libre': False, 'tapacantos': {} },
                        { 'nombre': 'Repisa',  'ancho': 550, 'largo': 250, 'cantidad': 2, 'veta_libre': True,  'tapacantos': {'arriba': True} },
                    ]
                    conf_mat = {
                        'material_id': mat_default.id,
                        'ancho_custom': mat_default.ancho,
                        'largo_custom': mat_default.largo,
                        'margen_x': 10,
                        'margen_y': 10,
                        'desperdicio_sierra': 3,
                        'tapacanto_codigo': (tap_default.codigo if tap_default else ''),
                        'tapacanto_nombre': (tap_default.nombre if tap_default else ''),
                    }
                    # Guardar configuración agregada en el proyecto (multi-material listo)
                    proyecto.configuracion = json.dumps({
                        'materiales': [
                            {'configuracion_material': conf_mat, 'piezas': piezas_demo}
                        ]
                    }, ensure_ascii=False)
                    proyecto.save(update_fields=['configuracion'])

                    # Ejecutar una optimización simple para tener layout y PDF
                    if OptimizationEngine is not None:
                        try:
                            engine = OptimizationEngine(conf_mat['ancho_custom'], conf_mat['largo_custom'], conf_mat['margen_x'], conf_mat['margen_y'], conf_mat['desperdicio_sierra'])
                            piezas_proc = []
                            for pz in piezas_demo:
                                piezas_proc.append({
                                    'nombre': pz['nombre'],
                                    'ancho': pz['ancho'],
                                    'largo': pz['largo'],
                                    'cantidad': pz.get('cantidad', 1),
                                    'veta_libre': pz.get('veta_libre', False),
                                    'tapacantos': pz.get('tapacantos', {}) or {}
                                })
                            r = engine.optimizar_piezas(piezas_proc)
                            r['entrada'] = piezas_proc
                            r['material'] = {
                                'nombre': mat_default.nombre,
                                'codigo': mat_default.codigo,
                                'ancho_original': mat_default.ancho,
                                'largo_original': mat_default.largo,
                                'ancho_usado': conf_mat['ancho_custom'],
                                'largo_usado': conf_mat['largo_custom']
                            }
                            r['config'] = {'margen_x': conf_mat['margen_x'], 'margen_y': conf_mat['margen_y'], 'kerf': conf_mat['desperdicio_sierra']}
                            r['tapacanto'] = { 'codigo': conf_mat['tapacanto_codigo'], 'nombre': conf_mat['tapacanto_nombre'] }

                            resultado_persist = {
                                'materiales': [r],
                                'total_tableros': len(r.get('tableros', [])),
                                'total_piezas': sum(len(tb.get('piezas', [])) for tb in r.get('tableros', [])),
                                'eficiencia_promedio': r.get('eficiencia', 0) or 0,
                                'ultimo_folio': f"SEED-{timezone.now().strftime('%Y%m%d%H%M%S')}"
                            }
                            proyecto.resultado_optimizacion = resultado_persist
                            proyecto.total_materiales = 1
                            proyecto.total_tableros = resultado_persist['total_tableros']
                            proyecto.total_piezas = resultado_persist['total_piezas']
                            proyecto.eficiencia_promedio = resultado_persist['eficiencia_promedio']
                            proyecto.estado = 'optimizado'
                            # Asignar un public_id global incremental
                            proyecto.public_id = public_id_seed
                            public_id_seed += 1
                            proyecto.save()

                            # Generar PDF del layout
                            if _pdf_from_result is not None:
                                try:
                                    pdf_bytes = _pdf_from_result(proyecto, resultado_persist)
                                    rel_dir = f"proyectos/{proyecto.id}"
                                    cliente_slug = slugify(proyecto.cliente.nombre) if proyecto.cliente_id else 'cliente'
                                    rel_path = f"{rel_dir}/optimizacion_{proyecto.public_id}_{cliente_slug}.pdf"
                                    abs_dir = os.path.join(settings.MEDIA_ROOT, rel_dir)
                                    os.makedirs(abs_dir, exist_ok=True)
                                    abs_path = os.path.join(settings.MEDIA_ROOT, rel_path)
                                    with open(abs_path, 'wb') as fh:
                                        fh.write(pdf_bytes)
                                    proyecto.archivo_pdf = rel_path
                                    proyecto.save(update_fields=['archivo_pdf'])
                                except Exception:
                                    pass
                        except Exception:
                            # Si algo falla, el proyecto igual queda creado con configuración
                            pass

        # Mostrar resumen de credenciales
        self.stdout.write(self.style.SUCCESS("Datos de ejemplo creados/actualizados con éxito.\n"))
        self.stdout.write("Credenciales de usuarios demo (usuario / contraseña / rol):\n")
        current_org = None
        for org_name, username, password, rol in demo_users:
            if current_org != org_name:
                self.stdout.write(f"\n== {org_name} ==")
                current_org = org_name
            self.stdout.write(f"  - {username} / {password} / {rol}")
