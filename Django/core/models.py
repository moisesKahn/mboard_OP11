from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone

class Organizacion(models.Model):
    """Modelo para organizaciones/empresas del sistema"""
    codigo = models.CharField(max_length=20, unique=True, verbose_name="Código")
    nombre = models.CharField(max_length=150, verbose_name="Nombre de la Organización")
    # Indica si es la organización de Soporte con acceso global
    is_general = models.BooleanField(default=False, verbose_name="Organización General (Soporte)")
    direccion = models.TextField(blank=True, null=True, verbose_name="Dirección")
    telefono = models.CharField(max_length=15, blank=True, null=True, verbose_name="Teléfono")
    email = models.EmailField(blank=True, null=True, verbose_name="Email")
    activo = models.BooleanField(default=True, verbose_name="Activo")
    fecha_creacion = models.DateTimeField(auto_now_add=True, verbose_name="Fecha de Creación")
    
    class Meta:
        verbose_name = "Organización"
        verbose_name_plural = "Organizaciones"
        ordering = ['nombre']
    
    def __str__(self):
        return f"{self.nombre} ({self.codigo})"

    @staticmethod
    def generar_codigo(nombre):
        """
        Genera un código único a partir del nombre de la organización.
        Toma las iniciales de cada palabra (máx 4) en mayúsculas y añade
        un sufijo numérico secuencial de 3 dígitos hasta encontrar uno libre.
        Ejemplo: "Muebles del Sur S.A." → "MDS001", si existe → "MDS002"
        """
        import re
        palabras = re.findall(r'[A-Za-zÁÉÍÓÚáéíóúÑñ]+', nombre)
        prefijo = ''.join(p[0].upper() for p in palabras[:4])
        if not prefijo:
            prefijo = 'ORG'
        n = 1
        while True:
            candidato = f"{prefijo}{n:03d}"
            if not Organizacion.objects.filter(codigo=candidato).exists():
                return candidato
            n += 1

class Cliente(models.Model):
    """Modelo para clientes del sistema"""
    # RUT único por organización (no global): se aplica constraint en Meta
    rut = models.CharField(max_length=12, verbose_name="RUT")
    nombre = models.CharField(max_length=100, verbose_name="Nombre Completo")
    organizacion = models.ForeignKey(Organizacion, on_delete=models.SET_NULL, blank=True, null=True, verbose_name="Organización")
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, blank=True, null=True, verbose_name="Creado por", related_name="clientes_creados")
    telefono = models.CharField(max_length=15, blank=True, null=True, verbose_name="Teléfono")
    email = models.EmailField(blank=True, null=True, verbose_name="Email")
    direccion = models.TextField(blank=True, null=True, verbose_name="Dirección")
    activo = models.BooleanField(default=True, verbose_name="Activo")
    fecha_creacion = models.DateTimeField(auto_now_add=True, verbose_name="Fecha de Creación")
    
    class Meta:
        verbose_name = "Cliente"
        verbose_name_plural = "Clientes"
        ordering = ['nombre']
        indexes = [
            models.Index(fields=["organizacion", "fecha_creacion"], name="cli_org_fecha_idx"),
            models.Index(fields=["created_by", "fecha_creacion"], name="cli_creador_fecha_idx"),
        ]
        unique_together = [('rut', 'organizacion')]  # RUT único por organización
    
    def __str__(self):
        return f"{self.nombre} ({self.rut})"

