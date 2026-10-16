from django import forms
from django.contrib.auth import authenticate
from django.core.exceptions import ValidationError


class EmailAuthenticationForm(forms.Form):
    """
    Formulario de autenticación corporativa B2B basado en correo electrónico y contraseña.
    """
    email = forms.EmailField(
        label="Correo Corporativo",
        widget=forms.EmailInput(
            attrs={
                'class': (
                    'w-full h-10 px-3 text-sm bg-white border border-zinc-200 rounded-md '
                    'text-zinc-900 placeholder-zinc-400 focus:outline-none focus:border-zinc-900 '
                    'transition-colors font-sans'
                ),
                'placeholder': 'colaborador@empresa.com',
                'autocomplete': 'email',
                'autofocus': True,
            }
        ),
    )
    password = forms.CharField(
        label="Contraseña de Acceso",
        strip=False,
        widget=forms.PasswordInput(
            attrs={
                'class': (
                    'w-full h-10 px-3 text-sm bg-white border border-zinc-200 rounded-md '
                    'text-zinc-900 placeholder-zinc-400 focus:outline-none focus:border-zinc-900 '
                    'transition-colors font-sans'
                ),
                'placeholder': '••••••••••••',
                'autocomplete': 'current-password',
            }
        ),
    )

    def __init__(self, request=None, *args, **kwargs):
        self.request = request
        self.user_cache = None
        super().__init__(*args, **kwargs)

    def clean(self):
        email = self.cleaned_data.get('email')
        password = self.cleaned_data.get('password')

        if email and password:
            email_normalized = email.lower().strip()
            self.user_cache = authenticate(
                self.request,
                username=email_normalized,
                email=email_normalized,
                password=password,
            )
            if self.user_cache is None:
                raise ValidationError(
                    "Credenciales de acceso no válidas. Verifique su correo o contraseña.",
                    code='invalid_login',
                )
            if not self.user_cache.is_active:
                raise ValidationError(
                    "Esta cuenta de usuario ha sido desactivada por el administrador.",
                    code='inactive',
                )
        return self.cleaned_data

    def get_user(self):
        return self.user_cache


class CorporateSignUpForm(forms.Form):
    """
    Formulario de registro autónomo corporativo para evaluadores y nuevas empresas.
    """
    full_name = forms.CharField(
        label="Nombre Completo",
        max_length=255,
        widget=forms.TextInput(
            attrs={
                'class': (
                    'w-full h-10 px-3 text-sm bg-white border border-zinc-200 rounded-md '
                    'text-zinc-900 placeholder-zinc-400 focus:outline-none focus:border-zinc-900 '
                    'transition-colors font-sans'
                ),
                'placeholder': 'ej: Carlos Fonseca Terán',
                'autocomplete': 'name',
                'autofocus': True,
            }
        ),
    )
    email = forms.EmailField(
        label="Correo Corporativo",
        widget=forms.EmailInput(
            attrs={
                'class': (
                    'w-full h-10 px-3 text-sm bg-white border border-zinc-200 rounded-md '
                    'text-zinc-900 placeholder-zinc-400 focus:outline-none focus:border-zinc-900 '
                    'transition-colors font-sans'
                ),
                'placeholder': 'evaluador@empresa.com',
                'autocomplete': 'email',
            }
        ),
    )
    phone = forms.CharField(
        label="Teléfono de Contacto (Opcional)",
        max_length=30,
        required=False,
        widget=forms.TextInput(
            attrs={
                'class': (
                    'w-full h-10 px-3 text-sm bg-white border border-zinc-200 rounded-md '
                    'text-zinc-900 placeholder-zinc-400 focus:outline-none focus:border-zinc-900 '
                    'transition-colors font-sans tabular-nums'
                ),
                'placeholder': '+505 8888-0000',
                'autocomplete': 'tel',
            }
        ),
    )
    password1 = forms.CharField(
        label="Contraseña de Acceso",
        strip=False,
        widget=forms.PasswordInput(
            attrs={
                'class': (
                    'w-full h-10 px-3 text-sm bg-white border border-zinc-200 rounded-md '
                    'text-zinc-900 placeholder-zinc-400 focus:outline-none focus:border-zinc-900 '
                    'transition-colors font-sans'
                ),
                'placeholder': 'Mínimo 8 caracteres',
                'autocomplete': 'new-password',
            }
        ),
    )
    password2 = forms.CharField(
        label="Confirmar Contraseña",
        strip=False,
        widget=forms.PasswordInput(
            attrs={
                'class': (
                    'w-full h-10 px-3 text-sm bg-white border border-zinc-200 rounded-md '
                    'text-zinc-900 placeholder-zinc-400 focus:outline-none focus:border-zinc-900 '
                    'transition-colors font-sans'
                ),
                'placeholder': 'Repita la contraseña',
                'autocomplete': 'new-password',
            }
        ),
    )

    def clean_email(self):
        email = self.cleaned_data.get('email', '').lower().strip()
        from django.contrib.auth import get_user_model
        User = get_user_model()
        if User.objects.filter(email__iexact=email).exists():
            raise ValidationError("Este correo electrónico ya se encuentra registrado.")
        return email

    def clean(self):
        cleaned_data = super().clean()
        p1 = cleaned_data.get('password1')
        p2 = cleaned_data.get('password2')
        if p1 and p2:
            if p1 != p2:
                self.add_error('password2', "Las contraseñas ingresadas no coinciden.")
            elif len(p1) < 8:
                self.add_error('password1', "La contraseña debe contener al menos 8 caracteres.")
        return cleaned_data

    def save(self):
        from django.contrib.auth import get_user_model
        User = get_user_model()
        user = User.objects.create_user(
            email=self.cleaned_data['email'],
            full_name=self.cleaned_data['full_name'].strip(),
            phone=self.cleaned_data.get('phone', '').strip(),
            password=self.cleaned_data['password1'],
        )
        return user
