"""
Pruebas de interfaz comunes a los mantenedores (A2 y UX-04/UX-05): navegación y aria-current,
distintivo de contexto con texto e ícono, estados de carga, vacío y error, campos obligatorios
y maquetas identificadas como datos de demostración.
"""

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import RequestFactory, TestCase
from django.urls import reverse
from django.views.defaults import server_error

from accounts.models import Delegation, Official, Role
from configuration.models import AttentionType, SubattentionType

User = get_user_model()
PASSWORD = "Clave-Interfaz-123"

LIST_PAGES = {
    "delegation_list": "Delegaciones",
    "role_list": "Roles",
    "user_maintainer": "Usuarios",
    "official_maintainer": "Funcionarios",
    "item_maintainer": "Ítems y metas",
    "attention_type_maintainer": "Tipo de Atención",
    "subattention_type_maintainer": "Sub Atención",
}
FORM_PAGES = (
    "delegation_create",
    "role_create",
    "user_create",
    "official_create",
    "item_create",
    "attention_type_create",
    "subattention_type_create",
    "attention_entry",
)
MOCKUP_PAGES = (
    "position_maintainer",
    "area_maintainer",
    "group_maintainer",
    "period_maintainer",
    "activity_maintainer",
)


class MaintainerLayoutTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser("interfaz", "interfaz@example.test", PASSWORD)
        cls.delegation = Delegation.objects.create(delegation_name="Zona Interfaz", address="Calle 1", commune="La Serena")
        Official.objects.create(
            user=cls.admin,
            full_name="Administración Interfaz",
            national_id="RUT-INTERFAZ",
            email="interfaz@example.test",
            delegation=cls.delegation,
        )

    def setUp(self):
        self.client.force_login(self.admin)

    def test_every_maintainer_marks_its_own_sidebar_link_as_current(self):
        for route_name, label in LIST_PAGES.items():
            with self.subTest(route=route_name):
                response = self.client.get(reverse(route_name))

                self.assertContains(
                    response,
                    f'<a class="maintainer-sidebar-link is-active" href="{reverse(route_name)}" aria-current="page">{label}</a>',
                    html=True,
                )
                self.assertContains(response, "Delegación activa")

    def test_forms_mark_required_fields_and_show_loading_while_saving(self):
        for route_name in FORM_PAGES:
            with self.subTest(route=route_name):
                response = self.client.get(
                    reverse(route_name), HTTP_X_MODAL_REQUEST="true"
                )

                self.assertContains(response, "Los campos marcados con * son obligatorios.")
                self.assertContains(response, 'data-loading-text="Guardando…"')
                self.assertContains(response, "Cancelar")

    def test_lists_show_a_loading_state_and_mark_the_current_page(self):
        for index in range(11):
            Delegation.objects.create(delegation_name=f"Zona Página {index:02d}", address="Calle", commune="La Serena")
            AttentionType.objects.create(name=f"Tipo Página {index:02d}")

        for route_name in ("delegation_list", "attention_type_maintainer"):
            with self.subTest(route=route_name):
                response = self.client.get(reverse(route_name))

                self.assertContains(response, 'data-loading-target="#maintainer-table-wrap"')
                self.assertContains(response, 'data-loading-text="Buscando…"')
                self.assertContains(response, '<span class="page-link" aria-current="page">1</span>', html=True)
                self.assertContains(response, "Mostrando 1 a 10 de")

    def test_catalogs_distinguish_empty_lists_from_searches_without_matches(self):
        cases = (
            ("attention_type_maintainer", "Aún no hay tipos de atención registrados.",
             "No hay tipos de atención que coincidan con la búsqueda o el filtro aplicado."),
            ("subattention_type_maintainer", "Aún no hay subatenciones registradas.",
             "No hay subatenciones que coincidan con la búsqueda o el filtro aplicado."),
        )
        for route_name, empty, no_matches in cases:
            with self.subTest(route=route_name):
                self.assertContains(self.client.get(reverse(route_name)), empty)
                self.assertContains(self.client.get(reverse(route_name), {"q": "inexistente"}), no_matches)

    def test_mockups_are_clearly_identified_as_demo_data(self):
        for route_name in MOCKUP_PAGES:
            with self.subTest(route=route_name):
                response = self.client.get(reverse(route_name))

                self.assertContains(response, "<strong>Datos de demostración.</strong>", html=True)
                self.assertContains(response, '<span class="maintainer-demo-badge">Demostración</span>', html=True)
                self.assertContains(response, "(datos de demostración) · SGR")

    def test_real_maintainers_are_not_labelled_as_demo_data(self):
        for route_name in LIST_PAGES:
            with self.subTest(route=route_name):
                self.assertNotContains(self.client.get(reverse(route_name)), "maintainer-demo-banner")

    def test_catalog_state_messages_use_the_right_gender(self):
        attention_type = AttentionType.objects.create(name="Social")
        subattention = SubattentionType.objects.create(name="Orientación", attention_type=attention_type)

        response = self.client.post(reverse("subattention_type_deactivate", args=[subattention.pk]), follow=True)

        self.assertContains(response, "La subatención Orientación fue desactivada correctamente.")


