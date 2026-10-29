"""
Endurecimiento de los mantenedores: límite de 500 caracteres en las descripciones (Ítems, Roles y
Tipo de Atención), nombres de usuario con los caracteres de auth.User, e identificadores
inexistentes, enormes, negativos o no numéricos en las URLs, que responden 404 y nunca 500.
"""

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from accounts.forms import OfficialForm, OfficialUserForm
from accounts.models import Delegation, Official, Role
from accounts.role_forms import RoleForm
from common.text import DESCRIPTION_MAX_LENGTH, clean_description_text
from common.views import listing_url_for
from configuration.forms import AttentionTypeForm, ItemForm, SubattentionTypeForm
from configuration.models import AttentionType, AuditLog, Item, SubattentionType

User = get_user_model()
PASSWORD = "Clave-Limites-123"
MODAL_HEADERS = {"HTTP_X_MODAL_REQUEST": "true"}


class CleanDescriptionTextTests(SimpleTestCase):
    def test_limit_is_500(self):
        self.assertEqual(DESCRIPTION_MAX_LENGTH, 500)

    def test_exactly_the_limit_is_accepted(self):
        self.assertEqual(clean_description_text("a" * 500), "a" * 500)

    def test_one_more_than_the_limit_is_rejected(self):
        with self.assertRaises(ValidationError) as error:
            clean_description_text("a" * 501)
        self.assertIn("500 caracteres", error.exception.messages[0])

    def test_surrounding_spaces_are_stripped_before_counting(self):
        self.assertEqual(clean_description_text("  " + "a" * 500 + "\r\n  "), "a" * 500)

    def test_crlf_line_breaks_count_as_one_character(self):
        # 250 líneas: 250 + 249 saltos = 499 caracteres para el navegador (748 contando cada \r\n como 2).
        text = "\r\n".join(["a"] * 250)
        self.assertEqual(clean_description_text(text), text)
        with self.assertRaises(ValidationError):
            clean_description_text(text + "\r\nbc")

    def test_empty_values_are_allowed(self):
        self.assertEqual(clean_description_text(None), "")
        self.assertEqual(clean_description_text("   "), "")


class DescriptionLimitFormTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser("limites", "limites@example.test", PASSWORD)
        cls.permission = Permission.objects.get(content_type__app_label="configuration", codename="view_item")

    def build_forms(self, description):
        return {
            "Ítem": ItemForm(data={"item_name": "Ítem Límite", "description": description, "is_active": "True"}),
            "Tipo de Atención": AttentionTypeForm(
                data={"name": "Tipo Límite", "description": description, "is_active": "True"}
            ),
            "Rol": RoleForm(
                data={
                    "role_name": "Rol Límite",
                    "description": description,
                    "scope": Role.Scope.DELEGATION,
                    "permissions": [self.permission.pk],
                    "is_active": "True",
                },
                actor=self.admin,
            ),
        }

    def test_500_characters_are_accepted(self):
        for name, form in self.build_forms("d" * 500).items():
            with self.subTest(form=name):
                self.assertTrue(form.is_valid(), form.errors)
                self.assertEqual(form.cleaned_data["description"], "d" * 500)

    def test_501_characters_are_rejected(self):
        for name, form in self.build_forms("d" * 501).items():
            with self.subTest(form=name):
                self.assertFalse(form.is_valid())
                self.assertIn("description", form.errors)

    def test_crlf_text_within_the_browser_limit_is_accepted(self):
        text = "\r\n".join(["linea"] * 83)  # 83 * 5 + 82 = 497 caracteres.
        for name, form in self.build_forms(text).items():
            with self.subTest(form=name):
                self.assertTrue(form.is_valid(), form.errors)

    def test_textarea_renders_maxlength(self):
        for name, form in self.build_forms("").items():
            with self.subTest(form=name):
                self.assertIn('maxlength="500"', str(form["description"]))

    def test_create_views_render_maxlength_in_the_modal(self):
        self.client.force_login(self.admin)
        for route in ("item_create", "role_create", "attention_type_create"):
            with self.subTest(route=route):
                response = self.client.get(reverse(route), **MODAL_HEADERS)
                self.assertContains(response, 'maxlength="500"')

    def test_item_view_rejects_501_characters_without_saving(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("item_create"),
            {"item_name": "Ítem Largo", "description": "x" * 501, "is_active": "True"},
            **MODAL_HEADERS,
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "no puede superar los 500 caracteres")
        self.assertFalse(Item.objects.filter(item_name="Ítem Largo").exists())


class CatalogNameNormalizationTests(TestCase):
    def test_attention_type_name_collapses_inner_spaces_and_detects_duplicates(self):
        AttentionType.objects.create(name="Visita Domiciliaria")
        form = AttentionTypeForm(data={"name": "  visita   domiciliaria ", "is_active": "True"})
        self.assertFalse(form.is_valid())
        self.assertIn("name", form.errors)

    def test_subattention_name_collapses_inner_spaces(self):
        attention_type = AttentionType.objects.create(name="Tipo Sub")
        form = SubattentionTypeForm(
            data={"name": "  Entrega   de  ayuda ", "attention_type": attention_type.pk, "is_active": "True"}
        )
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["name"], "Entrega de ayuda")


