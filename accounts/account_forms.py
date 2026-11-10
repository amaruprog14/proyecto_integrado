from django import forms
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction
from .forms import OfficialUserForm
from .models import ServiceRecipient, Official, Territory
from common.field_validation import clean_address, configure_text_widgets


class TerritorySelect(forms.Select):
    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(name, value, label, selected, index, subindex, attrs)
        if hasattr(value, 'instance'):
            option['attrs']['data-delegation'] = value.instance.delegation_id
        return option


class NewOfficialAccountForm(OfficialUserForm):
    account_type = forms.ChoiceField(label="Tipo de usuario", choices=[('', 'Selecciona un tipo'), ('OFFICIAL', 'Funcionario'), ('CLIENT', 'Cliente')], widget=forms.Select(attrs={'class': 'form-select', 'data-account-type': ''}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['has_official'].initial = True
        self.fields['has_official'].disabled = True
        self.fields['password1'].required = True
        self.fields['password2'].required = True

    def clean_account_type(self):
        if self.cleaned_data['account_type'] != 'OFFICIAL':
            raise ValidationError('Selecciona Funcionario para este formulario.')
        return 'OFFICIAL'

    def clean_national_id(self):
        value = super().clean_national_id()
        if value and ServiceRecipient.objects.filter(national_id=value).exists():
            raise ValidationError('Ya existe una persona usuaria con este RUT.')
        return value


class ClientAccountForm(OfficialUserForm):
    account_type = forms.ChoiceField(label="Tipo de usuario", choices=[('CLIENT', 'Cliente'), ('OFFICIAL', 'Funcionario')], widget=forms.Select(attrs={'class': 'form-select', 'data-account-type': ''}))
    territory = forms.ModelChoiceField(label="Territorio", queryset=Territory.objects.none(), widget=TerritorySelect(attrs={'class': 'form-select', 'data-client-territory': ''}))
    address = forms.CharField(label="Dirección", max_length=100, widget=forms.TextInput(attrs={'class': 'form-control'}))

    def __init__(self, *args, **kwargs):
        kwargs.pop('active_delegation', None)
        super().__init__(*args, **kwargs)
        self.recipient = getattr(self.instance, 'service_recipient', None) if self.instance else None
        for key in ('has_official', 'roles', 'authorized_delegations', 'is_staff', 'area', 'position', 'full_name'):
            self.fields.pop(key, None)
        for key in ('first_name', 'last_name', 'national_id', 'email', 'delegation'):
            self.fields[key].required = True
        self.fields['status'].choices = ServiceRecipient.Status.choices
        self.fields['delegation'].queryset = self.fields['delegation'].queryset.filter(status='ACTIVE', deleted_at__isnull=True)
        self.fields['territory'].queryset = Territory.objects.filter(is_active=True, deleted_at__isnull=True,
            delegation__in=self.fields['delegation'].queryset).select_related('delegation').order_by('territory_name')
        if self.recipient:
            self.fields['account_type'].disabled = True
            self.initial.update(account_type='CLIENT', national_id=self.recipient.national_id,
                phone=self.recipient.phone, delegation=self.recipient.delegation_id,
                territory=self.recipient.territory_id, address=self.recipient.address,
                status=self.recipient.status)
        else:
            self.initial['account_type'] = 'CLIENT'
        creating = self.instance is None or not self.instance.pk
        self.fields['password1'].required = creating
        self.fields['password2'].required = creating
        configure_text_widgets(self)
        self.order_fields(['account_type', 'first_name', 'last_name', 'username', 'email',
            'password1', 'password2', 'national_id', 'phone', 'delegation', 'territory', 'address', 'status'])

    def clean_account_type(self):
        if self.cleaned_data['account_type'] != 'CLIENT':
            raise ValidationError('El tipo de cuenta no puede cambiarse.')
        return 'CLIENT'

    def clean_address(self):
        return clean_address(self.cleaned_data['address'])

    def clean_national_id(self):
        value = super().clean_national_id()
        people = ServiceRecipient.objects.filter(national_id=value)
        if self.recipient:
            people = people.exclude(pk=self.recipient.pk)
        if people.exists() or Official.objects.filter(national_id=value).exists():
            raise ValidationError('Ya existe una persona con este RUT.')
        return value

    def clean(self):
        data = super().clean()
        if self.recipient and (self.data.get('account_type') not in (None, '', 'CLIENT')):
            self.add_error('account_type', 'El tipo de cuenta no puede cambiarse.')
        if any(self.data.get(key) for key in ('roles', 'authorized_delegations', 'is_staff', 'has_official', 'area', 'position')):
            self.add_error(None, 'Una cuenta de cliente no puede recibir permisos ni atributos de funcionario.')
        if data.get('territory') and data.get('delegation') and data['territory'].delegation_id != data['delegation'].pk:
            self.add_error('territory', 'El territorio no pertenece a la delegación elegida.')
        email = data.get('email')
        if email and ServiceRecipient.objects.filter(email__iexact=email).exclude(pk=getattr(self.recipient, 'pk', None)).exists():
            self.add_error('email', 'Ya existe otra persona con este correo.')
        return data

    def save(self):
        data = self.cleaned_data
        with transaction.atomic():
            # Las vigencias se vuelven a verificar bajo bloqueo antes de escribir.
            territory = Territory.objects.select_for_update().get(pk=data['territory'].pk)
            from .models import Delegation
            delegation = Delegation.objects.select_for_update().get(pk=territory.delegation_id)
            if not territory.is_active or territory.deleted_at or delegation.status != 'ACTIVE' or delegation.deleted_at:
                raise ValidationError('La ubicación dejó de estar vigente. Revisa el formulario.')
            user = self.instance or get_user_model()()
            for key in ('username', 'first_name', 'last_name', 'email'):
                setattr(user, key, data[key])
            user.is_active = data['status'] == 'ACTIVE'
            user.is_staff = user.is_superuser = False
            if data.get('password1'):
                user.set_password(data['password1'])
            user.save()
            recipient = self.recipient or ServiceRecipient(user=user)
            if not self.recipient or not (self.keeps_original_text("first_name") and self.keeps_original_text("last_name")):
                recipient.full_name = f"{user.first_name} {user.last_name}".strip()
            for key in ('national_id', 'email', 'phone', 'address', 'territory', 'status'):
                setattr(recipient, key, data[key])
            recipient.full_clean()
            recipient.save()
            return user
