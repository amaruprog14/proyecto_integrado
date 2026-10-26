"""
Fase 10: búsqueda en tiempo real en los seis mantenedores y aviso de cambios sin guardar al
cambiar la delegación activa. El comportamiento del navegador (espera de 400 ms, cancelación,
reemplazo de bloques y SweetAlert2) se prueba a mano; aquí se comprueba lo que el servidor
entrega: scripts, atributos data-*, filtros conservados en la URL y en la exportación.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from accounts.models import Delegation, Official, Role
from configuration.models import AttentionType, Item, SubattentionType

User = get_user_model()
PASSWORD = "Clave-Tiempo-Real-123"

# (listado, exportación, valor del filtro de estado "activo")
MAINTAINERS = (
    ("delegation_list", "delegation_export", "ACTIVE"),
    ("role_list", "role_export", "ACTIVE"),
    ("user_maintainer", "user_export", "ACTIVE"),
    ("item_maintainer", "item_export", "ACTIVE"),
    ("attention_type_maintainer", "attention_type_export", "1"),
    ("subattention_type_maintainer", "subattention_type_export", "1"),
)


class LiveSearchMarkupTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser("tiempo.real", "tiempo.real@example.test", PASSWORD)
        attention_type = AttentionType.objects.create(name="Tipo Base de Subatenciones")
        for index in range(12):
            Delegation.objects.create(delegation_name=f"Buscable {index:02d}", address="Calle", commune="La Serena")
            Role.objects.create(role_name=f"Buscable {index:02d}")
            User.objects.create_user(f"buscable{index:02d}", f"buscable{index:02d}@example.test", PASSWORD)
            Item.objects.create(item_name=f"Buscable {index:02d}")
            AttentionType.objects.create(name=f"Buscable {index:02d}")
            SubattentionType.objects.create(name=f"Buscable {index:02d}", attention_type=attention_type)

    def setUp(self):
        self.client.force_login(self.admin)

    def test_lists_declare_the_live_search_regions_and_scripts(self):
        for list_route, export_route, _ in MAINTAINERS:
            with self.subTest(route=list_route):
                response = self.client.get(reverse(list_route))

                self.assertContains(response, "data-live-search>")
                self.assertContains(response, 'data-live-region="table"')
                self.assertContains(response, 'data-live-region="footer"')
                self.assertContains(response, 'data-live-status role="status"')
                self.assertContains(response, f'data-export-base="{reverse(export_route)}"')
                self.assertContains(response, "js/maintainer-states.js")
                self.assertContains(response, "js/maintainer-crud.js")
                # Sin JavaScript sigue habiendo un formulario GET con su botón Buscar y el filtro.
                self.assertContains(response, 'method="get"')
                self.assertContains(response, 'type="submit" data-loading-text="Buscando…">Buscar</button>')
                self.assertContains(response, 'name="status" data-swal-autosubmit')

    def test_search_in_the_url_keeps_filters_in_pages_and_export(self):
        for list_route, export_route, active in MAINTAINERS:
            with self.subTest(route=list_route):
                response = self.client.get(reverse(list_route), {"q": "BUSCABLE", "status": active})

                self.assertEqual(response.context["total"], 12)
                self.assertEqual(response.context["page_obj"].number, 1)
                self.assertContains(response, 'value="BUSCABLE"')
                content = response.content.decode()
                self.assertIn("q=BUSCABLE", content.split('data-live-region="footer"', 1)[1])
                self.assertIn(f"status={active}", content.split('data-live-region="footer"', 1)[1])
                self.assertRegex(content, rf'href="{reverse(export_route)}\?[^"]*q=BUSCABLE[^"]*status={active}')

                second = self.client.get(reverse(list_route), {"q": "BUSCABLE", "status": active, "page": 2})
                self.assertEqual(second.context["page_obj"].number, 2)
                self.assertEqual(len(second.context["page_obj"].object_list), 2)

    def test_live_requests_return_the_list_without_consuming_pending_messages(self):
        delegation = Delegation.objects.get(delegation_name="Buscable 00")
        self.client.post(reverse("delegation_deactivate", args=[delegation.pk]))

        live = self.client.get(reverse("delegation_list"), {"q": "buscable"}, HTTP_X_LIVE_SEARCH="1")

        self.assertContains(live, 'data-live-region="table"')
        self.assertNotContains(live, "fue desactivada correctamente")
        self.assertContains(self.client.get(reverse("delegation_list")), "fue desactivada correctamente")


class DelegationSwitchWarningTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.first = Delegation.objects.create(delegation_name="Primera", address="Calle 1", commune="La Serena")
        cls.second = Delegation.objects.create(delegation_name="Segunda", address="Calle 2", commune="La Serena")

    def make_user(self, username, *delegations):
        user = User.objects.create_user(username, f"{username}@example.test", PASSWORD)
        official = Official.objects.create(
            user=user, full_name=username.title(), national_id=f"RUT-{username[:12]}",
            email=f"{username}@example.test", delegation=delegations[0],
        )
        official.authorized_delegations.set(delegations[1:])
        return user

    def test_selector_with_several_delegations_loads_the_unsaved_changes_warning(self):
        self.client.force_login(self.make_user("varias", self.first, self.second))

        response = self.client.get(reverse("home"))

        self.assertContains(response, "data-delegation-switch>")
        self.assertContains(response, "js/delegation-switch.js")
        self.assertContains(response, "sweetalert2@11")

    def test_fixed_context_has_no_selector_or_warning(self):
        self.client.force_login(self.make_user("una", self.first))

        response = self.client.get(reverse("home"))

        self.assertNotContains(response, "data-delegation-switch")
        self.assertNotContains(response, "js/delegation-switch.js")

    def test_switch_script_loads_after_the_page_scripts(self):
        # La foto de los formularios se toma después de que los scripts de la página los preparan.
        self.client.force_login(User.objects.create_superuser("orden", "orden@example.test", PASSWORD))

        content = self.client.get(
            reverse("delegation_create"), HTTP_X_MODAL_REQUEST="true"
        ).content.decode()

        self.assertIn("data-delegation-switch>", content)
        self.assertGreater(content.index("js/delegation-switch.js"), content.index("js/maintainer-states.js"))
        self.assertGreater(content.index("js/delegation-switch.js"), content.index("js/maintainer-crud.js"))