class UsernameCharactersTests(TestCase):
    def test_user_form_rejects_spaces_and_symbols_in_username(self):
        for username in ("juan perez", "juan<script>", "juan#1"):
            with self.subTest(username=username):
                form = OfficialUserForm(data={"username": username, "email": "x@example.test", "status": "ACTIVE"})
                form.is_valid()
                self.assertIn("username", form.errors)

    def test_user_form_accepts_django_username_characters(self):
        form = OfficialUserForm(data={"username": "juan.perez-1_a@b+c", "email": "x@example.test", "status": "ACTIVE"})
        form.is_valid()
        self.assertNotIn("username", form.errors)

    def test_official_form_rejects_spaces_in_the_new_account_username(self):
        form = OfficialForm(data={"create_account": "on", "username": "juan perez"})
        form.is_valid()
        self.assertIn("username", form.errors)


class InvalidIdentifierTests(TestCase):
    """Ids inexistentes, enormes, negativos o no numéricos: 404 (SEG-01), nunca 500."""

    DETAIL_ROUTES = {
        "delegation": ("delegaciones", "delegation_list"),
        "user": ("usuarios", "user_maintainer"),
        "role": ("roles", "role_list"),
        "item": ("items", "item_maintainer"),
        "attention_type": ("tipos-atencion", "attention_type_maintainer"),
        "subattention_type": ("subatenciones", "subattention_type_maintainer"),
    }
    APP_PREFIX = {
        "delegation": "accounts",
        "user": "accounts",
        "role": "accounts",
        "item": "configuration",
        "attention_type": "configuration",
        "subattention_type": "configuration",
    }
    HUGE_ID = "99999999999999999999999999"

    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser("ids.invalidos", "ids@example.test", PASSWORD)
        delegation = Delegation.objects.create(delegation_name="Centro", address="Calle 1", commune="La Serena")
        Official.objects.create(
            user=cls.admin, full_name="Admin Ids", national_id="11.111.111-1", email="ids@example.test",
            delegation=delegation,
        )

    def setUp(self):
        self.client.raise_request_exception = True
        self.client.force_login(self.admin)

    def assert_not_found(self, response):
        self.assertEqual(response.status_code, 404)
        self.assertTemplateUsed(response, "404.html")

    def test_nonexistent_and_huge_ids_return_404_in_every_operation(self):
        for name in self.DETAIL_ROUTES:
            for pk in (1000, 2147483648, int(self.HUGE_ID)):
                with self.subTest(entity=name, pk=pk):
                    self.assert_not_found(self.client.get(reverse(f"{name}_detail", args=[pk])))
                    self.assert_not_found(self.client.get(reverse(f"{name}_update", args=[pk]), **MODAL_HEADERS))
                    self.assert_not_found(self.client.post(reverse(f"{name}_update", args=[pk]), **MODAL_HEADERS))
                    self.assert_not_found(self.client.post(reverse(f"{name}_activate", args=[pk])))
                    self.assert_not_found(self.client.post(reverse(f"{name}_deactivate", args=[pk])))

    def test_negative_and_non_numeric_ids_do_not_match_any_route(self):
        for name, (segment, _) in self.DETAIL_ROUTES.items():
            base = f"/{self.APP_PREFIX[name]}/{segment}"
            for pk in ("-1", "abc", "1.5", "1e3", "%20", "0x10"):
                for suffix in ("/", "/editar/", "/activar/", "/desactivar/"):
                    with self.subTest(url=f"{base}/{pk}{suffix}"):
                        self.assert_not_found(self.client.get(f"{base}/{pk}{suffix}"))
                        self.assert_not_found(self.client.post(f"{base}/{pk}{suffix}"))

    def test_teacher_example_offers_back_to_listing(self):
        response = self.client.get("/configuration/items/1000/")

        self.assert_not_found(response)
        self.assertContains(response, "No encontramos lo que buscas", status_code=404)
        self.assertContains(response, 'href="/configuration/items/"', status_code=404)
        self.assertContains(response, "Volver al listado", status_code=404)
        self.assertContains(response, "Volver al inicio", status_code=404)

    def test_unknown_section_offers_go_back_instead_of_listing(self):
        response = self.client.get("/no-existe/")

        self.assertContains(response, "Volver atrás", status_code=404)
        self.assertNotContains(response, "Volver al listado", status_code=404)


class ListingUrlTests(TestCase):
    def test_listing_is_the_maintainer_of_the_path(self):
        cases = {
            "/configuration/items/1000/": "/configuration/items/",
            "/configuration/items/99999999999999999999999999/editar/": "/configuration/items/",
            "/configuration/tipos-atencion/abc/": "/configuration/tipos-atencion/",
            "/configuration/subatenciones/5/activar/": "/configuration/subatenciones/",
            "/accounts/usuarios/7/editar/": "/accounts/usuarios/",
            "/accounts/delegaciones/-1/": "/accounts/delegaciones/",
            "/accounts/roles/3/desactivar/": "/accounts/roles/",
        }
        for path, expected in cases.items():
            with self.subTest(path=path):
                self.assertEqual(listing_url_for(path), expected)

    def test_paths_outside_a_maintainer_have_no_listing(self):
        for path in ("/", "/no-existe/", "/accounts/login/x/", "/admin/x/"):
            with self.subTest(path=path):
                self.assertIsNone(listing_url_for(path))


