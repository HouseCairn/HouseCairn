"""Web views of the contractors of a home: list, sheet, form, deletion, contact file.

Rules live in `services`; reading is open to every member, writing to those who may write
(docs/adr/0045).
"""

from typing import Any

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.utils.translation import gettext as _
from django.views import View
from django.views.generic import FormView, TemplateView

from housecairn.tasks import forms, services, vcard
from housecairn.tasks.models import Contractor
from housecairn.tasks.views import HomeTasksMixin


class HomeContractorsMixin(HomeTasksMixin):
    def get_contractor(self) -> Contractor:
        contractor: Contractor = get_object_or_404(
            services.contractors_of(self.home), id=self.kwargs["contractor_id"]
        )
        return contractor


class ContractorListView(HomeContractorsMixin, TemplateView):
    template_name = "tasks/contractor_list.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        return super().get_context_data(
            **self.page(contractors=services.contractors_of(self.home)), **kwargs
        )


class ContractorDetailView(HomeContractorsMixin, TemplateView):
    template_name = "tasks/contractor_detail.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        contractor = self.get_contractor()
        return super().get_context_data(
            **self.page(
                contractor=contractor, tasks=list(services.tasks_of_contractor(contractor)[:50])
            ),
            **kwargs,
        )


class ContractorFormMixin(HomeContractorsMixin, FormView[forms.ContractorForm]):
    require_write = True
    template_name = "tasks/contractor_form.html"
    form_class = forms.ContractorForm

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        return super().get_context_data(**self.page(), **kwargs)


class ContractorCreateView(ContractorFormMixin):
    def form_valid(self, form: forms.ContractorForm) -> HttpResponse:
        try:
            contractor = services.create_contractor(
                self.request.user, self.home, **form.cleaned_data
            )
        except ValidationError as exc:
            form.add_error(None, exc)
            return self.form_invalid(form)
        messages.success(self.request, _("Contractor added."))
        return redirect(
            "tasks:contractor-detail", home_id=self.home.id, contractor_id=contractor.id
        )


class ContractorEditView(ContractorFormMixin):
    def get_form_kwargs(self) -> dict[str, Any]:
        return {**super().get_form_kwargs(), "instance": self.get_contractor()}

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        return super().get_context_data(contractor=self.get_contractor(), **kwargs)

    def form_valid(self, form: forms.ContractorForm) -> HttpResponse:
        contractor = self.get_contractor()
        try:
            services.update_contractor(self.request.user, contractor, **form.cleaned_data)
        except ValidationError as exc:
            form.add_error(None, exc)
            return self.form_invalid(form)
        messages.success(self.request, _("Contractor saved."))
        return redirect(
            "tasks:contractor-detail", home_id=self.home.id, contractor_id=contractor.id
        )


class ContractorDeleteView(HomeContractorsMixin, TemplateView):
    """A page that asks, then a POST that deletes: no script is needed to confirm."""

    require_write = True
    template_name = "tasks/contractor_confirm_delete.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        return super().get_context_data(**self.page(contractor=self.get_contractor()), **kwargs)

    def post(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        services.delete_contractor(request.user, self.get_contractor())
        messages.success(request, _("Contractor deleted."))
        return redirect("tasks:contractors", home_id=self.home.id)


class ContractorVcardView(HomeContractorsMixin, View):
    """The contact file of a contractor, for any member of the home (reading is enough)."""

    http_method_names = ["get", "head"]

    def get(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        return vcard.response(self.get_contractor())
