from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

User = get_user_model()


class CorporateRegisterTestCase(TestCase):
    """
    Suite de pruebas para el flujo de registro autónomo corporativo B2B.
    """

    def setUp(self):
        self.client = Client()

    def test_register_get_renders_form(self):
        """Verifica que GET /auth/register/ retorne 200 y presente el formulario."""
        response = self.client.get(reverse('accounts_auth:register'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Crear Cuenta Corporativa")
        self.assertContains(response, "name=\"email\"")
        self.assertContains(response, "name=\"password1\"")

    def test_register_post_creates_user_and_redirects_to_onboarding(self):
        """Verifica que el POST válido cree al usuario, lo autentique y lo envíe a onboarding."""
        payload = {
            'full_name': 'Ing. Roberto Somoza',
            'email': 'rsomoza@corporativo.ni',
            'phone': '+505 8888-1111',
            'password1': 'ContrasenaSegura2026!',
            'password2': 'ContrasenaSegura2026!',
        }
        response = self.client.post(reverse('accounts_auth:register'), payload, follow=False)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('tenancy:onboarding'))

        user = User.objects.filter(email='rsomoza@corporativo.ni').first()
        self.assertIsNotNone(user)
        self.assertEqual(user.full_name, 'Ing. Roberto Somoza')
        self.assertTrue(user.check_password('ContrasenaSegura2026!'))

    def test_register_duplicate_email_rejected(self):
        """Verifica el rechazo estricto ante correos ya registrados."""
        User.objects.create_user(
            email='existente@corporativo.ni',
            full_name='Usuario Existente',
            password='Password123!',
        )
        payload = {
            'full_name': 'Otro Usuario',
            'email': 'existente@corporativo.ni',
            'password1': 'ContrasenaSegura2026!',
            'password2': 'ContrasenaSegura2026!',
        }
        response = self.client.post(reverse('accounts_auth:register'), payload)
        self.assertEqual(response.status_code, 422)
        self.assertContains(response, "Este correo electrónico ya se encuentra registrado.", status_code=422)

    def test_reciprocal_links_between_login_and_register(self):
        """Verifica que login tenga enlace a registro y registro a login."""
        login_res = self.client.get(reverse('accounts_auth:login'))
        self.assertContains(login_res, reverse('accounts_auth:register'))

        register_res = self.client.get(reverse('accounts_auth:register'))
        self.assertContains(register_res, reverse('accounts_auth:login'))


class QuickSandboxLoginTestCase(TestCase):
    """
    Suite de pruebas para el acceso instantáneo de 1-Clic al Sandbox Demo.
    """

    def setUp(self):
        self.client = Client()

    def test_quick_sandbox_login_post_authenticates_and_redirects(self):
        """Verifica que POST a sandbox_login cree o autentique al usuario demo y redirija al dashboard."""
        response = self.client.post(reverse('accounts_auth:sandbox_login'))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('tenancy:dashboard'))

        # Comprueba que el usuario evaluador existe y la sesión está activa
        user = User.objects.filter(email='evaluador@eternallabs.ni').first()
        self.assertIsNotNone(user)
        self.assertEqual(self.client.session.get('_auth_user_id'), str(user.pk))

        # Comprueba que la organización de IMESA fue creada y seteada en la sesión
        from apps.tenancy.models import Organization
        org = Organization.objects.filter(slug='imesa-ingenieria').first()
        self.assertIsNotNone(org)
        self.assertEqual(self.client.session.get('active_org_id'), str(org.id))

