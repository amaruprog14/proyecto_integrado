from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Area, Delegation, Official, Position, Role, Territory
from activities.models import Activity
from configuration.models import AttentionType, Item, Period, SubattentionType


User = get_user_model()
MODAL = {"HTTP_X_MODAL_REQUEST": "true"}
INLINE_MODAL = {**MODAL, "HTTP_X_MODAL_FEEDBACK": "inline"}


class ModalFeedbackTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser("admin.modal", "admin.modal@example.test", "Prueba-SGR-123!")
        cls.delegation = Delegation.objects.create(
            delegation_name="Zona de referencia", address="Calle Uno", commune="La Serena",
        )
        cls.official = Official.objects.create(
            user=cls.admin, full_name="Administración de prueba", national_id="11111111-1",
            email=cls.admin.email, delegation=cls.delegation,
        )
        cls.area = Area.objects.create(area_name="Área de referencia")
        cls.position = Position.objects.create(position_name="Cargo de referencia")
        cls.role = Role.objects.create(role_name="Rol de referencia", scope=Role.Scope.DELEGATION)
        cls.permission = Permission.objects.get(content_type__app_label="accounts", codename="view_official")
        cls.item = Item.objects.create(item_name="Ítem de referencia")
        cls.attention_type = AttentionType.objects.create(name="Tipo de referencia")
        cls.today = timezone.localdate()
        Period.objects.create(start_date=cls.today, end_date=cls.today)

    def setUp(self):
        self.client.force_login(self.admin)

    def assert_modal_saved(self, response):
        errors = response.context["form"].errors.as_text() if response.context else ""
        self.assertEqual(response.status_code, 204, errors)

    def test_inline_create_and_update_do_not_leave_a_confirmation_in_any_crud(self):
        next_week = self.today + timedelta(days=7)
        cases = [
            ("delegation", Delegation, "delegation_name", {
                "delegation_name": "Zona del modal", "address": "Calle Dos",
                "commune": "La Serena", "status": Delegation.Status.ACTIVE,
            }, "Zona del modal editada"),
            ("role", Role, "role_name", {
                "role_name": "Rol del modal", "scope": Role.Scope.DELEGATION,
                "permissions": [self.permission.pk], "is_active": "True",
            }, "Rol del modal editado"),
            ("user", User, "username", {
                "account_type": "OFFICIAL", "username": "usuario.modal", "first_name": "Usuario",
                "last_name": "Modal", "email": "usuario.modal@example.test",
                "full_name": "Usuario Modal", "national_id": "16666666-K", "delegation": self.delegation.pk,
                "password1": "Cuenta-SGR-123!", "password2": "Cuenta-SGR-123!", "status": Official.Status.ACTIVE,
            }, "usuario.modal.editado"),
            ("official", Official, "full_name", {
                "full_name": "Funcionario del modal", "national_id": "12345678-5",
                "email": "funcionario.modal@example.test", "area": self.area.pk,
                "position": self.position.pk, "delegation": self.delegation.pk,
                "roles": [self.role.pk], "status": Official.Status.ACTIVE,
            }, "Funcionario del modal editado"),
            ("position", Position, "position_name", {
                "position_name": "Cargo del modal", "is_active": "on",
            }, "Cargo del modal editado"),
            ("territory", Territory, "territory_name", {
                "territory_name": "Territorio del modal", "delegation": self.delegation.pk, "is_active": "on",
            }, "Territorio del modal editado"),
            ("area", Area, "area_name", {
                "area_name": "Área del modal", "is_active": "on",
            }, "Área del modal editada"),
            ("group", Group, "name", {
                "name": "Grupo del modal", "scope": Role.Scope.DELEGATION, "is_active": "on",
            }, "Grupo del modal editado"),
            ("activity", Activity, "action_description", {
                "action_description": "Actividad del modal", "official": self.official.pk,
                "item": self.item.pk, "date": self.today.isoformat(), "record_type": Activity.RecordType.FIELD,
            }, "Actividad del modal editada"),
            ("item", Item, "item_name", {
                "item_name": "Ítem del modal", "code": "MODAL-ITM", "is_active": "True",
            }, "Ítem del modal editado"),
            ("attention_type", AttentionType, "name", {
                "name": "Tipo del modal", "is_active": "True",
            }, "Tipo del modal editado"),
            ("subattention_type", SubattentionType, "name", {
                "name": "Subatención del modal", "attention_type": self.attention_type.pk, "is_active": "True",
            }, "Subatención del modal editada"),
            ("period", Period, "end_date", {
                "start_date": next_week.isoformat(), "end_date": next_week.isoformat(),
            }, (next_week + timedelta(days=1)).isoformat()),
        ]
        for route, model, field, payload, edited_value in cases:
            next_list = reverse("role_list" if route == "delegation" else "delegation_list")
            with self.subTest(route=route, operation="create"):
                self.assert_modal_saved(self.client.post(reverse(f"{route}_create"), payload, **INLINE_MODAL))
                self.assertNotContains(self.client.get(next_list), "data-sgr-messages")
            with self.subTest(route=route, operation="update"):
                record = model.objects.get(**{field: payload[field]})
                update = {**payload, field: edited_value}
                if route == "user":
                    update.update(password1="", password2="")
                self.assert_modal_saved(self.client.post(reverse(f"{route}_update", args=[record.pk]), update, **INLINE_MODAL))
                self.assertTrue(model.objects.filter(pk=record.pk, **{field: edited_value}).exists())
                self.assertNotContains(self.client.get(next_list), "data-sgr-messages")

    def test_modal_get_and_invalid_post_preserve_previous_feedback_and_field_errors(self):
        self.client.post(reverse("delegation_deactivate", args=[self.delegation.pk]))
        edit = reverse("role_update", args=[self.role.pk])
        self.assertNotContains(self.client.get(edit, **MODAL), "data-sgr-messages")
        invalid = self.client.post(edit, {"role_name": ""}, **INLINE_MODAL)
        self.assertContains(invalid, "Ingresa el nombre del rol.")
        self.assertNotContains(invalid, "data-sgr-messages")
        self.assert_modal_saved(self.client.post(edit, {
            "role_name": "Rol actualizado", "scope": Role.Scope.DELEGATION,
            "permissions": [self.permission.pk],
        }, **INLINE_MODAL))

        following = self.client.get(reverse("delegation_list"))
        self.assertContains(following, "fue desactivada correctamente.", count=1)
        self.assertContains(following, "data-sgr-message ", count=1)
        self.assertNotContains(self.client.get(reverse("role_list")), "data-sgr-messages")

    def test_modal_with_reload_still_displays_the_confirmation_once(self):
        self.assert_modal_saved(self.client.post(reverse("position_create"), {
            "position_name": "Cargo con recarga", "is_active": "on",
        }, **MODAL))
        self.assertContains(self.client.get(reverse("position_maintainer")), "Registro guardado correctamente.", count=1)
        self.assertNotContains(self.client.get(reverse("delegation_list")), "data-sgr-messages")
