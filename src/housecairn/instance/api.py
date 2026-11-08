"""API of the instance administrator, for a signed-in administrator only (docs/adr/0022).

An API token never serves these endpoints, even one owned by an administrator:
administration needs a person signed in.
"""

from collections.abc import Iterable
from typing import Any

from django.core.exceptions import PermissionDenied
from django.core.exceptions import ValidationError as DjangoValidationError
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import exceptions, mixins, permissions, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from housecairn.accounts.services import email_is_configured, is_instance_admin
from housecairn.apitokens.models import ApiToken
from housecairn.audit import services as audit
from housecairn.audit.api import AuditEventSerializer
from housecairn.audit.models import AuditEvent
from housecairn.homes import sso
from housecairn.homes.scoping import allow
from housecairn.instance import config, emails, registry, services, settings_services
from housecairn.instance.models import InstanceInvitation
from housecairn.instance.reauth import signed_in_recently


class InstanceAdminOnly(permissions.BasePermission):
    message = "Instance administration needs an administrator signed in; API tokens cannot."

    def has_permission(self, request: Request, view: Any) -> bool:
        if isinstance(request.auth, ApiToken):
            return False
        return is_instance_admin(request.user)


class InstanceInvitationSerializer(serializers.ModelSerializer[InstanceInvitation]):
    class Meta:
        model = InstanceInvitation
        fields = ["id", "email", "sent_at", "expires_at"]
        read_only_fields = ["id", "sent_at", "expires_at"]


def _validation(exc: DjangoValidationError) -> serializers.ValidationError:
    return serializers.ValidationError({"detail": exc.messages})


