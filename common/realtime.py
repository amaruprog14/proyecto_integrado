"""Avisos de mantenedores con los mismos ámbitos que HTTP, en un proceso local."""
import logging
from collections import Counter
from threading import Lock

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db import transaction
from django.db.models.signals import pre_save, post_save, pre_delete, post_delete, m2m_changed
from django.dispatch import receiver

from accounts.models import Official, Delegation, Role, Area, Position, GroupProfile, Territory, ServiceRecipient
from activities.models import Activity, SocialAttention
from configuration.models import Item, Period, AttentionType, SubattentionType, ServiceType
from common.scopes import current_permission

logger = logging.getLogger(__name__)
MODELS = dict(territory=Territory, activity=Activity, official=Official, delegation=Delegation, user=get_user_model(),
    role=Role, area=Area, position=Position, group=Group, period=Period,
    item=Item, attention_type=AttentionType, subattention_type=SubattentionType)
ROUTES = dict(territory='territory_maintainer', activity='activity_maintainer', official='official_maintainer',
    delegation='delegation_list', user='user_maintainer', role='role_list', area='area_maintainer',
    position='position_maintainer', group='group_maintainer', period='period_maintainer',
    item='item_maintainer', attention_type='attention_type_maintainer', subattention_type='subattention_type_maintainer')
_readers = Counter()
_lock = Lock()


def permission(key):
    model = MODELS[key]
    return f'{model._meta.app_label}.view_{model._meta.model_name}'


def can_read(user, key='activity'):
    official = getattr(user, 'official', None)
    return bool(user.is_active and (user.is_superuser or (official and official.is_enabled))
                and user.has_perm(permission(key)))


def subscribe(user_id, key='activity'):
    with _lock:
        _readers[key, user_id] += 1


def unsubscribe(user_id, key='activity'):
    with _lock:
        _readers[key, user_id] -= 1
        if _readers[key, user_id] <= 0:
            _readers.pop((key, user_id), None)


def group_name(user_id, key='activity'):
    return f'maintainers.{key}.user.{user_id}'


def send_notice(uid, key):
    try:
        async_to_sync(get_channel_layer().group_send)(group_name(uid, key), {'type': 'maintainer.changed'})
    except Exception:
        # Un fallo de transporte no convierte un guardado confirmado en un error.
        logger.exception('No se pudo enviar el aviso de %s', key)


def queryset(key, user):
    from accounts.views import scoped_officials, scoped_users, scoped_delegations
    from common.maintainers import activity_queryset
    # No heredar el permiso de escritura ni el contexto del actor que guardó.
    token = current_permission.set(permission(key))
    try:
        if key == 'official':
            return scoped_officials(user)
        if key == 'user':
            return scoped_users(user)
        if key == 'delegation':
            return scoped_delegations(user)
        if key == 'territory':
            from accounts.models import Role
            from common.scopes import permission_scope, delegation_ids
            qs = Territory.objects.filter(deleted_at__isnull=True)
            scope = permission_scope(user, permission(key))
            return qs if scope == Role.Scope.ALL else qs.filter(delegation_id__in=delegation_ids(user)) if scope == Role.Scope.DELEGATION else qs.none()
        if key == 'activity':
            return activity_queryset(user, permission(key))
        qs = MODELS[key].objects.all()
        if key != 'group':
            qs = qs.filter(deleted_at__isnull=True)
        return qs
    finally:
        current_permission.reset(token)


def audience(key, pk):
    with _lock:
        ids = [uid for module, uid in _readers if module == key]
    return {u.pk for u in get_user_model().objects.filter(pk__in=ids)
            if can_read(u, key) and queryset(key, u).filter(pk=pk).exists()}


def publish(key, pk, previous):
    try:
        for uid in previous | audience(key, pk):
            send_notice(uid, key)
    except Exception:
        logger.exception('No se pudo anunciar el cambio de %s', key)


