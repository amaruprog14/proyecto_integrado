from common.testing_seed import seed_test_data
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse, resolve
from django.utils import timezone
from accounts.models import Delegation
from common.list_state import ROUTES, SORTS
from common.pagination import ClampedPaginationMixin


class ListStateTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_test_data()
        cls.admin = User.objects.get(username='admin_demo')
        for index in range(66):
            Delegation.objects.create(delegation_name=f'Paginable {index:03d}', address='Calle 1', commune='La Serena')

    def setUp(self):
        self.client.force_login(self.admin)

    def test_every_list_inherits_mixin_and_offers_allowed_sizes_and_sort(self):
        for route, module in ROUTES.items():
            if route.endswith('_export') or module not in SORTS:
                continue
            with self.subTest(module=module):
                url = reverse(route)
                self.assertTrue(issubclass(resolve(url).func.view_class, ClampedPaginationMixin))
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.context['page_obj'].paginator.per_page, 15)
                self.assertEqual(response.context['selected_sort'], 'date' if module == 'activity' else 'created')
                for size in (5, 15, 30):
                    self.assertContains(response, f'<option value="{size}"')
                self.assertContains(response, 'name="sort"')
                self.assertContains(response, 'name="direction"')
                # Las dos columnas de cada módulo deben aceptar ambas direcciones.
                for field in SORTS[module][1]:
                    for direction in ('asc', 'desc'):
                        sorted_response = self.client.get(url, {'sort': field, 'direction': direction})
                        self.assertEqual(sorted_response.status_code, 200)
                        self.assertEqual(sorted_response.context['selected_sort'], field)
                        self.assertEqual(sorted_response.context['selected_direction'], direction)

    def test_restore_after_detail_other_module_and_cancel(self):
        url = reverse('delegation_list')
        params = {'q': 'Paginable', 'page_size': 5, 'sort': 'name', 'direction': 'asc'}
        self.client.get(url, params)
        response = self.client.get(url, {'page': 3})
        original = [obj.pk for obj in response.context['delegations']]
        self.client.get(reverse('delegation_detail', args=[original[0]]))
        self.client.get(reverse('role_list'), {'q': 'Consulta', 'page_size': 30})
        restored = self.client.get(url)
        self.assertEqual(restored.context['page_obj'].number, 3)
        self.assertEqual([obj.pk for obj in restored.context['delegations']], original)
        self.assertEqual(restored.context['query'], 'Paginable')
        self.assertEqual(restored.context['selected_sort'], 'name')
        self.assertIn('page=3', restored['X-List-URL'])

    def test_changes_reset_page_and_empty_filters_clear_session(self):
        url = reverse('delegation_list')
        self.client.get(url, {'q': 'Paginable', 'page_size': 5, 'status': 'ACTIVE'})
        self.client.get(url, {'page': 4})
        changed = self.client.get(url, {'sort': 'name', 'page': 4})
        self.assertEqual(changed.context['page_obj'].number, 1)
        cleared = self.client.get(url, {'q': '', 'status': ''})
        self.assertEqual(cleared.context['query'], '')
        self.assertEqual(cleared.context['selected_status'], '')
        self.assertEqual(self.client.get(url).context['query'], '')

    def test_invalid_values_and_removed_last_page(self):
        url = reverse('delegation_list')
        invalid = self.client.get(url, {'page_size': '1000', 'page': '-4', 'sort': 'user__password', 'direction': 'SQL'})
        self.assertEqual(invalid.context['page_obj'].number, 1)
        self.assertEqual(invalid.context['page_obj'].paginator.per_page, 15)
        self.assertEqual(invalid.context['selected_sort'], 'created')
        for value in ('abc', '0', '-1', '999999999999999999999999999999999'):
            self.assertEqual(self.client.get(url, {'page': value}).status_code, 200)
        self.client.get(url, {'q': 'Paginable', 'page_size': 5})
        last = self.client.get(url, {'page': 14})
        self.assertEqual(last.context['page_obj'].number, 14)
        Delegation.objects.filter(pk__in=[obj.pk for obj in last.context['delegations']]).delete()
        adjusted = self.client.get(url)
        self.assertEqual(adjusted.context['page_obj'].number, 13)
        self.assertIn('page=13', adjusted['X-List-URL'])
        empty = self.client.get(url, {'q': 'Inexistente'})
        self.assertEqual(empty.context['total'], 0)
        self.assertEqual(empty.context['page_obj'].number, 1)

    def test_created_order_and_deterministic_ties(self):
        timestamp = timezone.now()
        Delegation.objects.filter(delegation_name__startswith='Paginable').update(created_at=timestamp)
        response = self.client.get(reverse('delegation_list'), {'q': 'Paginable', 'page_size': 30})
        ids = [obj.pk for obj in response.context['delegations']]
        self.assertEqual(ids, sorted(ids, reverse=True))
        oldest = Delegation.objects.get(delegation_name='Paginable 000')
        oldest.address = 'Dirección editada'
        oldest.save()
        self.assertEqual([obj.pk for obj in self.client.get(reverse('delegation_list')).context['delegations']], ids)

    def test_different_accounts_and_delegations_do_not_share_state(self):
        url = reverse('official_maintainer')
        self.client.get(url, {'q': 'Ninguno', 'page_size': 30})
        session = self.client.session
        session['active_delegation_id'] = Delegation.objects.get(delegation_name='Sur').pk
        session.save()
        self.assertEqual(self.client.get(url).context['query'], '')
        self.client.force_login(User.objects.get(username='funcionario4'))
        response = self.client.get(url)
        self.assertEqual(response.context['query'], '')
        self.assertNotContains(response, 'funcionario1@demo.cl')

    def test_export_inherits_filters_and_order_without_changing_page(self):
        from django.core.cache import cache
        from openpyxl import load_workbook
        from io import BytesIO
        url = reverse('delegation_list')
        self.client.get(url, {'q': 'Paginable', 'page_size': 5, 'sort': 'name', 'direction': 'asc'})
        self.client.get(url, {'page': 3})
        cache.clear()
        export = self.client.get(reverse('delegation_export'))
        rows = list(load_workbook(BytesIO(export.content), read_only=True).active.values)
        self.assertEqual(len(rows), 67)
        self.assertEqual(rows[1][1], 'Paginable 000')
        self.assertEqual(self.client.get(url).context['page_obj'].number, 3)

    def test_every_export_has_independent_thirty_second_cooldown(self):
        from django.core.cache import cache
        from unittest.mock import patch
        for module in SORTS:
            with self.subTest(module=module):
                cache.clear()
                url = reverse(module + '_export')
                with patch('django.core.cache.cache.add', wraps=cache.add) as acquire:
                    self.assertEqual(self.client.get(url).status_code, 200)
                    acquire.assert_called_with(f'{module}-export:{self.admin.pk}', True, timeout=30)
                blocked = self.client.get(url)
                self.assertEqual(blocked.status_code, 302)
                self.assertNotIn('Content-Disposition', blocked)
                cache.delete(f'{module}-export:{self.admin.pk}')
                self.assertEqual(self.client.get(url).status_code, 200)