class SidebarPermissionTests(TestCase):
    def test_sidebar_only_lists_screens_the_profile_can_open(self):
        user = User.objects.create_user("solo.items", "solo.items@example.test", PASSWORD)
        Official.objects.create(user=user, full_name="Solo Ítems", national_id="RUT-SOLO-ITEMS", email="solo.items@example.test")
        user.user_permissions.add(Permission.objects.get(content_type__app_label="configuration", codename="view_item"))
        self.client.force_login(user)

        response = self.client.get(reverse("item_maintainer"))

        self.assertContains(response, f'href="{reverse("item_maintainer")}" aria-current="page"')
        self.assertNotContains(response, f'class="maintainer-sidebar-link" href="{reverse("delegation_list")}"')
        self.assertNotContains(response, "Maquetas · datos de demostración")


class HeaderContextBadgeTests(TestCase):
    def test_header_shows_user_role_and_delegation_with_text_and_icon(self):
        delegation = Delegation.objects.create(delegation_name="Centro", address="Calle 1", commune="La Serena")
        user = User.objects.create_user("badge.user", "badge.user@example.test", PASSWORD)
        official = Official.objects.create(
            user=user, full_name="Ana Distintivo", national_id="RUT-BADGE", email="badge.user@example.test",
            delegation=delegation,
        )
        official.roles.add(Role.objects.create(role_name="Operador"), Role.objects.create(role_name="Histórico", is_active=False))
        self.client.force_login(user)

        response = self.client.get(reverse("home"))
        header = response.content.decode().split('aria-label="Usuario y delegación activa"', 1)[1].split("</section>", 1)[0]

        for label in ("Usuario", "Rol", "Delegación activa"):
            self.assertIn(f'<span class="municipal-context-label">{label}</span>', header)
        self.assertEqual(header.count('<span class="municipal-context-icon" aria-hidden="true">'), 3)
        self.assertEqual(header.count("<svg"), 3)
        self.assertIn("Ana Distintivo", header)
        self.assertIn("Operador", header)
        self.assertIn("Histórico (inactivo)", header)
        self.assertIn(f"{delegation.code} · Centro", header)


class ErrorPageTests(TestCase):
    def test_not_found_uses_the_institutional_template(self):
        self.client.force_login(User.objects.create_superuser("errores", "errores@example.test", PASSWORD))

        response = self.client.get("/no-existe/")

        self.assertEqual(response.status_code, 404)
        self.assertTemplateUsed(response, "404.html")
        self.assertContains(response, "No encontramos lo que buscas", status_code=404)

    def test_server_error_page_renders_without_request_context(self):
        response = server_error(RequestFactory().get("/"))

        self.assertEqual(response.status_code, 500)
        self.assertIn("No pudimos completar la operación", response.content.decode())
