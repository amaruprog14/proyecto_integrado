"""
Pruebas transversales a los seis mantenedores y al ingreso de atención, según el plan de la
segunda evaluación: autorización por operación con 403 y auditoría (SEG-02), longitudes máxima y
máxima+1 y relaciones inactivas en el servidor (CAT-05), y entradas adversas tratadas como datos
en las búsquedas (SEG-03).
"""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from accounts.models import Delegation, Official, Role
from activities.models import SocialAttention
from configuration.models import AttentionType, AuditLog, Item, SubattentionType

User = get_user_model()
PASSWORD = "Clave-Requisitos-123"


class OperationAuthorizationTests(TestCase):
    """Un funcionario habilitado sin permisos recibe 403 en cada operación y queda registrado."""

    @classmethod
    def setUpTestData(cls):
        cls.delegation = Delegation.objects.create(delegation_name="Zona Permisos", address="Calle 1", commune="La Serena")
        cls.user = User.objects.create_user("sin.permisos", "sin.permisos@example.test", PASSWORD)
        Official.objects.create(
            user=cls.user, full_name="Sin Permisos", national_id="RUT-SIN-PERM", email="sin.permisos@example.test",
            delegation=cls.delegation,
        )
        cls.role = Role.objects.create(role_name="Rol Objetivo")
        cls.item = Item.objects.create(item_name="Ítem Objetivo")
        cls.attention_type = AttentionType.objects.create(name="Tipo Objetivo")
        cls.subattention_type = SubattentionType.objects.create(name="Sub Objetivo", attention_type=cls.attention_type)
        cls.target = User.objects.create_user("objetivo.permisos", "objetivo.permisos@example.test", PASSWORD)

    def test_every_operation_of_the_six_maintainers_is_denied_and_audited(self):
        pk = {
            "delegation": self.delegation.pk,
            "role": self.role.pk,
            "user": self.target.pk,
            "item": self.item.pk,
            "attention_type": self.attention_type.pk,
            "subattention_type": self.subattention_type.pk,
        }
        operations = [
            ("get", "delegation_list", None), ("get", "delegation_export", None), ("post", "delegation_create", None),
            ("get", "delegation_detail", "delegation"), ("post", "delegation_update", "delegation"),
            ("post", "delegation_deactivate", "delegation"),
            ("get", "role_list", None), ("get", "role_export", None), ("post", "role_create", None),
            ("get", "role_detail", "role"), ("post", "role_update", "role"), ("post", "role_deactivate", "role"),
            ("get", "user_maintainer", None), ("get", "user_export", None), ("post", "user_create", None),
            ("get", "user_detail", "user"), ("post", "user_update", "user"), ("post", "user_deactivate", "user"),
            ("get", "item_maintainer", None), ("get", "item_export", None), ("post", "item_create", None),
            ("get", "item_detail", "item"), ("post", "item_update", "item"), ("post", "item_deactivate", "item"),
            ("get", "attention_type_maintainer", None), ("get", "attention_type_export", None),
            ("post", "attention_type_create", None), ("get", "attention_type_detail", "attention_type"),
            ("post", "attention_type_update", "attention_type"), ("post", "attention_type_deactivate", "attention_type"),
            ("get", "subattention_type_maintainer", None), ("get", "subattention_type_export", None),
            ("post", "subattention_type_create", None), ("get", "subattention_type_detail", "subattention_type"),
            ("post", "subattention_type_update", "subattention_type"),
            ("post", "subattention_type_deactivate", "subattention_type"),
            ("post", "attention_entry", None),
        ]
        self.client.force_login(self.user)

        for method, route_name, key in operations:
            with self.subTest(route=route_name, method=method):
                url = reverse(route_name, args=[pk[key]] if key else None)

                response = getattr(self.client, method)(url)

                self.assertEqual(response.status_code, 403)
                self.assertTrue(
                    AuditLog.objects.filter(action="Acceso denegado", affected_table=route_name).exists()
                )
        self.delegation.refresh_from_db()
        self.assertEqual(self.delegation.status, Delegation.Status.ACTIVE)
        self.assertTrue(Role.objects.get(pk=self.role.pk).is_active)
        self.assertTrue(Item.objects.get(pk=self.item.pk).is_active)