class Material(models.Model):
    """Modelo para materiales (tableros, melaminas, etc.)"""
    TIPOS_MATERIAL = [
        ('melamina', 'Melamina'),
        ('mdf', 'MDF'), 
        ('osb', 'OSB'),
        ('terciado', 'Terciado'),
        ('aglomerado', 'Aglomerado'),
        ('otro', 'Otro')
    ]
    
    codigo = models.CharField(max_length=20, verbose_name="Código")
    nombre = models.CharField(max_length=100, verbose_name="Nombre del Material")
    tipo = models.CharField(max_length=20, choices=TIPOS_MATERIAL, verbose_name="Tipo de Material")
    espesor = models.DecimalField(max_digits=5, decimal_places=1, verbose_name="Espesor (mm)")
    ancho = models.IntegerField(verbose_name="Ancho (mm)")
    largo = models.IntegerField(verbose_name="Largo (mm)")
    precio_m2 = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Precio por m²")
    stock = models.IntegerField(default=0, verbose_name="Stock Disponible")
    proveedor = models.CharField(max_length=100, blank=True, null=True, verbose_name="Proveedor")
    organizacion = models.ForeignKey(Organizacion, on_delete=models.CASCADE, verbose_name="Organización", null=True, blank=True)
    activo = models.BooleanField(default=True, verbose_name="Activo")
    fecha_creacion = models.DateTimeField(auto_now_add=True, verbose_name="Fecha de Creación")
    
    class Meta:
        verbose_name = "Material"
        verbose_name_plural = "Materiales" 
        ordering = ['nombre']
        unique_together = ['codigo', 'organizacion']  # Código único por organización
        constraints = [
            models.CheckConstraint(check=models.Q(ancho__gte=models.F('largo')), name='material_ancho_mayor_igual_largo'),
            models.CheckConstraint(check=models.Q(ancho__gt=0) & models.Q(largo__gt=0), name='material_dimensiones_positivas'),
        ]
    
    def __str__(self):
        return f"{self.nombre} - {self.espesor}mm ({self.ancho}x{self.largo})"
    
    def clean(self):
        # Asegurar que ancho sea siempre la medida mayor (eje X)
        if self.ancho and self.largo and self.largo > self.ancho:
            self.ancho, self.largo = self.largo, self.ancho

    def save(self, *args, **kwargs):
        # Normaliza antes de guardar
        self.clean()
        super().save(*args, **kwargs)
    
    @property
    def area_m2(self):
        """Calcula el área del tablero en m²"""
        return (self.ancho * self.largo) / 1000000

    @property
    def precio_tablero(self):
        """Precio por tablero calculado como precio_m2 * área (m²)."""
        try:
            return float(self.precio_m2) * float(self.area_m2)
        except Exception:
            return 0.0

class Tapacanto(models.Model):
    """Modelo para tapacantos"""
    codigo = models.CharField(max_length=20, verbose_name="Código")
    nombre = models.CharField(max_length=100, verbose_name="Nombre del Tapacanto")
    color = models.CharField(max_length=50, verbose_name="Color")
    ancho = models.DecimalField(max_digits=5, decimal_places=1, verbose_name="Ancho (mm)")
    espesor = models.DecimalField(max_digits=5, decimal_places=2, verbose_name="Espesor (mm)")
    precio_metro = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Valor por metro")
    stock_metros = models.IntegerField(default=0, verbose_name="Stock en Metros")
    proveedor = models.CharField(max_length=100, blank=True, null=True, verbose_name="Proveedor")
    organizacion = models.ForeignKey(Organizacion, on_delete=models.CASCADE, verbose_name="Organización")
    activo = models.BooleanField(default=True, verbose_name="Activo")
    fecha_creacion = models.DateTimeField(auto_now_add=True, verbose_name="Fecha de Creación")
    
    class Meta:
        verbose_name = "Tapacanto"
        verbose_name_plural = "Tapacantos"
        ordering = ['nombre']
        unique_together = ['codigo', 'organizacion']  # Código único por organización
    
    def __str__(self):
        return f"{self.nombre} - {self.color} ({self.ancho}x{self.espesor}mm)"

    @property
    def valor_por_metro(self):
        """Alias semántico para precio_metro."""
        return self.precio_metro

