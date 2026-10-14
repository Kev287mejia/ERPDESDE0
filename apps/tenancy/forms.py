from django import forms
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.utils.text import slugify

from apps.core.models import CountryConfig
from apps.tenancy.constants import AVAILABLE_MODULES, DEFAULT_ENABLED_MODULES, MODULE_CHOICES
from apps.tenancy.models import (
    BloodType,
    ContractType,
    Department,
    Organization,
    OrganizationMembership,
    RoleLevel,
)

User = get_user_model()


class OrganizationOnboardingForm(forms.Form):
    """
    Formulario técnico para la inicialización y alta de una Organización (Tenant).
    Garantiza validación estricta de jurisdicción activa, identificadores tributarios
    y configuración modular adaptativa.
    """
    country_code = forms.CharField(
        max_length=2,
        initial='NI',
        widget=forms.HiddenInput(),
    )
    name = forms.CharField(
        label="Nombre Comercial",
        max_length=150,
        widget=forms.TextInput(
            attrs={
                'class': (
                    'w-full h-9 px-3 text-[13px] bg-white border border-zinc-200 rounded-[4px] '
                    'text-zinc-900 placeholder-zinc-400 focus:outline-none focus:border-zinc-900 '
                    'focus:ring-1 focus:ring-zinc-900 transition-colors font-sans'
                ),
                'placeholder': 'ej: SIE Nicaragua',
                'autocomplete': 'organization',
            }
        ),
    )
    legal_name = forms.CharField(
        label="Razón Social",
        max_length=200,
        widget=forms.TextInput(
            attrs={
                'class': (
                    'w-full h-9 px-3 text-[13px] bg-white border border-zinc-200 rounded-[4px] '
                    'text-zinc-900 placeholder-zinc-400 focus:outline-none focus:border-zinc-900 '
                    'focus:ring-1 focus:ring-zinc-900 transition-colors font-sans'
                ),
                'placeholder': 'ej: Soluciones de Ingeniería Eléctrica S.A.',
                'autocomplete': 'organization-title',
            }
        ),
    )
    tax_id = forms.CharField(
        label="RUC / Identificador Fiscal",
        max_length=50,
        widget=forms.TextInput(
            attrs={
                'class': (
                    'w-full h-9 px-3 text-[13px] bg-white border border-zinc-200 rounded-[4px] '
                    'text-zinc-900 placeholder-zinc-400 focus:outline-none focus:border-zinc-900 '
                    'focus:ring-1 focus:ring-zinc-900 transition-colors font-mono tabular-nums uppercase'
                ),
                'placeholder': 'ej: J0310000123456 o 001-290590-0001A',
                'autocomplete': 'off',
            }
        ),
    )
    currency = forms.ChoiceField(
        label="Moneda Base Operativa",
        choices=Organization.Currency.choices,
        initial=Organization.Currency.NIO,
        widget=forms.Select(
            attrs={
                'class': (
                    'w-full h-9 px-3 text-[13px] bg-white border border-zinc-200 rounded-[4px] '
                    'text-zinc-900 focus:outline-none focus:border-zinc-900 focus:ring-1 '
                    'focus:ring-zinc-900 transition-colors font-sans'
                )
            }
        ),
    )
    tax_regime = forms.ChoiceField(
        label="Régimen Fiscal DGI",
        choices=Organization.TaxRegime.choices,
        initial=Organization.TaxRegime.GENERAL,
        widget=forms.Select(
            attrs={
                'class': (
                    'w-full h-9 px-3 text-[13px] bg-white border border-zinc-200 rounded-[4px] '
                    'text-zinc-900 focus:outline-none focus:border-zinc-900 focus:ring-1 '
                    'focus:ring-zinc-900 transition-colors font-sans'
                )
            }
        ),
    )
    industry = forms.ChoiceField(
        label="Giro o Rubro Comercial",
        choices=Organization.Industry.choices,
        initial=Organization.Industry.SERVICES,
        widget=forms.Select(
            attrs={
                'class': (
                    'w-full h-9 px-3 text-[13px] bg-white border border-zinc-200 rounded-[4px] '
                    'text-zinc-900 focus:outline-none focus:border-zinc-900 focus:ring-1 '
                    'focus:ring-zinc-900 transition-colors font-sans'
                )
            }
        ),
    )
    accounting_template = forms.ChoiceField(
        label="Plantilla Contable Inicial",
        choices=Organization.AccountingTemplate.choices,
        initial=Organization.AccountingTemplate.NIIF_PYMES,
        widget=forms.Select(
            attrs={
                'class': (
                    'w-full h-9 px-3 text-[13px] bg-white border border-zinc-200 rounded-[4px] '
                    'text-zinc-900 focus:outline-none focus:border-zinc-900 focus:ring-1 '
                    'focus:ring-zinc-900 transition-colors font-sans'
                )
            }
        ),
    )
    enabled_modules = forms.MultipleChoiceField(
        label="Módulos Habilitados",
        choices=AVAILABLE_MODULES,
        initial=DEFAULT_ENABLED_MODULES,
        widget=forms.CheckboxSelectMultiple(),
    )

    def clean_country_code(self):
        code = self.cleaned_data.get('country_code', '').upper().strip()
        country = CountryConfig.objects.filter(code=code).first()
        if not country:
            raise ValidationError("La jurisdicción fiscal especificada no existe en el sistema.")
        if not country.is_active:
            raise ValidationError(
                f"La jurisdicción de {country.name} ({country.code}) está en estado PRÓXIMAMENTE. "
                "Actualmente las operaciones están restringidas exclusivamente a Nicaragua (NI)."
            )
        self.cleaned_country = country
        return code

    def clean_tax_id(self):
        tax_id = self.cleaned_data.get('tax_id', '').upper().strip()
        country = getattr(self, 'cleaned_country', None)
        if not country:
            code = self.cleaned_data.get('country_code', 'NI').upper().strip()
            country = CountryConfig.objects.filter(code=code).first()

        if country:
            if not country.validate_tax_id(tax_id):
                raise ValidationError(
                    f"El formato del {country.tax_id_label} no es válido para {country.name}. "
                    "Formato requerido: 14 dígitos o cédula con guiones (ej. 001-290590-0001A)."
                )
            if Organization.objects.filter(country=country, tax_id=tax_id).exists():
                raise ValidationError(
                    f"Ya existe una organización registrada con este {country.tax_id_label} en {country.name}."
                )

        return tax_id

    def generate_unique_slug(self, name, tax_id):
        base_slug = slugify(name)
        if not base_slug:
            base_slug = f"tenant-{tax_id.lower()[:8]}"
        slug = base_slug
        counter = 1
        while Organization.objects.filter(slug=slug).exists():
            slug = f"{base_slug}-{counter}"
            counter += 1
        return slug


