from common.testing_seed import seed_test_data
import uuid
from datetime import timedelta
from io import BytesIO

from django.contrib.auth.models import User, Permission
from django.core.cache import cache
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from openpyxl import load_workbook

from accounts.models import ServiceRecipient, Delegation, Official, Role, Territory
from configuration.models import AttentionType, SubattentionType
from .models import Activity, ClientRequest, ClientRequestEvent


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class ClientPortalTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_test_data()
        cls.users = [User.objects.create_user(f"client{i}", password="Client-12345") for i in range(2)]
        cls.people = [ServiceRecipient.objects.create(user=user, full_name=f"Cliente {i}",
            national_id=rut, email=f"client{i}@example.test")
            for i, (user, rut) in enumerate(zip(cls.users, ("12345678-5", "11111111-1")))]
        cls.delegation = Delegation.objects.get(delegation_name="Sur")
        cls.territory = Territory.objects.create(territory_name="Territorio Demo", delegation=cls.delegation)
        for person in cls.people:
            person.territory = cls.territory
            person.address = "Calle Demo 123"
            person.save()
        cls.kind = AttentionType.objects.filter(is_active=True, deleted_at__isnull=True).first()
        cls.sub = SubattentionType.objects.filter(attention_type=cls.kind, is_active=True).first()

    def setUp(self):
        self.client.force_login(self.users[0])

    def payload(self, **overrides):
        return dict(attention_type=self.kind.pk, subattention_type=self.sub.pk,
                    delegation=self.delegation.pk, subject="Consulta ciudadana",
                    description="Necesito orientación sobre los servicios.",
                    submission_token=str(uuid.uuid4()), **overrides)

    def create_request(self, recipient=None):
        return ClientRequest.objects.create(recipient=recipient or self.people[0], delegation=self.delegation,
            attention_type=self.kind, subattention_type=self.sub, subject="Solicitud privada",
            description="Antecedentes privados", submission_token=uuid.uuid4())

    def test_create_owner_status_and_duplicate_protection(self):
        payload = self.payload()
        payload.update(recipient=self.people[1].pk, status="RESOLVED", response="Falsa respuesta")
        self.assertRedirects(self.client.post(reverse("client_request_create"), payload), reverse("client_requests"))
        item = ClientRequest.objects.get()
        self.assertEqual(item.recipient, self.people[0])
        self.assertEqual(item.status, "RECEIVED")
        self.assertEqual(item.response, "")
        self.client.post(reverse("client_request_create"), payload)
        self.assertEqual(ClientRequest.objects.count(), 1)
        self.assertEqual(ClientRequestEvent.objects.count(), 1)
        self.assertContains(self.client.get(reverse("client_requests")), "Recibida")

    def test_new_request_appears_in_activity_list_without_creating_an_activity(self):
        previous_count = Activity.objects.count()
        self.client.post(reverse("client_request_create"), self.payload())
        origin = ClientRequest.objects.get()
        listing = reverse("activity_maintainer")
        self.assertEqual(self.client.get(listing).status_code, 403)

        self.client.force_login(User.objects.get(username="admin_demo"))
        response = self.client.get(listing, {"q": origin.identifier})
        self.assertContains(response, origin.identifier)
        self.assertContains(response, "Tipo de registro")
        self.assertContains(response, 'data-maintainer-websocket="/ws/maintainers/activity/"')
        self.assertEqual(Activity.objects.count(), previous_count)

    def test_activity_list_orders_both_sources_before_pagination_and_export(self):
        cache.clear()
        origin = self.create_request()
        origin.subject = "MIX Consulta ciudadana"
        origin.save(update_fields=["subject"])
        template = Activity.objects.first()
        today = timezone.localdate(origin.created_at)
        activities = [Activity.objects.create(
            code=f"MIX-{offset}", date=today + timedelta(days=offset), official=template.official,
            item=template.item, record_type=Activity.RecordType.FIELD,
        ) for offset in (3, 2, 1, -1, -2)]
        self.client.force_login(User.objects.get(username="admin_demo"))
        listing = reverse("activity_maintainer")
        page = self.client.get(listing, {"q": "MIX", "page_size": 5})
        self.assertEqual(list(page.context["page_obj"]), [*activities[:3], origin, activities[3]])
        self.assertEqual(list(self.client.get(listing, {"page": 2}).context["page_obj"]), [activities[4]])
        result = self.client.get(reverse("activity_export"))
        codes = [row[0] for row in list(load_workbook(BytesIO(result.content)).active.values)[1:]]
        self.assertEqual(codes, [*(obj.code for obj in activities[:3]), origin.identifier,
                                 *(obj.code for obj in activities[3:])])
        self.assertEqual(list(self.client.get(listing, {"record_source": "request"}).context["page_obj"]), [origin])
        self.assertEqual(list(self.client.get(listing, {"record_source": "activity"}).context["page_obj"]), activities[:5])
        same_day = self.client.get(listing, {"record_source": "", "date_from": today, "date_to": today})
        self.assertEqual(list(same_day.context["page_obj"]), [origin])

    def test_direct_url_and_filters_never_expose_another_client(self):
        own = self.create_request()
        other = self.create_request(self.people[1])
        self.assertEqual(self.client.get(reverse("client_request_detail", args=[other.pk])).status_code, 404)
        response = self.client.get(reverse("client_requests"), {"recipient": self.people[1].pk})
        self.assertEqual(list(response.context["page_obj"]), [own.attention_case])
        self.assertContains(response, 'action-icon--view')
        self.assertEqual(self.client.post(reverse("staff_client_request_review", args=[own.pk]),
            {"status": "RESOLVED", "response": "No autorizado"}).status_code, 403)

    def test_profile_edits_only_own_contact_and_preserves_identity(self):
        response = self.client.get(reverse("client_profile"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Cargo</dt>")
        self.client.post(reverse("client_profile"), {"first_name": "Clara", "last_name": "Rojas",
            "email": "new@example.test", "phone": "56912345678", "user": self.users[1].pk,
            "full_name": "Identidad falsa", "national_id": "11.111.111-1", "status": "INACTIVE"})
        self.people[0].refresh_from_db()
        self.people[1].refresh_from_db()
        self.assertEqual(self.people[0].email, "new@example.test")
        self.assertEqual(self.people[0].user_id, self.users[0].pk)
        # Nombre editable por el propio cliente (nombres + apellidos, igual en su cuenta); el
        # nombre completo enviado directamente, el RUT, el estado y la cuenta vinculada no.
        self.assertEqual(self.people[0].full_name, "Clara Rojas")
        self.users[0].refresh_from_db()
        self.assertEqual((self.users[0].first_name, self.users[0].last_name, self.users[0].email),
                         ("Clara", "Rojas", "new@example.test"))
        self.assertNotEqual(self.people[0].national_id, "11111111-1")
        self.assertEqual(self.people[0].status, "ACTIVE")
        self.assertEqual(self.people[1].email, "client1@example.test")

    def test_form_rejects_inactive_and_mismatched_catalogs(self):
        other_type = AttentionType.objects.create(name="Otro tipo")
        payload = self.payload()
        payload["attention_type"] = other_type.pk
        response = self.client.post(reverse("client_request_create"), payload)
        self.assertIn("subattention_type", response.context["form"].errors)
        self.kind.is_active = False
        self.kind.save()
        response = self.client.post(reverse("client_request_create"), self.payload())
        self.assertTrue(response.context["form"].errors)
        self.assertEqual(ClientRequest.objects.count(), 0)

    def test_disabled_client_anonymous_and_employee_access(self):
        self.assertRedirects(self.client.get(reverse("home")), reverse("client_requests"))
        self.client.force_login(User.objects.get(username="admin_demo"))
        self.assertEqual(self.client.get(reverse("client_requests")).status_code, 403)
        self.client.force_login(self.users[0])
        self.people[0].status = "INACTIVE"
        self.people[0].save()
        self.assertIn(self.client.get(reverse("client_requests")).status_code, (302, 403))
        self.assertIsNone(__import__('django.contrib.auth', fromlist=['authenticate']).authenticate(
            username=self.users[0].username, password="Client-12345"))
        self.client.logout()
        self.assertEqual(self.client.get(reverse("client_requests")).status_code, 302)

    def test_staff_response_and_delegation_boundary(self):
        item = self.create_request()
        user = User.objects.create_user("reviewer", password="Reviewer-123")
        official = Official.objects.create(user=user, full_name="Revisor", national_id="staff-test",
                                           email="reviewer@example.test", delegation=self.delegation)
        role = Role.objects.create(role_name="Revisión ciudadana", scope=Role.Scope.DELEGATION)
        role.permissions.add(*Permission.objects.filter(content_type__app_label="activities",
            codename__in=["view_socialattention", "change_socialattention", "view_activity"]))
        official.roles.add(role)
        self.client.force_login(user)
        url = reverse("staff_client_request_review", args=[item.pk])
        listing = reverse("staff_client_requests")
        for page in (listing, url, listing):
            self.assertContains(self.client.get(page),
                f'<a class="maintainer-sidebar-link is-active" href="{listing}" aria-current="page">Solicitudes ciudadanas</a>',
                html=True, count=1)
        activities = reverse("activity_maintainer")
        response = self.client.get(activities)
        self.assertContains(response,
            f'<a class="maintainer-sidebar-link is-active" href="{activities}" aria-current="page">Actividades</a>',
            html=True, count=1)
        self.assertContains(response,
            f'<a class="maintainer-sidebar-link" href="{listing}">Solicitudes ciudadanas</a>',
            html=True, count=1)
        self.assertContains(self.client.get(activities, {"q": item.identifier}), item.identifier)

        self.assertEqual(self.client.post(url, {"status": "RESOLVED", "response": ""}).status_code, 200)
        self.assertEqual(self.client.post(url, {"status": "RESOLVED", "response": "Tu consulta fue atendida."}).status_code, 302)
        item.refresh_from_db()
        self.assertEqual(item.status, "RESOLVED")
        self.assertEqual(item.events.count(), 1)
        self.client.force_login(self.users[0])
        self.assertContains(self.client.get(reverse("client_request_detail", args=[item.pk])), "Tu consulta fue atendida.")
        self.client.force_login(user)
        item.delegation = Delegation.objects.get(delegation_name="Norte")
        item.save()
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.post(url, {"status": "REVIEW", "response": "Ajena"}).status_code, 404)
        self.assertEqual(list(self.client.get(activities, {"q": item.identifier}).context["page_obj"]), [])
        role.permissions.remove(Permission.objects.get(content_type__app_label="activities",
                                                      codename="view_socialattention"))
        item.delegation = self.delegation
        item.save(update_fields=["delegation"])
        self.assertEqual(list(self.client.get(activities, {"q": item.identifier}).context["page_obj"]), [])

    def test_staff_list_and_export_share_scope_search_status_and_order(self):
        cache.clear()
        user = User.objects.create_user("lector-solicitudes")
        Official.objects.create(user=user, full_name="Lector de solicitudes", national_id="12345678-5",
                                email="lector-solicitudes@example.test", delegation=self.delegation)
        user.user_permissions.add(Permission.objects.get(
            content_type__app_label="activities", codename="view_socialattention"))
        for index in range(8):
            item = self.create_request()
            item.subject = f"Consulta extensa {index} " + "x" * 70
            item.save(update_fields=["subject"])
        foreign = self.create_request()
        foreign.delegation = Delegation.objects.get(delegation_name="Norte")
        foreign.subject = "Consulta extensa de otra delegación"
        foreign.save(update_fields=["delegation", "subject"])
        reviewed = self.create_request()
        reviewed.subject, reviewed.status = "Consulta extensa revisada", ClientRequest.Status.REVIEW
        reviewed.save(update_fields=["subject", "status"])

        self.client.force_login(user)
        listing = reverse("staff_client_requests")
        export = reverse("staff_client_requests_export")
        params = {"q": "Consulta extensa", "status": "RECEIVED", "sort": "subject", "direction": "asc", "page_size": 5}
        response = self.client.get(listing, params)
        self.assertEqual(response.context["total"], 8)
        self.assertEqual(len(response.context["page_obj"]), 5)
        self.assertEqual(response.context["statuses"], ClientRequest.Status.choices)
        self.assertContains(response, 'data-maintainer-websocket="/ws/maintainers/staff_request/"')
        page = self.client.get(listing, {"page": 2})
        self.assertEqual(page.context["page_obj"].number, 2)
        self.assertEqual(len(page.context["page_obj"]), 3)

        response = self.client.get(export)
        with BytesIO(response.content) as workbook_data:
            workbook = load_workbook(workbook_data, read_only=True)
            subjects = [row[2] for row in list(workbook.active.values)[1:]]
            workbook.close()
        self.assertEqual(subjects, [f"Consulta extensa {index} " + "x" * 70 for index in range(8)])
        self.assertRedirects(self.client.get(export), listing)
        self.assertEqual(self.client.get(listing).context["page_obj"].number, 2)

        self.client.force_login(self.users[0])
        self.assertEqual(self.client.get(export).status_code, 403)


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class ClientPhotoTests(TransactionTestCase):
    def test_client_crop_and_private_photo(self):
        import json
        import tempfile
        from io import BytesIO
        from PIL import Image
        from django.core.files.uploadedfile import SimpleUploadedFile
        with tempfile.TemporaryDirectory() as directory, override_settings(MEDIA_ROOT=directory):
            user = User.objects.create_user("client-photo", password="Client-12345")
            recipient = ServiceRecipient.objects.create(user=user, full_name="Cliente Foto", national_id="12345678-5")
            image = BytesIO()
            Image.new("RGB", (100, 80), "red").save(image, "PNG")
            self.client.force_login(user)
            self.assertEqual(self.client.post(reverse("client_profile"), {
                "first_name": "Cliente", "last_name": "Foto",
                "email": "photo@example.test", "phone": "", "photo_crop": json.dumps(
                    dict(x=10, y=10, width=50, height=50)),
                "photo": SimpleUploadedFile("perfil.png", image.getvalue(), content_type="image/png")
            }).status_code, 302)
            recipient.refresh_from_db()
            with recipient.photo.open("rb") as saved:
                self.assertEqual(Image.open(saved).size, (50, 50))
            response = self.client.get(reverse("client_profile_photo"))
            self.assertEqual(response.status_code, 200)
            self.assertIn("private", response["Cache-Control"])
            self.assertIn("no-store", response["Cache-Control"])
            self.assertTrue(b"".join(response.streaming_content))
            response.close()
            other = User.objects.create_user("client-other-photo", password="Client-12345")
            ServiceRecipient.objects.create(user=other, full_name="Otro Cliente", national_id="11111111-1")
            self.client.force_login(other)
            self.assertEqual(self.client.get(reverse("client_profile_photo"), {"recipient": recipient.pk}).status_code, 404)