class InstanceInvitationViewSet(
    mixins.ListModelMixin, mixins.CreateModelMixin, viewsets.GenericViewSet[InstanceInvitation]
):
    """Pending invitations to the instance. They are sent by email, never returned."""

    serializer_class = InstanceInvitationSerializer
    permission_classes = [InstanceAdminOnly]
    queryset = InstanceInvitation.objects.none()
    lookup_field = "id"
    lookup_url_kwarg = "invitation_id"
    http_method_names = ["get", "post", "delete", "head", "options"]

    def get_queryset(self) -> Any:
        return services.pending_invitations()

    def _send(self) -> Any:
        if not email_is_configured():
            raise exceptions.ValidationError(
                {"detail": ["This instance cannot send email, so it cannot invite by link."]}
            )
        if not allow(self.request, "housecairn_instance_invite"):
            raise exceptions.Throttled()
        return emails.sender_for(self.request)

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        send = self._send()
        try:
            invitation = services.invite(
                request.user,  # type: ignore[arg-type]
                email=serializer.validated_data["email"],
                send=send,
            )
        except DjangoValidationError as exc:
            raise _validation(exc) from exc
        return Response(self.get_serializer(invitation).data, status=status.HTTP_201_CREATED)

    def destroy(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Revoke the invitation: its link stops working."""
        invitation = get_object_or_404(InstanceInvitation.objects.all(), id=kwargs["invitation_id"])
        services.revoke(request.user, invitation)  # type: ignore[arg-type]
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(request=None, responses={200: InstanceInvitationSerializer})
    @action(detail=True, methods=["post"])
    def resend(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """A new link and a new expiry; the previous link stops working."""
        invitation = get_object_or_404(InstanceInvitation.objects.all(), id=kwargs["invitation_id"])
        send = self._send()
        try:
            invitation = services.resend(
                request.user,  # type: ignore[arg-type]
                invitation,
                send=send,
            )
        except DjangoValidationError as exc:
            raise _validation(exc) from exc
        return Response(self.get_serializer(invitation).data)


class InstanceAuditView(mixins.ListModelMixin, viewsets.GenericViewSet[AuditEvent]):
    """Audit log of the instance: administration, invitations, accounts. No home content."""

    serializer_class = AuditEventSerializer
    permission_classes = [InstanceAdminOnly]
    queryset = AuditEvent.objects.none()

    def get_queryset(self) -> Any:
        return audit.instance_log(self.request.user)


class UnlockHomesView(APIView):
    """Clear the sign-in rule of every home whose provider the instance no longer offers."""

    permission_classes = [InstanceAdminOnly]

    @extend_schema(
        request=None,
        responses={200: inline_serializer("Unlocked", {"unlocked": serializers.IntegerField()})},
    )
    def post(self, request: Request) -> Response:
        try:
            count = services.unlock_removed_providers(
                request.user,  # type: ignore[arg-type]
                declared=[p.id for p in sso.declared_providers(request)],
            )
        except PermissionDenied as exc:  # pragma: no cover - the permission class refuses first
            raise exceptions.PermissionDenied() from exc
        return Response({"unlocked": count})


def _setting_field(setting: registry.Setting) -> serializers.Field[Any, Any, Any, Any]:
    kind = setting.kind
    options: dict[str, Any] = {"required": False, "help_text": str(setting.help)}
    if kind is registry.Kind.BOOL:
        return serializers.BooleanField(**options)
    if kind is registry.Kind.INT:
        return serializers.IntegerField(
            min_value=setting.minimum,  # type: ignore[arg-type]
            max_value=setting.maximum,  # type: ignore[arg-type]
            **options,
        )
    if kind is registry.Kind.CHOICE:
        return serializers.ChoiceField(choices=list(setting.choices), **options)
    if kind is registry.Kind.LIST:
        return serializers.ListField(child=serializers.CharField(max_length=253), **options)
    if kind is registry.Kind.SECRET:
        return serializers.CharField(write_only=True, max_length=1024, **options)
    return serializers.CharField(allow_blank=True, max_length=1024, **options)


SettingsUpdateSerializer = type(
    "SettingsUpdate",
    (serializers.Serializer,),
    {s.key: _setting_field(s) for s in registry.SETTINGS.values()},
)

SettingSerializer = inline_serializer(
    "InstanceSetting",
    {
        "key": serializers.CharField(),
        "section": serializers.CharField(),
        "kind": serializers.ChoiceField(choices=[k.value for k in registry.Kind]),
        "label": serializers.CharField(),
        "value": serializers.JSONField(
            allow_null=True, help_text="Null for a secret, which is never returned."
        ),
        "default": serializers.JSONField(allow_null=True),
        "source": serializers.ChoiceField(choices=["environment", "database", "default"]),
        "locked": serializers.BooleanField(
            help_text="True when an environment variable sets it: it cannot be changed here."
        ),
        "environment_variable": serializers.CharField(),
        "reload": serializers.ChoiceField(choices=[r.value for r in registry.Reload]),
        "secret_set": serializers.BooleanField(
            allow_null=True, help_text="For a secret only: whether one is in force."
        ),
        "minimum": serializers.IntegerField(allow_null=True),
        "maximum": serializers.IntegerField(allow_null=True),
        "choices": serializers.ListField(child=serializers.CharField()),
    },
)
SettingsListSerializer = inline_serializer(
    "InstanceSettings", {"settings": serializers.ListField(child=SettingSerializer)}
)


def _setting_json(key: str) -> dict[str, Any]:
    state = config.describe(key)
    setting = state.setting
    return {
        "key": key,
        "section": setting.section.value,
        "kind": setting.kind.value,
        "label": str(setting.label),
        "value": state.value,
        "default": None if setting.secret else setting.default,
        "source": state.source,
        "locked": state.locked,
        "environment_variable": setting.env,
        "reload": setting.reload.value,
        "secret_set": state.is_set if setting.secret else None,
        "minimum": setting.minimum,
        "maximum": setting.maximum,
        "choices": list(setting.choices),
    }


def _all_settings() -> dict[str, Any]:
    return {"settings": [_setting_json(key) for key in registry.SETTINGS]}


def _needs_recent_sign_in(request: Request) -> Response | None:
    if signed_in_recently(request._request):
        return None
    return Response(
        {
            "detail": "Sign in again to change settings.",
            "code": "reauthentication_required",
        },
        status=status.HTTP_403_FORBIDDEN,
    )


def _locked(keys: Iterable[str]) -> Response | None:
    locked = sorted(k for k in keys if k in registry.SETTINGS and config.is_locked(k))
    if not locked:
        return None
    return Response(
        {
            "detail": "A setting is set by an environment variable: change it there.",
            "code": "locked_by_environment",
            "locked": locked,
        },
        status=status.HTTP_409_CONFLICT,
    )


class InstanceSettingsView(APIView):
    """Settings of the instance, paired with environment variables (docs/adr/0031).

    Reading needs an administrator signed in; changing also needs a recent sign-in. A setting
    that a variable sets is `locked` and refuses writes. Secrets are write-only.
    """

    permission_classes = [InstanceAdminOnly]

    @extend_schema(responses={200: SettingsListSerializer})
    def get(self, request: Request) -> Response:
        return Response(_all_settings())

    @extend_schema(request=SettingsUpdateSerializer, responses={200: SettingsListSerializer})
    def patch(self, request: Request) -> Response:
        if (refused := _needs_recent_sign_in(request)) is not None:
            return refused
        if not isinstance(request.data, dict):
            raise exceptions.ValidationError({"detail": ["Expected an object."]})
        if (conflict := _locked(request.data)) is not None:
            return conflict
        serializer = SettingsUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        unknown = sorted(set(request.data) - set(registry.SETTINGS))
        if unknown:
            raise exceptions.ValidationError({k: ["Unknown setting."] for k in unknown})
        try:
            settings_services.update(request.user, dict(serializer.validated_data))  # type: ignore[arg-type]
        except DjangoValidationError as exc:
            raise exceptions.ValidationError(exc.message_dict) from exc
        return Response(_all_settings())


class InstanceSettingResetView(APIView):
    """Restore the default of one setting: the stored value is removed."""

    permission_classes = [InstanceAdminOnly]

    @extend_schema(request=None, responses={204: None})
    def delete(self, request: Request, key: str) -> Response:
        if key not in registry.SETTINGS:
            raise exceptions.NotFound()
        if (refused := _needs_recent_sign_in(request)) is not None:
            return refused
        if (conflict := _locked([key])) is not None:
            return conflict
        settings_services.reset(request.user, key)  # type: ignore[arg-type]
        return Response(status=status.HTTP_204_NO_CONTENT)


class InstanceEmailTestView(APIView):
    """Connect to the mail server with the settings in force, to check them; sends nothing."""

    permission_classes = [InstanceAdminOnly]

    @extend_schema(
        request=None,
        responses={
            200: inline_serializer(
                "EmailTest", {"ok": serializers.BooleanField(), "detail": serializers.CharField()}
            )
        },
    )
    def post(self, request: Request) -> Response:
        if not allow(request, "housecairn_settings_test"):
            raise exceptions.Throttled()
        ok, detail = settings_services.check_email(request.user)  # type: ignore[arg-type]
        return Response({"ok": ok, "detail": detail})
