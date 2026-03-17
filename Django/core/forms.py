from django import forms
from .models import Cliente, Material, Tapacanto, Proyecto, UsuarioPerfilOptimizador
from django.contrib.auth.models import User

class ClienteForm(forms.ModelForm):
    """Formulario para crear/editar clientes"""
    
    class Meta:
        model = Cliente
        fields = ['rut', 'nombre', 'organizacion', 'telefono', 'email', 'direccion', 'activo']
        widgets = {
            'rut': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Ej: 12.345.678-9'
            }),
            'nombre': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Nombre completo del cliente'
            }),
            'organizacion': forms.Select(attrs={
                'class': 'form-control form-select',
                'placeholder': 'Seleccione una organización'
            }),
            'telefono': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': '+56 9 XXXX XXXX'
            }),
            'email': forms.EmailInput(attrs={
                'class': 'form-control',
                'placeholder': 'cliente@email.com'
            }),
            'direccion': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Dirección completa del cliente'
            }),
            'activo': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            })
        }

class MaterialForm(forms.ModelForm):
    """Formulario para crear/editar materiales"""
    
    class Meta:
        model = Material
        fields = ['codigo', 'nombre', 'tipo', 'espesor', 'ancho', 'largo', 'precio_m2', 'stock', 'proveedor', 'activo']
        widgets = {
            'codigo': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Ej: MEL15-001'
            }),
            'nombre': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Nombre del material'
            }),
            'tipo': forms.Select(attrs={
                'class': 'form-select'
            }),
            'espesor': forms.NumberInput(attrs={
                'class': 'form-control',
                'placeholder': '15.0',
                'step': '0.1'
            }),
            'ancho': forms.NumberInput(attrs={
                'class': 'form-control',
                'placeholder': '1830'
            }),
            'largo': forms.NumberInput(attrs={
                'class': 'form-control',
                'placeholder': '2500'
            }),
            'precio_m2': forms.NumberInput(attrs={
                'class': 'form-control',
                'placeholder': '25000.00',
                'step': '0.01'
            }),
            'stock': forms.NumberInput(attrs={
                'class': 'form-control',
                'placeholder': '0'
            }),
            'proveedor': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Nombre del proveedor'
            }),
            'activo': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            })
        }

class TapacantoForm(forms.ModelForm):
    """Formulario para crear/editar tapacantos"""
    
    class Meta:
        model = Tapacanto
        fields = ['codigo', 'nombre', 'color', 'ancho', 'espesor', 'precio_metro', 'stock_metros', 'proveedor', 'activo']
        widgets = {
            'codigo': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Ej: PVC-001'
            }),
            'nombre': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Nombre del tapacanto'
            }),
            'color': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Color del tapacanto'
            }),
            'ancho': forms.NumberInput(attrs={
                'class': 'form-control',
                'placeholder': '19.0',
                'step': '0.1'
            }),
            'espesor': forms.NumberInput(attrs={
                'class': 'form-control',
                'placeholder': '1.5',
                'step': '0.01'
            }),
            'precio_metro': forms.NumberInput(attrs={
                'class': 'form-control',
                'placeholder': '500.00',
                'step': '0.01'
            }),
            'stock_metros': forms.NumberInput(attrs={
                'class': 'form-control',
                'placeholder': '0'
            }),
            'proveedor': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Nombre del proveedor'
            }),
            'activo': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            })
        }

class ProyectoForm(forms.ModelForm):
    """Formulario para crear/editar proyectos"""
    
    class Meta:
        model = Proyecto
        fields = ['codigo', 'nombre', 'cliente', 'descripcion', 'estado', 'fecha_inicio', 'fecha_entrega']
        widgets = {
            'codigo': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Ej: PROJ-001'
            }),
            'nombre': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Nombre del proyecto'
            }),
            'cliente': forms.Select(attrs={
                'class': 'form-select'
            }),
            'descripcion': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 4,
                'placeholder': 'Descripción del proyecto'
            }),
            'estado': forms.Select(attrs={
                'class': 'form-select'
            }),
            'fecha_inicio': forms.DateInput(attrs={
                'class': 'form-control',
                'type': 'date'
            }),
            'fecha_entrega': forms.DateInput(attrs={
                'class': 'form-control',
                'type': 'date'
            })
        }