class FieldLengthAndRelationTests(TestCase):
    """CAT-05: el servidor acepta la longitud máxima, rechaza máxima+1 y no guarda nada parcial."""

    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser("limites", "limites@example.test", PASSWORD)
        cls.attention_type = AttentionType.objects.create(name="Tipo Base")

    def setUp(self):
        self.client.force_login(self.admin)

    def cases(self):
        """(ruta, campo, longitud máxima, datos base, modelo, campo del modelo)."""
        return (
            ("delegation_create", "delegation_name", Delegation._meta.get_field("delegation_name").max_length,
             {"address": "Calle 1", "commune": "La Serena", "status": "ACTIVE"}, Delegation, "delegation_name"),
            ("role_create", "role_name", 100,
             {"scope": Role.Scope.DELEGATION, "is_active": "True",
              "permissions": [self.view_activity_permission()]}, Role, "role_name"),
            ("item_create", "item_name", 150, {"is_active": "True"}, Item, "item_name"),
            ("attention_type_create", "name", 150, {"is_active": "True"}, AttentionType, "name"),
            ("subattention_type_create", "name", 150,
             {"attention_type": self.attention_type.pk, "is_active": "True"}, SubattentionType, "name"),
        )

    @staticmethod
    def view_activity_permission():
        from django.contrib.auth.models import Permission

        return Permission.objects.get(content_type__app_label="activities", codename="view_activity").pk

    def test_maximum_length_is_accepted_and_one_more_is_rejected(self):
        for route_name, field, maximum, base, model, model_field in self.cases():
            with self.subTest(route=route_name):
                too_long = "B" * (maximum + 1)
                rejected = self.client.post(reverse(route_name), {**base, field: too_long})
                self.assertEqual(rejected.status_code, 200)
                self.assertTrue(rejected.context["form"].has_error(field))
                self.assertFalse(model.objects.filter(**{model_field: too_long}).exists())

                exact = "A" * maximum
                accepted = self.client.post(reverse(route_name), {**base, field: exact})
                self.assertEqual(accepted.status_code, 302)
                self.assertTrue(model.objects.filter(**{model_field: exact}).exists())

    def test_username_length_is_validated_on_the_server(self):
        response = self.client.post(
            reverse("user_create"),
            {"username": "u" * 151, "email": "largo@example.test", "password1": PASSWORD, "password2": PASSWORD,
             "status": Official.Status.ACTIVE},
        )

        self.assertTrue(response.context["form"].has_error("username"))
        self.assertFalse(User.objects.filter(email="largo@example.test").exists())

    def test_inactive_role_cannot_be_assigned(self):
        inactive_role = Role.objects.create(role_name="Rol Inactivo Requisito", is_active=False)

        response = self.client.post(
            reverse("user_create"),
            {"username": "con.inactivo", "email": "con.inactivo@example.test", "password1": PASSWORD,
             "password2": PASSWORD, "status": Official.Status.ACTIVE, "has_official": "on",
             "full_name": "Con Inactivo", "national_id": "12.345.678-5", "roles": [inactive_role.pk]},
        )

        self.assertTrue(response.context["form"].has_error("roles"))
        self.assertFalse(User.objects.filter(username="con.inactivo").exists())

    def test_attention_entry_rejects_an_inactive_attention_type_with_an_active_subattention(self):
        delegation = Delegation.objects.create(delegation_name="Zona Ingreso", address="Calle 1", commune="La Serena")
        Official.objects.create(
            user=self.admin, full_name="Administración Límites", national_id="RUT-LIMITES",
            email="limites@example.test", delegation=delegation,
        )
        subattention_type = SubattentionType.objects.create(name="Sub Vigente", attention_type=self.attention_type)
        AttentionType.objects.filter(pk=self.attention_type.pk).update(is_active=False)

        response = self.client.post(
            reverse("attention_entry"),
            {"recipient_national_id": "12.345.678-5", "recipient_full_name": "Persona Límite",
             "delegation": delegation.pk, "attention_type": self.attention_type.pk,
             "subattention_type": subattention_type.pk, "description": "Prueba de tipo inactivo."},
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].has_error("attention_type"))
        self.assertFalse(SocialAttention.objects.exists())


class AdverseSearchInputTests(TestCase):
    """SEG-03: apóstrofos, condiciones y etiquetas HTML se buscan como texto y se muestran escapados."""

    def test_adverse_search_terms_are_treated_as_data(self):
        self.client.force_login(User.objects.create_superuser("adverso", "adverso@example.test", PASSWORD))
        Delegation.objects.create(delegation_name="Zona Segura", address="Calle 1", commune="La Serena")
        routes = (
            "delegation_list", "role_list", "user_maintainer", "item_maintainer",
            "attention_type_maintainer", "subattention_type_maintainer",
        )
        terms = ("' OR '1'='1", "\" OR 1=1 --", "<script>alert(1)</script>")
        for route_name in routes:
            for term in terms:
                with self.subTest(route=route_name, term=term):
                    response = self.client.get(reverse(route_name), {"q": term})

                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.context["total"], 0)
                    self.assertNotContains(response, "<script>alert(1)</script>")
