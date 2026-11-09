"""Web views of tasks, occurrences and attachments. Rules live in `services`."""

import datetime
from collections.abc import Iterable
from functools import cached_property
from typing import Any, cast
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import UUID

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.http import HttpRequest, HttpResponse
from django.http.response import HttpResponseBase
from django.shortcuts import get_object_or_404, redirect
from django.urls import Resolver404, resolve, reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _
from django.views import View
from django.views.generic import FormView, TemplateView

from housecairn.accounts import names
from housecairn.core import navigation
from housecairn.core.redirects import has_safe_shape
from housecairn.homes.models import Home
from housecairn.homes.scoping import open_homes_for_request
from housecairn.rooms import conf
from housecairn.rooms.models import Item, Room
from housecairn.rooms.views import HomeRoomsMixin
from housecairn.stock import services as stock_services
from housecairn.tasks import agenda, forms, services
from housecairn.tasks import materials as material_services
from housecairn.tasks.files import attachment_response
from housecairn.tasks.forms.materials import BaseMaterialFormSet
from housecairn.tasks.models import Attachment, Occurrence, Status, Task

PAGE_SIZE = 30


class EntryView(LoginRequiredMixin, TemplateView):
    """The Tasks entry of the navigation: the tasks of the user's only home, else a choice."""

    template_name = "tasks/choose_home.html"

    def get(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        homes = list(open_homes_for_request(request).order_by("name"))
        if len(homes) == 1:
            return redirect("tasks:list", home_id=homes[0].id)
        return self.render_to_response({"homes": homes})


class HomeTasksMixin(HomeRoomsMixin):
    """A page of one home: the home from the address, and whether the user may write."""

    def get_task(self) -> Task:
        task: Task = get_object_or_404(services.tasks_of(self.home), id=self.kwargs["task_id"])
        return task

    def get_occurrence(self) -> Occurrence:
        occurrence: Occurrence = get_object_or_404(
            services.occurrences_of(self.home),
            id=self.kwargs["occurrence_id"],
            task_id=self.kwargs["task_id"],
        )
        return occurrence

    def undo_banner(self) -> Occurrence | None:
        """The occurrence just closed, whose address came back in `?undo=`: it can be undone."""
        raw = self.request.GET.get("undo", "")
        try:
            pk = UUID(raw)
        except ValueError:
            return None
        found = services.occurrences_of(self.home).filter(
            pk=pk, status__in=[Status.DONE, Status.SKIPPED]
        )
        return found.first() if self.can_write else None

    def undo_return(self) -> str:
        """The address of this page as it is, filters and page included, minus `?undo=`.

        The banner sends it back as `next`, so that taking back a closing returns to the
        same list and not to an unfiltered first page.
        """
        return _with_query(self.request.get_full_path(), ("undo",))


def _url(name: str, **kwargs: object) -> str:
    return reverse(f"tasks:{name}", kwargs=kwargs)


def _back(request: HttpRequest, default: str) -> str:
    """Where to go after an action: the page it was sent from, if that is on this site.

    The rule of `core.redirects` (a safe shape, then Django's own check of host and scheme)
    is written out where the address is used, so that the check is on the value redirected to.
    """
    target = request.POST.get("next", "")
    if has_safe_shape(target) and url_has_allowed_host_and_scheme(
        target, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return target
    return default


def _with_query(url: str, drop: tuple[str, ...], add: list[tuple[str, str]] | None = None) -> str:
    """The address, without the query keys `drop` and with the pairs `add` at the end."""
    parts = urlsplit(url)
    query = [(k, v) for k, v in parse_qsl(parts.query) if k not in drop]
    return urlunsplit(parts._replace(query=urlencode(query + (add or []))))


def _with_undo(url: str, occurrence: Occurrence) -> str:
    """The address of the page, with `?undo=` naming the occurrence just closed."""
    return _with_query(url, ("undo",), [("undo", str(occurrence.id))])


def _errors(form: Any, exc: ValidationError) -> None:
    form.add_error(None, exc)


# ---------- the list ----------


class TaskListView(HomeTasksMixin, TemplateView):
    template_name = "tasks/task_list.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        status = "done" if self.request.GET.get("status") == "done" else "open"
        if status == "done":
            # Done is the history (docs/adr/0017): what was done or skipped, filtered.
            return super().get_context_data(
                **self.page(status=status, **_history(self.home, self.request)), **kwargs
            )
        day = services.today()
        show_hidden = self.request.GET.get("hidden") == "1" and status == "open"
        if status == "open":
            rows = services.open_occurrences(self.home, day=day, include_hidden=show_hidden)
        else:
            rows = services.done(self.home)
        room_id = self.request.GET.get("room", "")
        room = None
        if room_id:
            room = (
                services.rooms_for_forms(self.home).filter(pk=room_id).first()
                if _is_uuid(room_id)
                else None
            )
            rows = rows.filter(task__room=room) if room else rows.none()
        page = Paginator(rows, PAGE_SIZE).get_page(self.request.GET.get("page"))
        hidden = 0
        if status == "open" and not show_hidden:
            hidden = (
                services.open_occurrences(self.home, day=day, include_hidden=True).count()
                - services.open_occurrences(self.home, day=day).count()
            )
        return super().get_context_data(
            **self.page(
                status=status,
                page=page,
                today=day,
                rooms=services.rooms_for_forms(self.home),
                room=room,
                show_hidden=show_hidden,
                hidden_count=hidden,
                show_hidden_url=_with_query(
                    self.request.get_full_path(), ("undo", "hidden"), [("hidden", "1")]
                ),
                undo=self.undo_banner(),
                undo_return=self.undo_return(),
            ),
            **kwargs,
        )


def _is_uuid(raw: str) -> bool:
    try:
        UUID(raw)
    except ValueError:
        return False
    return True


# ---------- tasks ----------


class TaskFormMixin(HomeTasksMixin, FormView[Any]):
    require_write = True
    template_name = "tasks/task_form.html"
    form_class = forms.TaskForm
    with_files = True

    def get_form_kwargs(self) -> dict[str, Any]:
        kwargs = super().get_form_kwargs()
        kwargs.update(home=self.home, with_files=self.with_files)
        return kwargs

    def material_initial(self) -> list[dict[str, Any]]:
        return []

    @cached_property
    def materials(self) -> BaseMaterialFormSet:
        """The stock items of the task, a formset next to the form (docs/adr/0046)."""
        formset = forms.MaterialFormSet(
            self.request.POST if self.request.method == "POST" else None,
            prefix="materials",
            initial=self.material_initial(),
            form_kwargs={"articles": stock_services.articles_of(self.home)},
        )
        return cast(BaseMaterialFormSet, formset)

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        return super().get_context_data(**self.page(materials=self.materials), **kwargs)

    @cached_property
    def materials_sent(self) -> bool:
        """The form carried the stock items; a request without them leaves them as they are."""
        return "materials-TOTAL_FORMS" in self.request.POST

    def save_materials(self, task: Task) -> None:
        if self.materials_sent:
            material_services.set_materials(self.request.user, task, self.materials.lines())

    def post(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        form = self.get_form()
        valid = form.is_valid()
        if self.materials_sent:
            valid = self.materials.is_valid() and valid  # both are checked, to show both
        return self.form_valid(form) if valid else self.form_invalid(form)

    def split(self, form: forms.TaskForm) -> tuple[dict[str, Any], dict[str, Any]]:
        """Fields of the task, and the rest (date, new contractor, files)."""
        data = dict(form.cleaned_data)
        extra = {key: data.pop(key, None) for key in ("due_on", "contractor_name", "uploads")}
        return data, extra

    def contractor_of(self, data: dict[str, Any], extra: dict[str, Any]) -> None:
        """The single field: a known contractor is linked, a new name creates one."""
        data["contractor"] = services.contractor_named(
            self.request.user, self.home, extra["contractor_name"] or ""
        )


class TaskCreateView(TaskFormMixin):
    def get_initial(self) -> dict[str, Any]:
        initial: dict[str, Any] = {}
        item = self._pick(Item, "item")
        room = self._pick(Room, "room")
        if item:
            initial["item"], initial["room"] = item, item.room
        elif room:
            initial["room"] = room
        return initial

    def _pick(self, model: type[Item] | type[Room], key: str) -> Any:
        raw = self.request.GET.get(key, "")
        if not _is_uuid(raw):
            return None
        return model.objects.filter(home=self.home, pk=raw).first()

    def form_valid(self, form: forms.TaskForm) -> HttpResponse:
        data, extra = self.split(form)
        try:
            # One unit: a form refused leaves no contractor, and no audit line, behind.
            with transaction.atomic():
                self.contractor_of(data, extra)
                task = services.create_task(
                    self.request.user, self.home, due_on=extra["due_on"], **data
                )
                self.save_materials(task)
        except ValidationError as exc:
            _errors(form, exc)
            return self.form_invalid(form)
        refused = []
        for upload in extra["uploads"] or []:
            try:
                services.add_attachment(self.request.user, task, upload=upload)
            except ValidationError as exc:
                refused.append(f"{upload.name}: {' '.join(exc.messages)}")
        target = navigation.after_create(
            self.request,
            _url("detail", home_id=self.home.id, task_id=task.id),
            "tasks:list",
            added=_("Task added"),
            saved=_("Task added."),
        )
        for line in refused:
            messages.error(self.request, _("File not added: %(reason)s") % {"reason": line})
        return redirect(target)


class TaskDetailView(HomeTasksMixin, TemplateView):
    template_name = "tasks/task_detail.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        task = self.get_task()
        current = services.open_occurrence_of(task)
        closed = list(
            services.occurrences_of(self.home)
            .filter(task=task, status__in=[Status.DONE, Status.SKIPPED])
            .order_by("-completed_on", "-updated_at", "-id")[:20]
        )
        attachments = list(task.attachments.all())
        return super().get_context_data(
            **self.page(
                task=task,
                current=current,
                last_closed=closed[0] if closed and current is None else None,
                history=closed,
                today=services.today(),
                next_dates=services.upcoming_dates(task),
                materials=material_services.materials_of(task),
                material_form=forms.MaterialSaveForm(
                    articles=stock_services.articles_of(self.home)
                ),
                images=[a for a in attachments if a.is_image],
                documents=[a for a in attachments if not a.is_image],
                undo=self.undo_banner(),
                undo_return=self.undo_return(),
            ),
            **kwargs,
        )


class TaskEditView(TaskFormMixin):
    with_files = False

    def get_form_kwargs(self) -> dict[str, Any]:
        kwargs = super().get_form_kwargs()
        kwargs["instance"] = self.get_task()
        return kwargs

    def material_initial(self) -> list[dict[str, Any]]:
        return [
            {"article": line.article_id, "quantity": line.quantity}
            for line in material_services.materials_of(self.get_task())
        ]

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        return super().get_context_data(task=self.get_task(), **kwargs)

    def form_valid(self, form: forms.TaskForm) -> HttpResponse:
        task = self.get_task()
        data, extra = self.split(form)
        try:
            with transaction.atomic():
                self.contractor_of(data, extra)
                services.update_task(self.request.user, task, due_on=extra["due_on"], **data)
                self.save_materials(task)
        except ValidationError as exc:
            _errors(form, exc)
            return self.form_invalid(form)
        messages.success(self.request, _("Task saved."))
        return redirect(
            navigation.back_url(self.request, _url("detail", home_id=self.home.id, task_id=task.id))
        )


class TaskDeleteView(HomeTasksMixin, TemplateView):
    """A page that asks, then a POST that deletes: no script is needed to confirm."""

    require_write = True
    template_name = "tasks/confirm_delete.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        task = self.get_task()
        cancel_url = _url("detail", home_id=self.home.id, task_id=task.id)
        return super().get_context_data(
            **self.page(task=task, cancel_url=navigation.back_url(self.request, cancel_url)),
            **kwargs,
        )

    def post(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        task = self.get_task()
        gone = [task.id, *task.occurrences.values_list("id", flat=True)]
        gone += list(task.attachments.values_list("id", flat=True))
        services.delete_task(request.user, task)
        messages.success(request, _("Task deleted."))
        parent = _url("list", home_id=self.home.id)
        return redirect(navigation.after_delete(request, parent, gone))


class MaterialSaveView(HomeTasksMixin, View):
    """Add a stock item to the task, or change its quantity (the form of the task page)."""

    require_write = True
    http_method_names = ["post"]

    def post(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        task = self.get_task()
        form = forms.MaterialSaveForm(request.POST, articles=stock_services.articles_of(self.home))
        target = redirect("tasks:detail", home_id=self.home.id, task_id=task.id)
        if not form.is_valid():
            messages.error(
                request, " ".join(str(m) for errors in form.errors.values() for m in errors)
            )
            return target
        try:
            material_services.save_material(
                request.user, task, form.cleaned_data["article"], form.cleaned_data["quantity"]
            )
        except ValidationError as exc:
            messages.error(request, " ".join(exc.messages))
            return target
        messages.success(request, _("Stock item saved on the task."))
        return target


class MaterialRemoveView(HomeTasksMixin, View):
    require_write = True
    http_method_names = ["post"]

    def post(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        task = self.get_task()
        line = get_object_or_404(
            material_services.materials_of(task), id=self.kwargs["material_id"]
        )
        material_services.remove_material(request.user, line)
        messages.success(request, _("Stock item removed from the task."))
        return redirect("tasks:detail", home_id=self.home.id, task_id=task.id)


# ---------- occurrences ----------


class OccurrenceActionView(HomeTasksMixin, View):
    """A button: one POST, then back to the page it came from."""

    require_write = True
    http_method_names = ["post"]

    def act(self, occurrence: Occurrence) -> Occurrence | None:
        raise NotImplementedError  # pragma: no cover

    def post(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        occurrence = self.get_occurrence()
        default = _url("detail", home_id=self.home.id, task_id=occurrence.task_id)
        try:
            banner = self.act(occurrence)
        except ValidationError as exc:
            messages.error(request, " ".join(exc.messages))
            return redirect(_back(request, default))
        target = _back(request, default)
        return redirect(_with_undo(target, banner) if banner else target)


def short_message(short: Iterable[material_services.Shortage]) -> str:
    """What the stock could not give when a task was marked done, one line."""
    listed = ", ".join(
        _("%(name)s: %(drawn)s of %(wanted)s")
        % {
            "name": s.article.name,
            "drawn": stock_services.plain(s.drawn),
            "wanted": stock_services.plain(s.wanted),
        }
        for s in short
    )
    return _("Not enough in stock, the stock is at zero: %(list)s.") % {"list": listed}


class OccurrenceCompleteView(OccurrenceActionView):
    def act(self, occurrence: Occurrence) -> Occurrence:
        closing = services.complete(self.request.user, occurrence)
        if closing.short:
            messages.warning(self.request, short_message(closing.short))
        return closing.occurrence


class OccurrenceSkipView(OccurrenceActionView):
    def act(self, occurrence: Occurrence) -> Occurrence:
        return services.skip(self.request.user, occurrence).occurrence


class OccurrenceUndoView(OccurrenceActionView):
    def act(self, occurrence: Occurrence) -> None:
        services.undo(self.request.user, occurrence)
        messages.success(self.request, _("Undone."))


class OccurrencePostponeView(HomeTasksMixin, FormView[Any]):
    require_write = True
    template_name = "tasks/postpone_form.html"
    form_class = forms.PostponeForm

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        occurrence = self.get_occurrence()
        return super().get_context_data(
            **self.page(task=occurrence.task, occurrence=occurrence), **kwargs
        )

    def get_initial(self) -> dict[str, Any]:
        return {"due_on": services.today() + datetime.timedelta(days=1)}

    def form_valid(self, form: forms.PostponeForm) -> HttpResponse:
        occurrence = self.get_occurrence()
        try:
            services.postpone(self.request.user, occurrence, form.cleaned_data["due_on"])
        except ValidationError as exc:
            _errors(form, exc)
            return self.form_invalid(form)
        messages.success(self.request, _("Task postponed."))
        return redirect("tasks:detail", home_id=self.home.id, task_id=occurrence.task_id)


class OccurrenceEditView(HomeTasksMixin, FormView[Any]):
    """The details of a task that is done: the date, the real cost, a note."""

    require_write = True
    template_name = "tasks/completion_form.html"
    form_class = forms.CompletionForm

    def get_form_kwargs(self) -> dict[str, Any]:
        kwargs = super().get_form_kwargs()
        occurrence = self.get_occurrence()
        kwargs.update(instance=occurrence, draws=material_services.draws_of(occurrence))
        return kwargs

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        occurrence = self.get_occurrence()
        return super().get_context_data(
            **self.page(task=occurrence.task, occurrence=occurrence), **kwargs
        )

    def form_valid(self, form: forms.CompletionForm) -> HttpResponse:
        occurrence = self.get_occurrence()
        try:
            services.update_occurrence(
                self.request.user, occurrence, used=form.used(), **form.completion()
            )
        except ValidationError as exc:
            _errors(form, exc)
            return self.form_invalid(form)
        messages.success(self.request, _("Details saved."))
        return redirect("tasks:detail", home_id=self.home.id, task_id=occurrence.task_id)


# ---------- Today, My home, History, display preferences ----------


class TodayView(HomeTasksMixin, TemplateView):
    """What to do in a home, laid out as the person asked (docs/adr/0037)."""

    template_name = "tasks/today.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        day = services.today()
        prefs = agenda.preferences_of(self.request.user)  # type: ignore[arg-type]
        return super().get_context_data(
            **self.page(
                sections=agenda.today_sections(self.home, prefs, day=day),
                prefs=prefs,
                show_person=prefs.today_group != "person",
                today=day,
                undo=self.undo_banner(),
                undo_return=self.undo_return(),
            ),
            **kwargs,
        )


class MyHomeView(LoginRequiredMixin, TemplateView):
    """What concerns the person signed in, in one home or in all of them."""

    template_name = "tasks/my_home.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        homes = list(open_homes_for_request(self.request).order_by("name"))
        raw = self.request.GET.get("home", "")
        chosen = next((h for h in homes if str(h.id) == raw), None)
        shown = [chosen] if chosen else homes
        return super().get_context_data(
            homes=homes,
            chosen=chosen,
            digests=agenda.my_home(self.request.user, shown, day=services.today()),  # type: ignore[arg-type]
            today=services.today(),
            **kwargs,
        )


def _uuid_or_none(raw: str) -> UUID | None:
    try:
        return UUID(raw)
    except ValueError:
        return None


def _date_or_none(raw: str) -> datetime.date | None:
    try:
        return datetime.date.fromisoformat(raw)
    except ValueError:
        return None


# The filters of the history, and the name each one has in the address of the list.
HISTORY_FILTERS = ("q", "room", "item", "contractor", "person", "outcome", "after", "before")


def _history(home: Home, request: HttpRequest) -> dict[str, Any]:
    """Everything that was done or skipped, filtered and searched, with its real cost."""
    params = request.GET
    outcome = params.get("outcome", "")
    selection = agenda.HistoryFilter(
        room=_uuid_or_none(params.get("room", "")),
        item=_uuid_or_none(params.get("item", "")),
        contractor=_uuid_or_none(params.get("contractor", "")),
        person=_uuid_or_none(params.get("person", "")),
        query=params.get("q", "").strip()[:200],
        status=outcome if outcome in ("done", "skipped") else "",
        after=_date_or_none(params.get("after", "")),
        before=_date_or_none(params.get("before", "")),
    )
    rows = agenda.history(home, selection)
    page = Paginator(rows, PAGE_SIZE).get_page(params.get("page"))
    kept = [(k, v) for k, v in params.items() if k in HISTORY_FILTERS and v]
    members = list(services.members_for_forms(home))
    shown = names.labels(members)
    people = [{"id": m.pk, "label": shown[m.pk]} for m in members]
    return {
        "page": page,
        "selection": selection,
        "cost": agenda.cost_of(rows),
        "rooms": services.rooms_for_forms(home),
        "items": services.items_for_forms(home),
        "contractors": services.contractors_of(home),
        "members": people,
        "query_string": urlencode([("status", "done"), *kept]),
        "filtered": bool(kept),
    }


class HistoryView(HomeTasksMixin, View):
    """The former address of the history: the Done filter of the task list (docs/adr/0017).

    The filters follow, the outcome under its new name (`status` became `outcome`).
    """

    def get(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        renamed = {"status": "outcome"}
        query = [("status", "done")] + [
            (renamed.get(k, k), v)
            for k, v in request.GET.items()
            if renamed.get(k, k) in (*HISTORY_FILTERS, "page") and v
        ]
        return redirect(f"{_url('list', home_id=self.home.id)}?{urlencode(query)}")


class PreferencesView(LoginRequiredMixin, FormView[Any]):
    """How the Today screen is laid out, for the person signed in."""

    template_name = "tasks/preferences.html"
    form_class = forms.PreferencesForm

    def get_form_kwargs(self) -> dict[str, Any]:
        kwargs = super().get_form_kwargs()
        kwargs["instance"] = agenda.preferences_of(self.request.user)  # type: ignore[arg-type]
        return kwargs

    def _next(self) -> str:
        target = self.request.POST.get("next") or self.request.GET.get("next", "")
        if has_safe_shape(target) and url_has_allowed_host_and_scheme(
            target, allowed_hosts={self.request.get_host()}, require_https=self.request.is_secure()
        ):
            return target
        return reverse("my-home")

    def _home(self) -> Home | None:
        """The home the person came from, if `next` is a page of one they may open.

        Only for the tabs of its tasks; it reads nothing from the address but the home.
        """
        try:
            match = resolve(urlsplit(self._next()).path)
        except Resolver404:
            return None
        home_id = match.kwargs.get("home_id")
        if home_id is None:
            return None
        return open_homes_for_request(self.request).filter(id=home_id).first()

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(next=self._next(), home=self._home(), **kwargs)
        form = context["form"]
        context["sections"] = [form["show_overdue"], form["show_upcoming"], form["show_season"]]
        return context

    def form_valid(self, form: forms.PreferencesForm) -> HttpResponse:
        agenda.update_preferences(self.request.user, **form.cleaned_data)
        messages.success(self.request, _("Preferences saved."))
        return redirect(self._next())


# ---------- attachments ----------


class AttachmentAddView(HomeTasksMixin, FormView[Any]):
    require_write = True
    template_name = "tasks/attachment_form.html"
    form_class = forms.AttachmentForm

    def post(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        # Refuse an oversized body before reading any of it (files of a few MB each).
        declared = int(request.META.get("CONTENT_LENGTH") or 0)
        if declared > conf.photo_max_bytes() * 5 + conf.MULTIPART_OVERHEAD:
            return HttpResponse(_("This file is too large."), status=413, content_type="text/plain")
        return super().post(request, *args, **kwargs)

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        return super().get_context_data(
            **self.page(task=self.get_task(), max_bytes=conf.photo_max_bytes()), **kwargs
        )

    def form_valid(self, form: forms.AttachmentForm) -> HttpResponse:
        task = self.get_task()
        added = 0
        for upload in form.cleaned_data["uploads"]:
            try:
                services.add_attachment(self.request.user, task, upload=upload)
                added += 1
            except ValidationError as exc:
                form.add_error("uploads", f"{upload.name}: {' '.join(exc.messages)}")
        if form.errors:
            if added:
                messages.success(self.request, _("Some files were added."))
            return self.form_invalid(form)
        messages.success(self.request, _("Files added."))
        return redirect("tasks:detail", home_id=self.home.id, task_id=task.id)


class AttachmentFileView(HomeTasksMixin, View):
    """The file itself, or the thumbnail of an image: only to the members of its home."""

    thumbnail = False
    http_method_names = ["get", "head"]

    def get(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponseBase:
        attachment = get_object_or_404(
            services.attachments_of(self.home), id=self.kwargs["attachment_id"]
        )
        return attachment_response(attachment, thumbnail=self.thumbnail)


class AttachmentThumbnailView(AttachmentFileView):
    thumbnail = True


class AttachmentDeleteView(HomeTasksMixin, View):
    require_write = True
    http_method_names = ["post"]

    def post(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        attachment: Attachment = get_object_or_404(
            services.attachments_of(self.home), id=self.kwargs["attachment_id"]
        )
        services.delete_attachment(request.user, attachment)
        messages.success(request, _("File deleted."))
        return redirect("tasks:detail", home_id=self.home.id, task_id=attachment.task_id)