class OfficialFieldRulesTests(TestCase):
    """Nombre completo, teléfono y correo de funcionarios con las mismas reglas en los tres formularios."""

    def official_form(self, **overrides):
        data = {
            "full_name": "María José O'Ryan-Pérez",
            "national_id": "12.345.678-5",
            "email": "maria.jose@example.test",
            "phone": "+56 9 1234 5678",
            "status": Official.Status.ACTIVE,
        }
        data.update(overrides)
        return OfficialForm(data=data)

    def test_valid_names_are_accepted_and_spaces_collapsed(self):
        form = self.official_form(full_name="  María   José O'Ryan-Pérez  ")
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["full_name"], "María José O'Ryan-Pérez")

    def test_abbreviations_with_a_period_are_accepted(self):
        for name in ("Ma. José Rojas", "J. Pablo Díaz", "Juan Pablo Jr.", "M. J. O'Ryan"):
            with self.subTest(name=name):
                form = self.official_form(full_name=name)
                self.assertTrue(form.is_valid(), form.errors)
                self.assertEqual(form.cleaned_data["full_name"], name)

    def test_names_with_digits_or_symbols_are_rejected(self):
        for name in ("Juan 2", "Juan_Pérez", "<b>Juan</b>", "Juan -- Pérez", "-Juan", "Juan > Pedro",
                     ".Juan", "Juan..", "Ma. . José", "J.2", "Juan@Pérez", "Juan & Pedro"):
            with self.subTest(name=name):
                form = self.official_form(full_name=name)
                self.assertFalse(form.is_valid())
                self.assertIn("full_name", form.errors)

    def test_phone_formats(self):
        for phone in ("+56912345678", "+56 9 1234 5678", "(51) 222 3344", "512223344", "22223333", ""):
            with self.subTest(phone=phone):
                form = self.official_form(phone=phone)
                self.assertTrue(form.is_valid(), form.errors)
        for phone in ("1234567", "+56 9 1234 5678 90123", "912345678 ext 2", "+56-9-abc", "56+912345678"):
            with self.subTest(phone=phone):
                form = self.official_form(phone=phone)
                self.assertFalse(form.is_valid())
                self.assertIn("phone", form.errors)

    def test_user_form_applies_the_same_name_and_phone_rules(self):
        form = OfficialUserForm(
            data={"username": "nuevo", "email": "nuevo@example.test", "status": "ACTIVE",
                  "has_official": "on", "full_name": "Juan 2", "national_id": "12.345.678-5", "phone": "123"}
        )
        form.is_valid()
        self.assertIn("full_name", form.errors)
        self.assertIn("phone", form.errors)

    def test_official_email_cannot_repeat_another_user_account(self):
        User.objects.create_user("cuenta.admin", "Compartido@example.test", PASSWORD)

        form = self.official_form(email="compartido@example.test")

        self.assertFalse(form.is_valid())
        self.assertIn("email", form.errors)

    def test_official_keeps_the_email_of_its_own_account(self):
        user = User.objects.create_user("propia", "propia@example.test", PASSWORD)
        official = Official.objects.create(
            user=user, full_name="Cuenta Propia", national_id="12.345.678-5", email="propia@example.test"
        )

        form = OfficialForm(
            data={"full_name": "Cuenta Propia", "national_id": "12.345.678-5",
                  "email": "propia@example.test", "status": Official.Status.ACTIVE},
            instance=official,
        )

        self.assertTrue(form.is_valid(), form.errors)


class CrlfDescriptionAuditTests(TestCase):
    """La descripción se guarda tal como llega (solo strip): sin cambios fantasma en la auditoría."""

    def test_clean_description_returns_the_original_line_breaks(self):
        self.assertEqual(clean_description_text("  uno\r\ndos\r\n "), "uno\r\ndos")

    def test_editing_an_item_without_touching_a_crlf_description_does_not_audit_it(self):
        admin = User.objects.create_superuser("auditoria.crlf", "auditoria.crlf@example.test", PASSWORD)
        item = Item.objects.create(item_name="Ítem CRLF", description="Primera línea\r\nSegunda línea")
        self.client.force_login(admin)

        self.client.post(
            reverse("item_update", args=[item.pk]),
            {"code": item.code, "item_name": "Ítem CRLF renombrado", "description": "Primera línea\r\nSegunda línea"},
            **MODAL_HEADERS,
        )

        item.refresh_from_db()
        self.assertEqual(item.item_name, "Ítem CRLF renombrado")
        self.assertEqual(item.description, "Primera línea\r\nSegunda línea")
        log = AuditLog.objects.get(action="Actualización de ítem", affected_record_id=item.pk)
        self.assertIn("Nombre", log.new_value)
        self.assertNotIn("Descripción", log.previous_value)
        self.assertNotIn("Descripción", log.new_value)
