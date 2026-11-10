from common.testing_seed import seed_test_data
import uuid
from io import BytesIO
from django.contrib.auth import authenticate
from django.contrib.auth.models import User, Permission
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse
from accounts.models import Territory, Delegation, Official, ServiceRecipient
from activities.models import ClientRequest
from openpyxl import load_workbook


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class ClientAccountsAndTerritoriesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_test_data()
        cls.admin = User.objects.get(username='admin_demo')
        cls.south = Delegation.objects.get(delegation_name='Sur')
        cls.north = Delegation.objects.get(delegation_name='Norte')
        cls.territory = Territory.objects.create(territory_name='Barrio Sur', delegation=cls.south)
        cls.other = Territory.objects.create(territory_name='Barrio Norte', delegation=cls.north)

    def setUp(self):
        cache.clear()
        self.client.force_login(self.admin)

    def payload(self, **overrides):
        # RUT válido y ficticio, reservado únicamente para esta base de pruebas.
        number = '90000001'
        result = 11 - sum(int(d) * (i % 6 + 2) for i, d in enumerate(reversed(number))) % 11
        rut = number + '-' + ('0' if result == 11 else 'K' if result == 10 else str(result))
        return dict(account_type='CLIENT', username='cliente.nuevo', first_name='Persona', last_name='Demo',
            email='cliente.nuevo@example.test', password1='Prueba-Portal-2026!', password2='Prueba-Portal-2026!',
            national_id=rut, phone='56912345678', delegation=self.south.pk, territory=self.territory.pk,
            address='Calle de Prueba 123', status='ACTIVE') | overrides

    def create_client(self):
        response = self.client.post(reverse('user_create'), self.payload())
        self.assertEqual(response.status_code, 302, getattr(response, 'context', None))
        return User.objects.get(username='cliente.nuevo')

    def test_create_edit_details_export_and_immutable_type(self):
        user = self.create_client()
        self.assertFalse(hasattr(user, 'official'))
        self.assertFalse(user.is_staff or user.is_superuser or user.groups.exists() or user.user_permissions.exists())
        self.assertEqual(user.service_recipient.territory, self.territory)
        response = self.client.get(reverse('user_detail', args=[user.pk]))
        self.assertContains(response, 'Perfil del cliente')
        self.assertContains(response, 'Calle de Prueba 123')
        data = self.payload(address='Calle Editada 456', password1='', password2='')
        self.assertEqual(self.client.post(reverse('user_update', args=[user.pk]), data).status_code, 302)
        user.refresh_from_db()
        self.assertEqual(user.service_recipient.address, 'Calle Editada 456')
        response = self.client.post(reverse('user_update', args=[user.pk]), data | {'account_type': 'OFFICIAL'})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['form'].errors)
        session = self.client.session
        session["active_delegation_id"] = self.south.pk
        session.save()
        export = self.client.get(reverse('user_export'), {'q': 'cliente.nuevo'})
        rows = list(load_workbook(BytesIO(export.content), read_only=True).active.values)
        self.assertEqual(len(rows), 2)
        self.assertIn('Cliente', rows[1])
        self.assertIn('Sur', rows[1])

    def test_type_required_and_client_permissions_rejected(self):
        for changes in ({'account_type': ''}, {'territory': self.other.pk}, {'roles': [1]}, {'is_staff': 'on'}, {'address': ''}, {'territory': ''}):
            response = self.client.post(reverse('user_create'), self.payload(**changes))
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.context['form'].errors)
            self.assertFalse(User.objects.filter(username='cliente.nuevo').exists())

    def test_password_limit_applies_to_input_before_hashing(self):
        password = "Clave Segura 9!" + "x" * 25
        self.assertEqual(len(password), 40)
        route = reverse("user_create")
        response = self.client.post(route, self.payload(password1=password + "x", password2=password + "x"))
        self.assertIn("password1", response.context["form"].errors)
        self.assertIn("password2", response.context["form"].errors)
        self.assertFalse(User.objects.filter(username="cliente.nuevo").exists())

        response = self.client.post(route, self.payload(password1=password, password2=password))
        self.assertEqual(response.status_code, 302)
        user = User.objects.get(username="cliente.nuevo")
        self.assertNotEqual(user.password, password)
        self.assertEqual(authenticate(username=user.username, password=password), user)

    def test_client_can_keep_legacy_name_and_phone_when_editing(self):
        user = self.create_client()
        user.first_name = "Ma. Persona"
        user.save(update_fields=["first_name"])
        person = user.service_recipient
        person.phone = "+56 9 1234 5678"
        person.save(update_fields=["phone"])
        data = self.payload(first_name=user.first_name, phone=person.phone, password1="", password2="",
                            address="Calle Editada 456")
        response = self.client.post(reverse("user_update", args=[user.pk]), data)
        self.assertEqual(response.status_code, 302)
        person.refresh_from_db()
        self.assertEqual(person.phone, "+56 9 1234 5678")
        self.assertEqual(person.address, "Calle Editada 456")

    def test_territory_duplicate_normalization_and_immutable_used_delegation(self):
        payload = dict(territory_name='  barrio   SUR ', delegation=self.south.pk, description='', is_active='True')
        response = self.client.post(reverse('territory_create'), payload)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['form'].errors)
        self.assertEqual(Territory.objects.count(), 2)
        response = self.client.post(reverse('territory_create'), payload | {'delegation': self.north.pk})
        self.assertEqual(response.status_code, 302)
        self.create_client()
        response = self.client.post(reverse('territory_update', args=[self.territory.pk]),
            payload | {'territory_name': 'Barrio Sur', 'delegation': self.north.pk})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['form'].errors)
        self.territory.refresh_from_db()
        self.assertEqual(self.territory.delegation, self.south)

    def test_delegation_scopes_include_clients_and_territories(self):
        client = self.create_client()
        worker = User.objects.create_user('worker-territory', password='Worker-123!')
        Official.objects.create(user=worker, full_name='Trabajador Sur', national_id='worker-test',
            email='worker@example.test', delegation=self.south)
        worker.user_permissions.add(*Permission.objects.filter(content_type__app_label='accounts',
            codename__in=['view_territory', 'add_territory', 'change_territory']))
        worker.user_permissions.add(*Permission.objects.filter(content_type__app_label='auth',
            codename__in=['view_user', 'add_user', 'change_user']))
        self.client.force_login(worker)
        response = self.client.get(reverse('territory_maintainer'))
        self.assertContains(response, 'Barrio Sur')
        self.assertNotContains(response, 'Barrio Norte')
        self.assertEqual(self.client.get(reverse('territory_detail', args=[self.other.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse('territory_update', args=[self.other.pk]), {}).status_code, 404)
        self.assertContains(self.client.get(reverse('user_maintainer')), 'cliente.nuevo')
        client.service_recipient.territory = self.other
        client.service_recipient.save()
        self.assertEqual(self.client.get(reverse('user_detail', args=[client.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse('user_create'), self.payload(
            username='ajeno', email='ajeno@example.test', delegation=self.north.pk, territory=self.other.pk)).status_code, 200)
        self.assertFalse(User.objects.filter(username='ajeno').exists())

    def test_profile_location_readonly_and_automatic_request_snapshot(self):
        user = self.create_client()
        self.client.force_login(user)
        from configuration.models import SubattentionType
        sub = SubattentionType.objects.filter(is_active=True, attention_type__is_active=True).first()
        data = dict(attention_type=sub.attention_type_id, subattention_type=sub.pk, subject='Orientación',
            description='Necesito una atención.', submission_token=uuid.uuid4(), delegation=self.north.pk,
            territory=self.other.pk, address='Dirección manipulada')
        form = self.client.get(reverse('client_request_create'))
        self.assertNotContains(form, 'name="delegation"')
        self.assertContains(form, 'Barrio Sur')
        self.assertEqual(self.client.post(reverse('client_request_create'), data).status_code, 302)
        item = ClientRequest.objects.get()
        self.assertEqual((item.delegation_id, item.territory_id, item.address_snapshot),
            (self.south.pk, self.territory.pk, 'Calle de Prueba 123'))
        self.client.post(reverse('client_profile'), {'first_name': 'Cliente', 'last_name': 'Nuevo', 'email': user.email,
                                                     'phone': '', 'territory': self.other.pk, 'address': 'Falsa dirección'})
        recipient = ServiceRecipient.objects.get(user=user)
        self.assertEqual(recipient.territory, self.territory)
        self.assertEqual(recipient.address, 'Calle de Prueba 123')
        self.territory.is_active = False
        self.territory.save()
        self.assertEqual(self.client.get(reverse('client_request_detail', args=[item.pk])).status_code, 200)
        self.client.post(reverse('client_request_create'), data | {'submission_token': uuid.uuid4()})
        self.assertEqual(ClientRequest.objects.count(), 1)

    def test_existing_incomplete_client_keeps_history_but_cannot_submit(self):
        user = self.create_client()
        recipient = user.service_recipient
        recipient.territory = None
        recipient.address = ''
        recipient.save()
        self.client.force_login(user)
        self.assertEqual(self.client.get(reverse('client_requests')).status_code, 200)
        self.assertEqual(self.client.get(reverse('client_profile')).status_code, 200)
        self.assertContains(self.client.get(reverse('client_request_create')), 'Un administrador debe completar')

    def test_activation_syncs_client_profile(self):
        user = self.create_client()
        self.client.post(reverse('user_deactivate', args=[user.pk]))
        user.refresh_from_db()
        self.assertFalse(user.is_active)
        self.assertEqual(user.service_recipient.status, 'INACTIVE')
        self.client.post(reverse('user_activate', args=[user.pk]))
        user.refresh_from_db()
        self.assertTrue(user.is_active)
        self.assertEqual(user.service_recipient.status, 'ACTIVE')

    def test_header_sorting_excludes_state_and_actions_and_keeps_filters(self):
        response = self.client.get(reverse('territory_maintainer'), {'sort':'name', 'direction':'asc', 'q':'Barrio'})
        self.assertEqual([x['cells'][1] for x in response.context['rows']], ['Barrio Norte', 'Barrio Sur'])
        self.assertContains(response, 'aria-sort="ascending"')
        self.assertContains(response, 'class="list-sort-link"')
        self.assertNotContains(response, 'Ordenar por Estado')
        self.assertNotContains(response, 'Ordenar por Acciones')
        self.assertNotContains(response, '<select id="list-sort"')
        self.assertContains(response, 'q=Barrio')
        invalid = self.client.get(reverse('territory_maintainer'), {'sort':'delegation__user__password'})
        self.assertEqual(invalid.context['selected_sort'], 'created')