class UsuarioForm(forms.ModelForm):
    """Formulario para crear/editar usuarios.
    - En crear: Contraseña y Confirmar Contraseña son OBLIGATORIAS.
    - En editar: campos de contraseña son opcionales; si se completa uno, validar coincidencia y longitud.
    """

    password = forms.CharField(
        label='Contraseña',
        required=False,
        widget=forms.PasswordInput(attrs={'class': 'form-control radius-8', 'placeholder': '********'})
    )
    confirm_password = forms.CharField(
        label='Confirmar Contraseña',
        required=False,
        widget=forms.PasswordInput(attrs={'class': 'form-control radius-8', 'placeholder': '********'})
    )

    class Meta:
        model = User
        fields = ['username', 'first_name', 'last_name', 'email', 'is_active', 'password', 'confirm_password']
        widgets = {
            'username': forms.TextInput(attrs={
                'class': 'form-control radius-8',
                'placeholder': 'Nombre de usuario'
            }),
            'first_name': forms.TextInput(attrs={
                'class': 'form-control radius-8',
                'placeholder': 'Nombre'
            }),
            'last_name': forms.TextInput(attrs={
                'class': 'form-control radius-8',
                'placeholder': 'Apellido'
            }),
            'email': forms.EmailInput(attrs={
                'class': 'form-control radius-8',
                'placeholder': 'correo@email.com'
            }),
            'is_active': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            })
        }

    def clean(self):
        cleaned_data = super().clean()
        pwd = cleaned_data.get('password')
        cpwd = cleaned_data.get('confirm_password')
        is_creation = not getattr(self.instance, 'pk', None)
        # En creación: contraseña obligatoria
        if is_creation:
            if not pwd:
                self.add_error('password', 'La contraseña es obligatoria.')
            if not cpwd:
                self.add_error('confirm_password', 'Debe confirmar la contraseña.')
        # Validaciones comunes cuando hay al menos un campo rellenado
        if pwd or cpwd:
            if not pwd or not cpwd:
                self.add_error('confirm_password', 'Debe confirmar la contraseña.')
            elif pwd != cpwd:
                self.add_error('confirm_password', 'Las contraseñas no coinciden.')
            elif len(pwd) < 8:
                self.add_error('password', 'La contraseña debe tener al menos 8 caracteres.')
        return cleaned_data

class UsuarioPerfilForm(forms.ModelForm):
    """Formulario para el perfil extendido del usuario"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from core.models import Organizacion
        self.fields['organizacion'].queryset = Organizacion.objects.filter(activo=True).order_by('nombre')

    class Meta:
        model = UsuarioPerfilOptimizador
        fields = ['rol', 'telefono', 'organizacion', 'activo']
        widgets = {
            'rol': forms.Select(attrs={
                'class': 'form-control radius-8 form-select'
            }),
            'telefono': forms.TextInput(attrs={
                'class': 'form-control radius-8',
                'placeholder': '+56 9 XXXX XXXX'
            }),
            'organizacion': forms.Select(attrs={
                'class': 'form-control radius-8 form-select'
            }),
            'activo': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            })
        }

    def clean(self):
        cleaned = super().clean()
        ancho = cleaned.get('ancho')
        largo = cleaned.get('largo')
        if ancho and largo and largo > ancho:
            cleaned['ancho'], cleaned['largo'] = largo, ancho
            # Añadimos un error informativo en 'ancho' para notificar el ajuste
            self.add_error('ancho', 'Se ajustó automáticamente para que el Ancho (X) sea la medida mayor.')
        return cleaned