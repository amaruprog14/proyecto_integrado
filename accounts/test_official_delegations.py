from django.test import TestCase

from accounts.models import Delegation, Official, Role


class OfficialDelegationsTests(TestCase):
    def setUp(self):
        self.d1 = Delegation.objects.create(delegation_name="Centro", address="Calle 1", commune="La Serena")
        self.d2 = Delegation.objects.create(delegation_name="Norte", address="Calle 2", commune="La Serena")
        self.d3 = Delegation.objects.create(delegation_name="Sur", address="Calle 3", commune="La Serena")
        self.official = Official.objects.create(
            full_name="Ana", national_id="1-9", email="ana@example.test", delegation=self.d1
        )

    def test_delegation_code_is_generated_and_unique(self):
        self.assertTrue(self.d1.code.startswith("DEL-"))
        self.assertNotEqual(self.d1.code, self.d2.code)

    def test_single_delegation_is_the_only_one_authorized(self):
        self.assertEqual(list(self.official.get_authorized_delegations()), [self.d1])

    def test_additional_authorized_delegations(self):
        self.official.authorized_delegations.add(self.d2)
        self.assertEqual(set(self.official.get_authorized_delegations()), {self.d1, self.d2})

    def test_inactive_delegations_are_not_offered(self):
        self.official.authorized_delegations.add(self.d2)
        self.d2.deactivate()
        self.assertEqual(list(self.official.get_authorized_delegations()), [self.d1])

    def test_transversal_role_gets_all_active_delegations(self):
        role = Role.objects.create(role_name="Administrador", scope=Role.Scope.ALL)
        role.officials.add(self.official)
        self.assertEqual(set(self.official.get_authorized_delegations()), {self.d1, self.d2, self.d3})