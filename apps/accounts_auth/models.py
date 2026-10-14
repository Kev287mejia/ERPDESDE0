import uuid
from django.contrib.auth.models import AbstractUser
from django.db import models
from apps.accounts_auth.managers import UserManager


class User(AbstractUser):
    """
    Modelo de Usuario Customizado para el ecosistema ERP SAS.
    - Utiliza 'email' como USERNAME_FIELD único y sin distinción de mayúsculas/minúsculas.
    - Suprime 'username', 'first_name' y 'last_name' en favor de 'full_name' centralizado.
    - Implementa UUIDv4 como llave primaria universal.
    """
    username = None
    first_name = None
    last_name = None

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        help_text="Identificador único universal (UUIDv4)"
    )
    email = models.EmailField(
        unique=True,
        db_index=True,
        verbose_name="Correo Electrónico",
        help_text="Correo electrónico corporativo utilizado para iniciar sesión"
    )
    full_name = models.CharField(
        max_length=255,
        verbose_name="Nombre Completo",
        help_text="Nombres y apellidos completos del colaborador o usuario"
    )
    personal_id_number = models.CharField(
        max_length=50,
        blank=True,
        verbose_name="Documento de Identidad Personal",
        help_text="Número de cédula de identidad, DUI, DPI o pasaporte según el país"
    )
    phone = models.CharField(
        max_length=30,
        blank=True,
        verbose_name="Teléfono de Contacto",
        help_text="Número de teléfono móvil o corporativo"
    )
    avatar = models.ImageField(
        upload_to="avatars/%Y/%m/",
        blank=True,
        null=True,
        verbose_name="Foto de Perfil / Avatar",
        help_text="Fotografía de perfil para avatares y credenciales"
    )

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["full_name"]

    class Meta:
        verbose_name = "Usuario"
        verbose_name_plural = "Usuarios"
        ordering = ["email"]

    def __str__(self) -> str:
        return f"{self.full_name} <{self.email}>" if self.full_name else self.email

    def get_full_name(self) -> str:
        return self.full_name or self.email

    def get_short_name(self) -> str:
        if self.full_name:
            return self.full_name.split()[0]
        return self.email.split("@")[0]
