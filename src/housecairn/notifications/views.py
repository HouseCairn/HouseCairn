"""Web views of notifications: the person's channels and reminder preferences (docs/adr/0043).

Rules live in `services`. A channel is looked up among the channels of the person signed
in: someone else's, an administrator's included, is a 404 like a channel that does not exist.
"""

import json
from typing import Any

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ValidationError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View
from django.views.generic import TemplateView

from housecairn.notifications import catalog, forms, services
from housecairn.notifications.models import Channel, SendState

# The status of a test is asked again every two seconds, at most this many times; then the
# page says to reload it (docs/adr/0070). Without script, the page is reloaded by hand.
TEST_POLLS = 12


def _errors(form: Any, exc: ValidationError) -> None:
    if hasattr(exc, "error_dict"):
        for field, errors in exc.message_dict.items():
            form.add_error(field if field in form.fields else None, errors)
    else:
        form.add_error(None, exc.messages)


class IndexView(LoginRequiredMixin, TemplateView):
    template_name = "notifications/index.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        prefs = services.preferences_of(self.request.user)  # type: ignore[arg-type]
        context: dict[str, Any] = {
            "enabled": services.is_enabled(),
            "channels": services.channels_of(self.request.user),
            "add_form": forms.ChannelForm(),
            "families": catalog.by_family(),
            "preference_form": forms.PreferenceForm(instance=prefs),
        }
        return super().get_context_data(**{**context, **kwargs})


class AddView(LoginRequiredMixin, View):
    def post(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        form = forms.ChannelForm(request.POST)
        if form.is_valid():
            try:
                services.add_channel(request.user, **form.cleaned_data)
            except ValidationError as exc:
                _errors(form, exc)
            else:
                messages.success(request, services.ADDED)
                return redirect("notifications:index")
        page = IndexView(request=request, kwargs={})
        return page.render_to_response(page.get_context_data(add_form=form), status=422)


class ChannelMixin(LoginRequiredMixin):
    request: HttpRequest
    kwargs: dict[str, Any]

    def get_channel(self) -> Channel:
        channel: Channel = get_object_or_404(
            services.channels_of(self.request.user), id=self.kwargs["channel_id"]
        )
        return channel


class ChannelView(ChannelMixin, TemplateView):
    template_name = "notifications/channel.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        channel = services.expire_test(self.get_channel())
        form = kwargs.pop("form", None) or forms.ChannelEditForm(
            initial={"name": channel.name, "enabled": channel.enabled}
        )
        return super().get_context_data(
            channel=channel, form=form, **_test_context(channel, 0), **kwargs
        )

    def post(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        channel = self.get_channel()
        form = forms.ChannelEditForm(request.POST)
        if form.is_valid():
            try:
                services.update_channel(request.user, channel, **form.cleaned_data)
            except ValidationError as exc:
                _errors(form, exc)
            else:
                messages.success(request, services.SAVED)
                return redirect("notifications:index")
        return self.render_to_response(self.get_context_data(form=form), status=422)


def _test_context(channel: Channel, polls: int) -> dict[str, Any]:
    """What the status of the last test shows; `polls` already made by the page."""
    return {
        "test_state": channel.test_state,
        "test_text": services.test_result(channel),
        "test_polling": channel.test_state == SendState.RUNNING and polls < TEST_POLLS,
        "test_next": polls + 1,
    }


class TestView(ChannelMixin, View):
    """Queue the test and go back to the channel: the page shows it running, then its end."""

    def post(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        channel = self.get_channel()
        try:
            services.start_test(request.user, channel)
        except ValidationError as exc:
            messages.error(request, " ".join(exc.messages))
        return redirect("notifications:channel", channel_id=channel.id)


class TestStatusView(ChannelMixin, View):
    """The status of the last test, as a fragment that the page asks for again while it runs."""

    def get(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        channel = services.expire_test(self.get_channel())
        try:
            polls = max(0, min(int(request.GET.get("n", "0")), TEST_POLLS))
        except ValueError:
            polls = 0
        response = render(
            request,
            "notifications/_test_status.html",
            {"channel": channel, **_test_context(channel, polls)},
        )
        response["Cache-Control"] = "no-store"
        return response


class DeleteView(ChannelMixin, View):
    def post(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        services.delete_channel(request.user, self.get_channel())
        messages.success(request, services.DELETED)
        return redirect("notifications:index")


class PreferencesView(LoginRequiredMixin, View):
    def post(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        prefs = services.preferences_of(request.user)  # type: ignore[arg-type]
        form = forms.PreferenceForm(request.POST, instance=prefs)
        if form.is_valid():
            try:
                services.update_preferences(
                    request.user, **{f: form.cleaned_data[f] for f in form.Meta.fields}
                )
            except ValidationError as exc:
                _errors(form, exc)
            else:
                messages.success(request, services.SAVED)
                return redirect("notifications:index")
        page = IndexView(request=request, kwargs={})
        return page.render_to_response(page.get_context_data(preference_form=form), status=422)


class ExportView(LoginRequiredMixin, View):
    def get(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        body = json.dumps(services.export_of(request.user), indent=2, ensure_ascii=False)
        response = HttpResponse(body, content_type="application/json")
        response["Content-Disposition"] = 'attachment; filename="notifications.json"'
        return response
