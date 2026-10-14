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
                    'w-full h-9 px-3 text-[13px] bg-white border border-zinc-200 rounded-[4px] '
                    'text-zinc-900 placeholder-zinc-400 focus:outline-none focus:border-zinc-900 '
                    'focus:ring-1 focus:ring-zinc-900 transition-colors font-mono'
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
                    'w-full h-9 px-3 text-[13px] bg-white border border-zinc-200 rounded-[4px] '
                    'text-zinc-900 placeholder-zinc-400 focus:outline-none focus:border-zinc-900 '
                    'focus:ring-1 focus:ring-zinc-900 transition-colors font-mono'
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
