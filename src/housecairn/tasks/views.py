"""Web views of tasks and occurrences. Rules live in `services`."""

import datetime
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import UUID

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _
from django.views import View
from django.views.generic import FormView, TemplateView

from housecairn.homes.scoping import open_homes_for_request
from housecairn.rooms.models import Item, Room
from housecairn.rooms.views import HomeRoomsMixin
from housecairn.tasks import agenda, forms, services
from housecairn.tasks.models import Occurrence, Status, Task

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
    """Where to go after an action: the page it was sent from, if that is on this site."""
    target = request.POST.get("next", "")
    if target and url_has_allowed_host_and_scheme(
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

    def get_form_kwargs(self) -> dict[str, Any]:
        kwargs = super().get_form_kwargs()
        kwargs.update(home=self.home)
        return kwargs

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        return super().get_context_data(**self.page(), **kwargs)

    def split(self, form: forms.TaskForm) -> tuple[dict[str, Any], dict[str, Any]]:
        """Fields of the task, and the rest (date, new contractor)."""
        data = dict(form.cleaned_data)
        extra = {
            key: data.pop(key, None) for key in ("due_on", "new_contractor", "new_contractor_trade")
        }
        return data, extra

    def contractor_of(self, data: dict[str, Any], extra: dict[str, Any]) -> None:
        if extra["new_contractor"]:
            data["contractor"] = services.create_contractor(
                self.request.user,
                self.home,
                name=extra["new_contractor"],
                trade=extra["new_contractor_trade"] or "",
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
            self.contractor_of(data, extra)
            task = services.create_task(
                self.request.user, self.home, due_on=extra["due_on"], **data
            )
        except ValidationError as exc:
            _errors(form, exc)
            return self.form_invalid(form)
        messages.success(self.request, _("Task added."))
        return redirect("tasks:detail", home_id=self.home.id, task_id=task.id)


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
        return super().get_context_data(
            **self.page(
                task=task,
                current=current,
                last_closed=closed[0] if closed and current is None else None,
                history=closed,
                today=services.today(),
                next_dates=services.upcoming_dates(task),
                undo=self.undo_banner(),
                undo_return=self.undo_return(),
            ),
            **kwargs,
        )


class TaskEditView(TaskFormMixin):
    def get_form_kwargs(self) -> dict[str, Any]:
        kwargs = super().get_form_kwargs()
        kwargs["instance"] = self.get_task()
        return kwargs

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        return super().get_context_data(task=self.get_task(), **kwargs)

    def form_valid(self, form: forms.TaskForm) -> HttpResponse:
        task = self.get_task()
        data, extra = self.split(form)
        try:
            self.contractor_of(data, extra)
            services.update_task(self.request.user, task, due_on=extra["due_on"], **data)
        except ValidationError as exc:
            _errors(form, exc)
            return self.form_invalid(form)
        messages.success(self.request, _("Task saved."))
        return redirect("tasks:detail", home_id=self.home.id, task_id=task.id)


class TaskDeleteView(HomeTasksMixin, TemplateView):
    """A page that asks, then a POST that deletes: no script is needed to confirm."""

    require_write = True
    template_name = "tasks/confirm_delete.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        task = self.get_task()
        return super().get_context_data(
            **self.page(
                task=task, cancel_url=_url("detail", home_id=self.home.id, task_id=task.id)
            ),
            **kwargs,
        )

    def post(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        services.delete_task(request.user, self.get_task())
        messages.success(request, _("Task deleted."))
        return redirect("tasks:list", home_id=self.home.id)


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


class OccurrenceCompleteView(OccurrenceActionView):
    def act(self, occurrence: Occurrence) -> Occurrence:
        return services.complete(self.request.user, occurrence).occurrence


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
        kwargs["instance"] = self.get_occurrence()
        return kwargs

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        occurrence = self.get_occurrence()
        return super().get_context_data(
            **self.page(task=occurrence.task, occurrence=occurrence), **kwargs
        )

    def form_valid(self, form: forms.CompletionForm) -> HttpResponse:
        occurrence = self.get_occurrence()
        try:
            services.update_occurrence(self.request.user, occurrence, **form.cleaned_data)
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


class HistoryView(HomeTasksMixin, TemplateView):
    """Everything that was done or skipped, filtered and searched, with its real cost."""

    template_name = "tasks/history.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        params = self.request.GET
        status = params.get("status", "")
        selection = agenda.HistoryFilter(
            room=_uuid_or_none(params.get("room", "")),
            item=_uuid_or_none(params.get("item", "")),
            contractor=_uuid_or_none(params.get("contractor", "")),
            person=_uuid_or_none(params.get("person", "")),
            query=params.get("q", "").strip()[:200],
            status=status if status in ("done", "skipped") else "",
            after=_date_or_none(params.get("after", "")),
            before=_date_or_none(params.get("before", "")),
        )
        rows = agenda.history(self.home, selection)
        page = Paginator(rows, PAGE_SIZE).get_page(params.get("page"))
        kept = [(k, v) for k, v in params.items() if k not in ("page", "undo") and v]
        return super().get_context_data(
            **self.page(
                page=page,
                selection=selection,
                cost=agenda.cost_of(rows),
                rooms=services.rooms_for_forms(self.home),
                items=services.items_for_forms(self.home),
                contractors=services.contractors_of(self.home),
                members=services.members_for_forms(self.home),
                query_string=urlencode(kept),
                filtered=bool(kept),
            ),
            **kwargs,
        )


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
        if target and url_has_allowed_host_and_scheme(
            target, allowed_hosts={self.request.get_host()}, require_https=self.request.is_secure()
        ):
            return target
        return reverse("my-home")

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        return super().get_context_data(next=self._next(), **kwargs)

    def form_valid(self, form: forms.PreferencesForm) -> HttpResponse:
        agenda.update_preferences(self.request.user, **form.cleaned_data)
        messages.success(self.request, _("Preferences saved."))
        return redirect(self._next())