class TeamCreateMemberForm(forms.Form):
    """
    Formulario para el alta y enrolamiento de colaboradores en la organización.
    Aplica regla anti-inversión de mando (un usuario no puede asignar un rol superior al propio)
    y valida el documento de identidad contra el regex nacional del país del Tenant.
    """
    full_name = forms.CharField(
        label="Nombre Completo",
        max_length=255,
        widget=forms.TextInput(
            attrs={
                'class': 'w-full h-9 px-3 text-[13px] bg-white border border-zinc-200 rounded-[4px] text-zinc-900 placeholder-zinc-400 focus:outline-none focus:border-zinc-900 focus:ring-1 focus:ring-zinc-900 transition-colors font-sans',
                'placeholder': 'ej: Carlos Morales Hernández',
                'required': True,
            }
        ),
    )
    email = forms.EmailField(
        label="Correo Corporativo",
        widget=forms.EmailInput(
            attrs={
                'class': 'w-full h-9 px-3 text-[13px] bg-white border border-zinc-200 rounded-[4px] text-zinc-900 placeholder-zinc-400 focus:outline-none focus:border-zinc-900 focus:ring-1 focus:ring-zinc-900 transition-colors font-mono',
                'placeholder': 'colaborador@empresa.com',
                'required': True,
            }
        ),
    )
    personal_id_number = forms.CharField(
        label="Documento de Identidad (Cédula / DNI)",
        max_length=50,
        widget=forms.TextInput(
            attrs={
                'class': 'w-full h-9 px-3 text-[13px] bg-white border border-zinc-200 rounded-[4px] text-zinc-900 placeholder-zinc-400 focus:outline-none focus:border-zinc-900 focus:ring-1 focus:ring-zinc-900 transition-colors font-mono uppercase tabular-nums',
                'placeholder': 'ej: 001-150897-0000A',
                'required': True,
            }
        ),
    )
    phone = forms.CharField(
        label="Teléfono Móvil",
        max_length=30,
        required=False,
        widget=forms.TextInput(
            attrs={
                'class': 'w-full h-9 px-3 text-[13px] bg-white border border-zinc-200 rounded-[4px] text-zinc-900 placeholder-zinc-400 focus:outline-none focus:border-zinc-900 focus:ring-1 focus:ring-zinc-900 transition-colors font-mono tabular-nums',
                'placeholder': '+505 8888-0000',
            }
        ),
    )
    job_title = forms.CharField(
        label="Cargo Operativo",
        max_length=120,
        required=False,
        widget=forms.TextInput(
            attrs={
                'class': 'w-full h-9 px-3 text-[13px] bg-white border border-zinc-200 rounded-[4px] text-zinc-900 placeholder-zinc-400 focus:outline-none focus:border-zinc-900 focus:ring-1 focus:ring-zinc-900 transition-colors font-sans',
                'placeholder': 'ej: Ingeniero Residente de Subestaciones',
            }
        ),
    )
    role_level = forms.TypedChoiceField(
        label="Nivel Jerárquico RBAC",
        choices=RoleLevel.choices,
        coerce=int,
        widget=forms.Select(
            attrs={
                'class': 'w-full h-9 px-3 text-[13px] bg-white border border-zinc-200 rounded-[4px] text-zinc-900 focus:outline-none focus:border-zinc-900 focus:ring-1 focus:ring-zinc-900 transition-colors font-mono',
            }
        ),
    )
    password = forms.CharField(
        label="Contraseña Provisional",
        required=False,
        widget=forms.PasswordInput(
            attrs={
                'class': 'w-full h-9 px-3 text-[13px] bg-white border border-zinc-200 rounded-[4px] text-zinc-900 placeholder-zinc-400 focus:outline-none focus:border-zinc-900 focus:ring-1 focus:ring-zinc-900 transition-colors font-mono',
                'placeholder': 'Dejar en blanco para autogenerar',
            }
        ),
        help_text="Opcional. Si se deja en blanco se generará una contraseña segura por defecto.",
    )

    # --- FICHA LABORAL & CONTRACTUAL ---
    department = forms.ChoiceField(
        label="Departamento / Área Operativa",
        choices=Department.choices,
        initial=Department.OPERATIONS,
        required=False,
        widget=forms.Select(
            attrs={
                'class': 'w-full h-9 px-3 text-[13px] bg-white border border-zinc-200 rounded-[4px] text-zinc-900 focus:outline-none focus:border-zinc-900 focus:ring-1 focus:ring-zinc-900 transition-colors font-sans',
            }
        ),
    )
    contract_type = forms.ChoiceField(
        label="Modalidad Contractual",
        choices=ContractType.choices,
        initial=ContractType.PERMANENT,
        required=False,
        widget=forms.Select(
            attrs={
                'class': 'w-full h-9 px-3 text-[13px] bg-white border border-zinc-200 rounded-[4px] text-zinc-900 focus:outline-none focus:border-zinc-900 focus:ring-1 focus:ring-zinc-900 transition-colors font-sans',
            }
        ),
    )
    social_security_number = forms.CharField(
        label="Nº Seguro Social (INSS)",
        max_length=50,
        required=False,
        widget=forms.TextInput(
            attrs={
                'class': 'w-full h-9 px-3 text-[13px] bg-white border border-zinc-200 rounded-[4px] text-zinc-900 placeholder-zinc-400 focus:outline-none focus:border-zinc-900 focus:ring-1 focus:ring-zinc-900 transition-colors font-mono tabular-nums',
                'placeholder': 'ej: 1234567-8',
            }
        ),
    )
    hire_date = forms.DateField(
        label="Fecha de Ingreso Laboral",
        required=False,
        widget=forms.DateInput(
            attrs={
                'type': 'date',
                'class': 'w-full h-9 px-3 text-[13px] bg-white border border-zinc-200 rounded-[4px] text-zinc-900 focus:outline-none focus:border-zinc-900 focus:ring-1 focus:ring-zinc-900 transition-colors font-mono tabular-nums',
            }
        ),
    )
    work_location = forms.CharField(
        label="Base Operativa / Frente Asignado",
        max_length=120,
        required=False,
        widget=forms.TextInput(
            attrs={
                'class': 'w-full h-9 px-3 text-[13px] bg-white border border-zinc-200 rounded-[4px] text-zinc-900 placeholder-zinc-400 focus:outline-none focus:border-zinc-900 focus:ring-1 focus:ring-zinc-900 transition-colors font-sans',
                'placeholder': 'ej: Sede Central / Frente Managua Norte',
            }
        ),
    )

    # --- FICHA SST & SALUD OCUPACIONAL ---
    blood_type = forms.ChoiceField(
        label="Grupo Sanguíneo",
        choices=BloodType.choices,
        initial=BloodType.UNKNOWN,
        required=False,
        widget=forms.Select(
            attrs={
                'class': 'w-full h-9 px-3 text-[13px] bg-white border border-zinc-200 rounded-[4px] text-zinc-900 focus:outline-none focus:border-zinc-900 focus:ring-1 focus:ring-zinc-900 transition-colors font-mono',
            }
        ),
    )
    emergency_contact_name = forms.CharField(
        label="Contacto de Emergencia",
        max_length=150,
        required=False,
        widget=forms.TextInput(
            attrs={
                'class': 'w-full h-9 px-3 text-[13px] bg-white border border-zinc-200 rounded-[4px] text-zinc-900 placeholder-zinc-400 focus:outline-none focus:border-zinc-900 focus:ring-1 focus:ring-zinc-900 transition-colors font-sans',
                'placeholder': 'ej: María Elena Morales (Cónyuge)',
            }
        ),
    )
    emergency_contact_phone = forms.CharField(
        label="Teléfono de Emergencia",
        max_length=30,
        required=False,
        widget=forms.TextInput(
            attrs={
                'class': 'w-full h-9 px-3 text-[13px] bg-white border border-zinc-200 rounded-[4px] text-zinc-900 placeholder-zinc-400 focus:outline-none focus:border-zinc-900 focus:ring-1 focus:ring-zinc-900 transition-colors font-mono tabular-nums',
                'placeholder': '+505 8765-4321',
            }
        ),
    )

    def __init__(self, organization=None, current_user_role_level=100, *args, **kwargs):
        self.organization = organization
        self.current_user_role_level = current_user_role_level
        super().__init__(*args, **kwargs)

        # Regla Anti-Inversión: Solo ofrecer roles menores o iguales al del usuario actual
        allowed_choices = [
            (val, label) for val, label in RoleLevel.choices
            if val <= self.current_user_role_level
        ]
        self.fields['role_level'].choices = allowed_choices

    def clean_email(self):
        email = self.cleaned_data.get('email', '').lower().strip()
        if self.organization:
            existing_user = User.objects.filter(email=email).first()
            if existing_user and OrganizationMembership.objects.filter(
                user=existing_user,
                organization=self.organization,
            ).exists():
                raise ValidationError("Este colaborador ya cuenta con una membresía activa en esta organización.")
        return email

    def clean_personal_id_number(self):
        personal_id = self.cleaned_data.get('personal_id_number', '').upper().strip()
        if self.organization and self.organization.country:
            country = self.organization.country
            if not country.validate_personal_id(personal_id):
                raise ValidationError(
                    f"El formato del {country.personal_id_label} no es válido para {country.name}. "
                    "Formato oficial nicaragüense requerido: 001-150897-0000A."
                )
        return personal_id

    def clean_role_level(self):
        role_level = self.cleaned_data.get('role_level')
        # Regla Anti-Inversión en Servidor
        if role_level > self.current_user_role_level:
            raise ValidationError(
                f"Violación de jerarquía: No puede asignar un nivel de autoridad ({role_level}) "
                f"superior al suyo propio ({self.current_user_role_level})."
            )
        return role_level