class Proyecto(models.Model):
    """Modelo para proyectos de optimización"""
    ESTADOS = [
        ('borrador', 'Borrador'),
        ('en_proceso', 'En Proceso'),
        ('optimizado', 'Optimizado'),
        ('aprobado', 'Aprobado'),
        ('produccion', 'En Producción'),
        ('enchapado_pendiente', 'Enchapado Pendiente'),
        ('completado', 'Completado'),
        ('cancelado', 'Cancelado')
    ]
    
    codigo = models.CharField(max_length=20, unique=True, verbose_name="Código del Proyecto")
    # Scope por organización (obligatorio)
    organizacion = models.ForeignKey(Organizacion, on_delete=models.CASCADE, verbose_name="Organización")
    nombre = models.CharField(max_length=200, verbose_name="Nombre del Proyecto")
    cliente = models.ForeignKey(Cliente, on_delete=models.CASCADE, verbose_name="Cliente")
    descripcion = models.TextField(blank=True, null=True, verbose_name="Descripción")
    estado = models.CharField(max_length=20, choices=ESTADOS, default='borrador', verbose_name="Estado")
    fecha_inicio = models.DateField(verbose_name="Fecha de Inicio")
    fecha_entrega = models.DateField(blank=True, null=True, verbose_name="Fecha de Entrega")
    total_materiales = models.IntegerField(default=0, verbose_name="Total de Materiales")
    total_tableros = models.IntegerField(default=0, verbose_name="Total de Tableros")
    total_piezas = models.IntegerField(default=0, verbose_name="Total de Piezas")
    eficiencia_promedio = models.DecimalField(max_digits=5, decimal_places=2, default=0, verbose_name="Eficiencia Promedio (%)")
    costo_total = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name="Costo Total")
    archivo_pdf = models.CharField(max_length=200, blank=True, null=True, verbose_name="Archivo PDF")
    # ID público del proyecto (reemplaza Folio): único global, inicia en 100, se actualiza al optimizar
    public_id = models.IntegerField(blank=True, null=True, unique=True, verbose_name="ID del Proyecto")
    # Folio: correlativo por cliente y versión incremental
    correlativo = models.IntegerField(default=0, verbose_name="Correlativo")
    version = models.IntegerField(default=0, verbose_name="Versión")
    # Nuevos campos para el optimizador
    configuracion = models.JSONField(blank=True, null=True, verbose_name="Configuración del Proyecto")
    resultado_optimizacion = models.JSONField(blank=True, null=True, verbose_name="Resultado de Optimización")
    usuario = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name="Usuario", related_name="proyectos_optimizador")
    creado_por = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name="Creado por")
    fecha_creacion = models.DateTimeField(auto_now_add=True, verbose_name="Fecha de Creación")
    fecha_modificacion = models.DateTimeField(auto_now=True, verbose_name="Fecha de Modificación")
    # Operador asignado al proyecto (opcional)
    operador = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Operador", related_name='proyectos_operador')
    
    class Meta:
        verbose_name = "Proyecto"
        verbose_name_plural = "Proyectos"
        ordering = ['-fecha_creacion']
        unique_together = [('cliente', 'correlativo')]
        indexes = [
            models.Index(fields=["organizacion", "fecha_creacion"], name="proy_org_fecha_idx"),
        ]
    
    def __str__(self):
        return f"{self.codigo} - {self.nombre}"

    @property
    def folio(self) -> str:
        """Compat: mantenemos propiedad folio pero devolvemos el ID público si existe.
        Evita romper plantillas/JS que aún referencian 'folio'.
        """
        try:
            if self.public_id:
                return str(int(self.public_id))
        except Exception:
            pass
        try:
            return f"{int(self.correlativo)}-{int(self.version)}"
        except Exception:
            # Fallback robusto
            return f"{self.correlativo}-{self.version}"

class MaterialProyecto(models.Model):
    """Modelo para materiales utilizados en cada proyecto"""
    proyecto = models.ForeignKey(Proyecto, on_delete=models.CASCADE, related_name='materiales_utilizados')
    material = models.ForeignKey(Material, on_delete=models.CASCADE)
    tapacanto = models.ForeignKey(Tapacanto, on_delete=models.SET_NULL, null=True, blank=True)
    cantidad_tableros = models.IntegerField(verbose_name="Cantidad de Tableros")
    eficiencia = models.DecimalField(max_digits=5, decimal_places=2, verbose_name="Eficiencia (%)")
    area_utilizada = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Área Utilizada (cm²)")
    costo_material = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Costo del Material")
    
    class Meta:
        verbose_name = "Material del Proyecto"
        verbose_name_plural = "Materiales del Proyecto"
    
    def __str__(self):
        return f"{self.proyecto.codigo} - {self.material.nombre}"

