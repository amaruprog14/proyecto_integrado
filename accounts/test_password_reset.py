from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.utils import timezone

from accounts.models import Delegation, Official, PasswordResetCode, Role


class PasswordResetCodeTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("ana", "ana@example.test", "Clave-Inicial-1")

    def _expire(self, record, minutes=11):
        PasswordResetCode.objects.filter(pk=record.pk).update(
            expires_at=timezone.now() - timedelta(minutes=minutes - 10)
        )
        record.refresh_from_db()

    def test_issue_stores_only_the_hash(self):
        record, code = PasswordResetCode.issue(self.user)
        self.assertEqual(len(code), 6)
        self.assertNotIn(code, record.code_hash)
        self.assertTrue(record.is_active)

    def test_valid_code_verifies_and_enables_password_change(self):
        record, code = PasswordResetCode.issue(self.user)
        self.assertFalse(record.can_set_password())
        self.assertTrue(record.verify(code))
        self.assertTrue(record.can_set_password())

    def test_wrong_code_counts_attempts_and_blocks_after_limit(self):
        record, code = PasswordResetCode.issue(self.user)
        for _ in range(PasswordResetCode.max_attempts()):
            self.assertFalse(record.verify("000000" if code != "000000" else "111111"))
        self.assertFalse(record.is_active)
        self.assertFalse(record.verify(code))

    def test_expired_code_is_rejected(self):
        record, code = PasswordResetCode.issue(self.user)
        self._expire(record)
        self.assertFalse(record.verify(code))

    def test_used_code_cannot_be_reused(self):
        record, code = PasswordResetCode.issue(self.user)
        self.assertTrue(record.verify(code))
        record.consume()
        self.assertFalse(record.verify(code))
        self.assertFalse(record.can_set_password())

    def test_resend_requires_wait_and_invalidates_previous_code(self):
        first, first_code = PasswordResetCode.issue(self.user)
        with self.assertRaises(ValidationError) as ctx:
            PasswordResetCode.issue(self.user)
        self.assertEqual(ctx.exception.code, "resend_too_soon")

        PasswordResetCode.objects.filter(pk=first.pk).update(
            last_sent_at=timezone.now() - timedelta(seconds=60)
        )
        second, second_code = PasswordResetCode.issue(self.user)
        first.refresh_from_db()
        self.assertFalse(first.verify(first_code))
        self.assertTrue(second.verify(second_code))
        self.assertEqual(second.resend_count, 1)

    @override_settings(PASSWORD_RESET_MAX_RESENDS=1, PASSWORD_RESET_RESEND_WAIT_SECONDS=0)
    def test_resend_limit(self):
        PasswordResetCode.issue(self.user)
        PasswordResetCode.issue(self.user)
        with self.assertRaises(ValidationError) as ctx:
            PasswordResetCode.issue(self.user)
        self.assertEqual(ctx.exception.code, "resend_limit")


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