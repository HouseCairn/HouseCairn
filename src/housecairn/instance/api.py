"""API of the instance administrator, for a signed-in administrator only (docs/adr/0022).

An API token never serves these endpoints, even one owned by an administrator:
administration needs a person signed in.
"""

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
from housecairn.instance import emails, services
from housecairn.instance.models import InstanceInvitation


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