class UsuarioPerfilOptimizador(models.Model):
    """Extensión del modelo User de Django para perfiles de usuario del sistema"""
    ROLES = [
        ('super_admin', 'Super Administrador'),  # Soporte / Organización General
        ('org_admin', 'Administrador de Organización'),  # ADMIN_ORG
        ('agente', 'Agente'),  # AGENTE
        ('subordinador', 'Subordinador'),  # SUBORDINADOR (solo lectura en materiales)
        ('operador', 'Operador'),  # OPERADOR (nuevo)
        ('enchapador', 'Enchapador'),  # ENCHAPADOR (proceso de tapacanto)
        ('supervisor', 'Supervisor'),  # SUPERVISOR (ver proyectos y métricas, sin administración global)
        ('autoservicio', 'Autoservicio'),  # AUTOSERVICIO (portal restringido de cliente)
    ]
    user = models.OneToOneField(User, on_delete=models.CASCADE, verbose_name="Usuario")
    rol = models.CharField(max_length=20, choices=ROLES, default='agente', verbose_name="Rol")
    telefono = models.CharField(max_length=15, blank=True, null=True, verbose_name="Teléfono")
    organizacion = models.ForeignKey(Organizacion, on_delete=models.SET_NULL, blank=True, null=True, verbose_name="Organización")
    activo = models.BooleanField(default=True, verbose_name="Activo")
    fecha_ultimo_acceso = models.DateTimeField(blank=True, null=True, verbose_name="Último Acceso")
    must_change_password = models.BooleanField(default=False, verbose_name="Debe cambiar contraseña")
    
    class Meta:
        verbose_name = "Perfil de Usuario"
        verbose_name_plural = "Perfiles de Usuario"
    
    def __str__(self):
        return f"{self.user.get_full_name()} ({self.rol})"


class Conversacion(models.Model):
    """Modelo para conversaciones de chat entre usuarios"""
    organizacion = models.ForeignKey(Organizacion, on_delete=models.CASCADE, verbose_name="Organización", null=True, blank=True)
    participantes = models.ManyToManyField(User, verbose_name="Participantes", related_name="conversaciones")
    nombre = models.CharField(max_length=100, blank=True, null=True, verbose_name="Nombre de la Conversación")
    es_grupal = models.BooleanField(default=False, verbose_name="Es Grupo")
    creado_en = models.DateTimeField(auto_now_add=True, verbose_name="Creado en")
    actualizado_en = models.DateTimeField(auto_now=True, verbose_name="Actualizado en")
    creado_por = models.ForeignKey(User, on_delete=models.CASCADE, related_name="conversaciones_creadas", verbose_name="Creado por")
    
    class Meta:
        verbose_name = "Conversación"
        verbose_name_plural = "Conversaciones"
        ordering = ['-actualizado_en']
    
    def __str__(self):
        if self.nombre:
            return self.nombre
        elif self.es_grupal:
            participantes = ", ".join([user.get_full_name() or user.username for user in self.participantes.all()[:3]])
            if self.participantes.count() > 3:
                participantes += f" y {self.participantes.count() - 3} más"
            return f"Grupo: {participantes}"
        else:
            participantes = self.participantes.all()
            if participantes.count() == 2:
                return f"Chat: {' y '.join([user.get_full_name() or user.username for user in participantes])}"
            return f"Conversación {self.id}"
    
    def ultimo_mensaje(self):
        """Obtiene el último mensaje de la conversación"""
        return self.mensajes.order_by('-enviado_en').first()
    
    def mensajes_no_leidos(self, usuario):
        """Cuenta los mensajes no leídos para un usuario específico"""
        return self.mensajes.exclude(autor=usuario).filter(leido=False).count()
    
    def otros_participantes(self, usuario_actual):
        """Obtiene los participantes excepto el usuario actual"""
        return self.participantes.exclude(id=usuario_actual.id)
    
    def nombre_display(self, usuario_actual):
        """Obtiene el nombre para mostrar en la interfaz"""
        if self.nombre:
            return self.nombre
        elif self.es_grupal:
            return f"Grupo ({self.participantes.count()} miembros)"
        else:
            otros = self.otros_participantes(usuario_actual)
            if otros.exists():
                otro_usuario = otros.first()
                return otro_usuario.get_full_name() or otro_usuario.username
            return "Conversación vacía"
    
    @property
    def fecha_actualizacion(self):
        """Alias para compatibilidad con el template"""
        return self.actualizado_en


