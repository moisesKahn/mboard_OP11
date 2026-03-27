from django.contrib import admin
from .models import Organizacion, Cliente, Material, Tapacanto, Proyecto, MaterialProyecto, UsuarioPerfilOptimizador, ConfiguracionEtiqueta

@admin.register(Organizacion)
class OrganizacionAdmin(admin.ModelAdmin):
    list_display = ('codigo', 'nombre', 'telefono', 'email', 'activo', 'fecha_creacion')
    list_filter = ('activo', 'fecha_creacion')
    search_fields = ('codigo', 'nombre', 'email')
    ordering = ('nombre',)

@admin.register(Cliente)
class ClienteAdmin(admin.ModelAdmin):
    list_display = ('rut', 'nombre', 'organizacion', 'telefono', 'activo', 'fecha_creacion')
    list_filter = ('activo', 'fecha_creacion', 'organizacion')
    search_fields = ('rut', 'nombre', 'organizacion__nombre', 'email')
    ordering = ('nombre',)

@admin.register(Material)
class MaterialAdmin(admin.ModelAdmin):
    list_display = ('codigo', 'nombre', 'tipo', 'espesor', 'ancho', 'largo', 'precio_m2', 'precio_tablero_display', 'stock', 'activo')
    list_filter = ('tipo', 'activo', 'proveedor')
    search_fields = ('codigo', 'nombre', 'proveedor')
    ordering = ('nombre',)

    def precio_tablero_display(self, obj):
        return f"${obj.precio_tablero:,.0f}".replace(',', '.')
    precio_tablero_display.short_description = 'Precio por tablero'

@admin.register(Tapacanto)
class TapacantoAdmin(admin.ModelAdmin):
    list_display = ('codigo', 'nombre', 'color', 'ancho', 'espesor', 'valor_por_metro', 'stock_metros', 'activo')
    list_filter = ('activo', 'proveedor')
    search_fields = ('codigo', 'nombre', 'color')
    ordering = ('nombre',)

@admin.register(Proyecto)
class ProyectoAdmin(admin.ModelAdmin):
    list_display = ('codigo', 'nombre', 'cliente', 'estado', 'fecha_inicio', 'eficiencia_promedio', 'costo_total', 'creado_por')
    list_filter = ('estado', 'fecha_inicio', 'creado_por')
    search_fields = ('codigo', 'nombre', 'cliente__nombre', 'cliente__rut')
    ordering = ('-fecha_creacion',)

@admin.register(MaterialProyecto)
class MaterialProyectoAdmin(admin.ModelAdmin):
    list_display = ('proyecto', 'material', 'cantidad_tableros', 'eficiencia', 'costo_material')
    list_filter = ('proyecto__estado',)
    search_fields = ('proyecto__codigo', 'material__nombre')

@admin.register(UsuarioPerfilOptimizador)
class UsuarioPerfilOptimizadorAdmin(admin.ModelAdmin):
    list_display = ('user', 'rol', 'organizacion', 'telefono', 'activo', 'fecha_ultimo_acceso')
    list_filter = ('rol', 'activo', 'organizacion')
    search_fields = ('user__username', 'user__first_name', 'user__last_name', 'organizacion__nombre')

@admin.register(ConfiguracionEtiqueta)
class ConfiguracionEtiquetaAdmin(admin.ModelAdmin):
    list_display = ('organizacion', 'ancho_mm', 'alto_mm', 'fuente_nombre', 'fecha_modificacion')
    list_filter = ('organizacion',)