class MemberRoleUpdateForm(forms.ModelForm):
    """
    Formulario para actualizar el rol operativo, cargo o estado de una membresía existente.
    Protege contra degradación del último Owner/Admin.
    """
    role_level = forms.TypedChoiceField(
        label="Nivel Jerárquico",
        choices=RoleLevel.choices,
        coerce=int,
        widget=forms.Select(
            attrs={'class': 'h-8 px-2 text-xs font-mono bg-white border border-zinc-200 rounded-[4px] text-zinc-900 focus:outline-none focus:border-zinc-900 focus:ring-1 focus:ring-zinc-900'}
        )
    )

    class Meta:
        model = OrganizationMembership
        fields = ['role_level', 'job_title', 'is_active']
        widgets = {
            'job_title': forms.TextInput(attrs={'class': 'h-8 px-2 text-xs bg-white border border-zinc-200 rounded-[4px] text-zinc-900 focus:outline-none focus:border-zinc-900 focus:ring-1 focus:ring-zinc-900 font-sans'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'w-4 h-4 text-zinc-900 rounded-[3px] border-zinc-300 focus:ring-zinc-900'}),
        }

    def __init__(self, current_user_role_level=100, *args, **kwargs):
        self.current_user_role_level = current_user_role_level
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned_data = super().clean()
        new_role_level = cleaned_data.get('role_level')
        is_active = cleaned_data.get('is_active')

        # Regla Anti-Inversión: No puede asignar un rol superior al suyo propio
        if new_role_level and new_role_level > self.current_user_role_level:
            raise ValidationError("No tiene autorización para promover a un nivel superior al suyo.")

        # Protección del único Owner/Admin
        if self.instance.role_level == RoleLevel.OWNER_ADMIN:
            if new_role_level != RoleLevel.OWNER_ADMIN or not is_active:
                active_owners = OrganizationMembership.objects.filter(
                    organization=self.instance.organization,
                    role_level=RoleLevel.OWNER_ADMIN,
                    is_active=True
                ).exclude(pk=self.instance.pk).count()

                if active_owners == 0:
                    raise ValidationError(
                        "No es posible degradar o desactivar al único Administrador General (Owner) activo del Tenant."
                    )

        return cleaned_data