class Mensaje(models.Model):
    """Modelo para mensajes de chat"""
    conversacion = models.ForeignKey(Conversacion, on_delete=models.CASCADE, related_name="mensajes", verbose_name="Conversación")
    autor = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name="Autor")
    contenido = models.TextField(verbose_name="Contenido")
    enviado_en = models.DateTimeField(auto_now_add=True, verbose_name="Enviado en")
    leido = models.BooleanField(default=False, verbose_name="Leído")
    editado = models.BooleanField(default=False, verbose_name="Editado")
    editado_en = models.DateTimeField(blank=True, null=True, verbose_name="Editado en")
    
    # Para archivos adjuntos (opcional)
    archivo_adjunto = models.FileField(upload_to='chat/archivos/', blank=True, null=True, verbose_name="Archivo Adjunto")
    
    class Meta:
        verbose_name = "Mensaje"
        verbose_name_plural = "Mensajes"
        ordering = ['enviado_en']
    
    def __str__(self):
        return f"{self.autor.get_full_name() or self.autor.username}: {self.contenido[:50]}..."
    
    def save(self, *args, **kwargs):
        # Actualizar el timestamp de la conversación cuando se crea un nuevo mensaje
        super().save(*args, **kwargs)
        self.conversacion.actualizado_en = self.enviado_en
        self.conversacion.save(update_fields=['actualizado_en'])
    
    @property
    def remitente(self):
        """Alias de autor para compatibilidad con template"""
        return self.autor
    
    @property
    def fecha_creacion(self):
        """Alias de enviado_en para compatibilidad con template"""
        return self.enviado_en
    
    @property
    def archivo(self):
        """Alias de archivo_adjunto para compatibilidad con template"""
        return self.archivo_adjunto


class MensajeLeido(models.Model):
    """Modelo para trackear qué mensajes ha leído cada usuario"""
    usuario = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name="Usuario")
    mensaje = models.ForeignKey(Mensaje, on_delete=models.CASCADE, verbose_name="Mensaje")
    leido_en = models.DateTimeField(auto_now_add=True, verbose_name="Leído en")
    
    class Meta:
        verbose_name = "Mensaje Leído"
        verbose_name_plural = "Mensajes Leídos"
        unique_together = ['usuario', 'mensaje']
    
    def __str__(self):
        return f"{self.usuario.username} leyó mensaje {self.mensaje.id}"


class AuditLog(models.Model):
    """Registro de auditoría de acciones del sistema"""
    VERBS = [
        ("LOGIN", "LOGIN"),
        ("CREATE", "CREATE"),
        ("UPDATE", "UPDATE"),
        ("DELETE", "DELETE"),
        ("RUN_OPT", "RUN_OPT"),
        ("MOVE", "MOVE"),
        ("EDIT", "EDIT"),
    ]
    actor = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Actor")
    organizacion = models.ForeignKey(Organizacion, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Organización")
    verb = models.CharField(max_length=20, choices=VERBS, verbose_name="Acción")
    target_model = models.CharField(max_length=120, verbose_name="Modelo")
    target_id = models.CharField(max_length=64, verbose_name="ID Objetivo")
    target_repr = models.TextField(blank=True, null=True, verbose_name="Representación")
    changes = models.JSONField(blank=True, null=True, verbose_name="Cambios/Metadatos")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Creado en")

    class Meta:
        verbose_name = "Auditoría"
        verbose_name_plural = "Auditorías"
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=["organizacion", "created_at"], name="audit_org_fecha_idx"),
            models.Index(fields=["actor", "created_at"], name="audit_actor_fecha_idx"),
        ]

    def __str__(self):
        return f"{self.verb} {self.target_model}({self.target_id}) por {self.actor_id or 'sistema'}"


class OptimizationRun(models.Model):
    """Ejecución del optimizador asociada a un proyecto"""
    organizacion = models.ForeignKey(Organizacion, on_delete=models.CASCADE, verbose_name="Organización")
    proyecto = models.ForeignKey(Proyecto, on_delete=models.CASCADE, verbose_name="Proyecto")
    run_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Ejecutado por")
    run_at = models.DateTimeField(default=timezone.now, verbose_name="Ejecutado en")
    porcentaje_uso = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True, verbose_name="% uso tablero")
    tiempo_ms = models.IntegerField(null=True, blank=True, verbose_name="Tiempo (ms)")

    class Meta:
        verbose_name = "Ejecución de Optimización"
        verbose_name_plural = "Ejecuciones de Optimización"
        ordering = ['-run_at']
        indexes = [
            models.Index(fields=["organizacion", "run_at"], name="opt_org_fecha_idx"),
            models.Index(fields=["proyecto", "run_at"], name="opt_proy_fecha_idx"),
        ]

    def __str__(self):
        return f"Run {self.id} Proy {self.proyecto_id} ({self.run_at:%Y-%m-%d %H:%M})"