def affected(instance):
    """Filas modificadas y etiquetas relacionadas que aparecen en otros listados."""
    rows = {(key, instance.pk) for key, model in MODELS.items()
            if isinstance(instance, model) and instance.pk}
    if isinstance(instance, ServiceRecipient) and instance.user_id:
        rows.add(('user', instance.user_id))
    if isinstance(instance, Official):
        rows.update(('role', pk) for pk in instance.roles.values_list('pk', flat=True))
        if instance.user_id:
            rows.add(('user', instance.user_id))
    if isinstance(instance, Role):
        rows.update(('official', pk) for pk in instance.officials.values_list('pk', flat=True))
    if isinstance(instance, get_user_model()):
        rows.update(('group', pk) for pk in instance.groups.values_list('pk', flat=True))
    if isinstance(instance, SocialAttention) and instance.activity_id:
        rows.add(('activity', instance.activity_id))
    if isinstance(instance, GroupProfile):
        rows.add(('group', instance.group_id))
    related = {
        Official: (('activity', Activity, 'official_id'),),
        Territory: (('user', get_user_model(), 'service_recipient__territory_id'),),
        Delegation: (('territory', Territory, 'delegation_id'), ('official', Official, 'delegation_id'), ('activity', Activity, 'official__delegation_id')),
        Area: (('official', Official, 'area_id'),),
        Position: (('official', Official, 'position_id'),),
        Item: (('activity', Activity, 'item_id'),),
        AttentionType: (('subattention_type', SubattentionType, 'attention_type_id'),),
        ServiceType: (('attention_type', AttentionType, 'service_type_id'),),
        get_user_model(): (('official', Official, 'user_id'),),
    }
    for key, model, lookup in related.get(type(instance), ()):
        rows.update((key, pk) for pk in model.objects.filter(**{lookup: instance.pk}).values_list('pk', flat=True))
    return rows


WATCHED = tuple(MODELS.values()) + (SocialAttention, GroupProfile, ServiceType, ServiceRecipient)


def snapshot(instance):
    with _lock:
        if not _readers:
            return {}
    return {(key, pk): audience(key, pk) for key, pk in affected(instance)}


def security_users(instance):
    if isinstance(instance, get_user_model()):
        return {instance.pk}
    if isinstance(instance, Official):
        return {instance.user_id} if instance.user_id else set()
    if isinstance(instance, Role):
        return set(instance.officials.exclude(user=None).values_list('user_id', flat=True))
    if isinstance(instance, (Group, GroupProfile)):
        group = instance if isinstance(instance, Group) else instance.group
        return set(group.user_set.values_list('pk', flat=True))
    return set()


@receiver(pre_save)
@receiver(pre_delete)
def remember(sender, instance, raw=False, **kwargs):
    if sender in WATCHED and not raw:
        instance._list_audiences = snapshot(instance) if instance.pk else {}
        instance._security_users = security_users(instance) if instance.pk else set()


@receiver(post_save)
@receiver(post_delete)
def announce(sender, instance, raw=False, using='default', **kwargs):
    if sender not in WATCHED or raw:
        return
    with _lock:
        if not _readers:
            return
    previous = getattr(instance, '_list_audiences', {})
    rows = set(previous) | affected(instance)
    users = getattr(instance, '_security_users', set()) | security_users(instance)
    def committed():
        for key, pk in rows:
            publish(key, pk, previous.get((key, pk), set()))
        # Cambios del propio contexto/permisos: volver a autorizar antes de
        # refrescar, incluso cuando se perdieron todas las filas del ámbito.
        with _lock:
            subscriptions = tuple(_readers)
        for key, uid in subscriptions:
            if uid in users:
                send_notice(uid, key)
    transaction.on_commit(committed, using=using)


@receiver(m2m_changed)
def announce_relations(sender, instance, action, using='default', **kwargs):
    relations = [Official.roles.through, Official.authorized_delegations.through,
        Role.permissions.through, Group.permissions.through,
        get_user_model().groups.through, get_user_model().user_permissions.through]
    if sender not in relations:
        return
    if action.startswith('pre_'):
        instance._list_relation_audiences = snapshot(instance)
        instance._security_users = security_users(instance)
    elif action.startswith('post_'):
        instance._list_audiences = getattr(instance, '_list_relation_audiences', {})
        announce(type(instance), instance, using=using)
