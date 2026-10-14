from django.contrib.auth import login as auth_login, logout as auth_logout
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_http_methods
from apps.accounts_auth.forms import EmailAuthenticationForm


@require_http_methods(["GET", "POST"])
def login_view(request):
    """
    Vista de Inicio de Sesión Corporativo B2B.
    Autentica al usuario mediante email y contraseña.
    """
    if request.user.is_authenticated:
        if getattr(request, 'organization', None):
            return redirect('tenancy:dashboard')
        return redirect('tenancy:onboarding')

    redirect_to = request.POST.get('next', request.GET.get('next', ''))

    if request.method == "POST":
        form = EmailAuthenticationForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            auth_login(request, user)

            # Validar URL de redirección segura
            if not url_has_allowed_host_and_scheme(
                url=redirect_to,
                allowed_hosts={request.get_host()},
                require_https=request.is_secure(),
            ):
                redirect_to = 'tenancy:dashboard'

            return redirect(redirect_to)
    else:
        form = EmailAuthenticationForm(request)

    return render(request, 'accounts_auth/login.html', {
        'form': form,
        'next': redirect_to,
    })


from django.views import View
from apps.accounts_auth.forms import EmailAuthenticationForm, CorporateSignUpForm


class CorporateRegisterView(View):
    """
    Registro autónomo de nuevos evaluadores y directores de empresa.
    Autentica al usuario inmediatamente tras el registro y lo transfiere
    al Onboarding Wizard para inicializar su organización.
    """
    template_name = 'accounts_auth/register.html'

    def get(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            if getattr(request, 'organization', None):
                return redirect('tenancy:dashboard')
            return redirect('tenancy:onboarding')
        form = CorporateSignUpForm()
        return render(request, self.template_name, {'form': form})

    def post(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return redirect('tenancy:onboarding')
        form = CorporateSignUpForm(request.POST)
        if form.is_valid():
            user = form.save()
            auth_login(request, user)
            return redirect('tenancy:onboarding')
        return render(request, self.template_name, {'form': form}, status=422)


@require_http_methods(["GET", "POST"])
def logout_view(request):
    """
    Cierra la sesión activa del usuario y limpia el identificador de tenant en sesión.
    """
    request.session.pop('active_org_id', None)
    auth_logout(request)
    return redirect('accounts_auth:login')
