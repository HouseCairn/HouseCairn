"""Web views of rooms, items and photos. Rules live in `services`."""

from functools import cached_property
from typing import Any

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.http.response import HttpResponseBase
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django.views import View
from django.views.generic import FormView, TemplateView

from housecairn.homes import services as home_services
from housecairn.homes.models import Home
from housecairn.homes.scoping import WebHomeScopedMixin, open_homes_for_request
from housecairn.rooms import conf, forms, services
from housecairn.rooms.files import photo_response
from housecairn.rooms.models import Item, Photo, PhotoCategory, Room


class EntryView(LoginRequiredMixin, TemplateView):
    """The Rooms entry of the navigation: the rooms of the user's only home, else a choice."""

    template_name = "rooms/choose_home.html"

    def get(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        homes = list(open_homes_for_request(request).order_by("name"))
        if len(homes) == 1:
            return redirect("rooms:list", home_id=homes[0].id)
        return self.render_to_response({"homes": homes})


class HomeRoomsMixin(WebHomeScopedMixin):
    """A page of one home: the home from the address, and whether the user may write."""

    require_write = False
    request: HttpRequest

    def get_home(self) -> Home:
        home = super().get_home()
        if self.require_write and not home_services.can_write(self.request.user, home):
            raise PermissionDenied
        return home

    @cached_property
    def home(self) -> Home:
        return self.get_home()

    @cached_property
    def can_write(self) -> bool:
        return home_services.can_write(self.request.user, self.home)

    def get_room(self) -> Room:
        room: Room = get_object_or_404(
            services.rooms_of(self.home),
            id=self.kwargs["room_id"],
        )
        return room

    def get_item(self) -> Item:
        item: Item = get_object_or_404(
            services.items_of(self.home),
            id=self.kwargs["item_id"],
        )
        return item

    def page(self, **extra: Any) -> dict[str, Any]:
        return {"home": self.home, "can_write": self.can_write, **extra}


def _url(name: str, **kwargs: object) -> str:
    return reverse(f"rooms:{name}", kwargs=kwargs)


def _errors(form: Any, exc: ValidationError) -> None:
    form.add_error(None, exc)


# ---------- rooms ----------


class RoomListView(HomeRoomsMixin, TemplateView):
    template_name = "rooms/room_list.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        rooms = list(services.rooms_of(self.home))
        reorder = self.can_write and self.request.GET.get("reorder") == "1" and len(rooms) > 1
        return super().get_context_data(**self.page(rooms=rooms, reorder=reorder), **kwargs)


class RoomFormMixin(HomeRoomsMixin, FormView[Any]):
    require_write = True

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        return super().get_context_data(**self.page(), **kwargs)


class RoomCreateView(RoomFormMixin):
    template_name = "rooms/room_form.html"
    form_class = forms.RoomForm

    def form_valid(self, form: forms.RoomForm) -> HttpResponse:
        room = services.create_room(self.request.user, self.home, **form.cleaned_data)
        messages.success(self.request, _("Room added."))
        return redirect("rooms:detail", home_id=self.home.id, room_id=room.id)


class RoomDetailView(HomeRoomsMixin, TemplateView):
    template_name = "rooms/room_detail.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        room = self.get_room()
        photos = list(services.photos_for(room))
        return super().get_context_data(
            **self.page(
                room=room,
                items=room.items.order_by("name", "id"),
                open_wall_photos=[p for p in photos if p.category == PhotoCategory.OPEN_WALLS],
                photos=[p for p in photos if p.category != PhotoCategory.OPEN_WALLS],
            ),
            **kwargs,
        )


class RoomEditView(RoomFormMixin):
    template_name = "rooms/room_form.html"
    form_class: Any = forms.RoomForm

    def get_form_kwargs(self) -> dict[str, Any]:
        kwargs = super().get_form_kwargs()
        kwargs["instance"] = self.get_room()
        return kwargs

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        return super().get_context_data(room=self.get_room(), **kwargs)

    def form_valid(self, form: forms.RoomForm) -> HttpResponse:
        room = services.update_room(self.request.user, self.get_room(), **form.cleaned_data)
        messages.success(self.request, _("Room saved."))
        return redirect("rooms:detail", home_id=self.home.id, room_id=room.id)


class RoomMemoryView(RoomEditView):
    template_name = "rooms/room_memory_form.html"
    form_class = forms.RoomMemoryForm


class ConfirmDeleteView(HomeRoomsMixin, TemplateView):
    """A page that asks, then a POST that deletes: no script is needed to confirm."""

    require_write = True
    template_name = "rooms/confirm_delete.html"
    message: Any = ""

    def target(self) -> Room | Item:
        raise NotImplementedError  # pragma: no cover

    def cancel_url(self, target: Any) -> str:
        raise NotImplementedError  # pragma: no cover

    def remove(self, target: Any) -> HttpResponse:
        raise NotImplementedError  # pragma: no cover

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        target = self.target()
        return super().get_context_data(
            **self.page(target=target, cancel_url=self.cancel_url(target), message=self.message),
            **kwargs,
        )

    def post(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        return self.remove(self.target())


class RoomDeleteView(ConfirmDeleteView):
    message = gettext_lazy("The room, its items and their photos disappear from the screens.")

    def target(self) -> Room:
        return self.get_room()

    def cancel_url(self, target: Room) -> str:
        return _url("detail", home_id=self.home.id, room_id=target.id)

    def remove(self, target: Room) -> HttpResponse:
        services.delete_room(self.request.user, target)
        messages.success(self.request, _("Room deleted."))
        return redirect("rooms:list", home_id=self.home.id)


class RoomMoveView(HomeRoomsMixin, View):
    """Move a room up or down the list."""

    require_write = True
    http_method_names = ["post"]

    def post(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        try:
            services.move_room(request.user, self.get_room(), request.POST.get("direction", ""))
        except ValidationError as exc:
            messages.error(request, " ".join(exc.messages))
        return redirect(f"{_url('list', home_id=self.home.id)}?reorder=1")


# ---------- items ----------


class ItemFormMixin(RoomFormMixin):
    template_name = "rooms/item_form.html"
    form_class = forms.ItemForm

    def get_form_kwargs(self) -> dict[str, Any]:
        kwargs = super().get_form_kwargs()
        kwargs["rooms"] = services.rooms_of(self.home)
        return kwargs


class ItemCreateView(ItemFormMixin):
    def get_initial(self) -> dict[str, Any]:
        return {"room": self.get_room()}

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        return super().get_context_data(room=self.get_room(), **kwargs)

    def form_valid(self, form: forms.ItemForm) -> HttpResponse:
        data = dict(form.cleaned_data)
        room = data.pop("room")
        try:
            item = services.create_item(self.request.user, room, **data)
        except ValidationError as exc:
            _errors(form, exc)
            return self.form_invalid(form)
        messages.success(self.request, _("Item added."))
        return redirect("rooms:item-detail", home_id=self.home.id, item_id=item.id)


class ItemDetailView(HomeRoomsMixin, TemplateView):
    template_name = "rooms/item_detail.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        item = self.get_item()
        today = timezone.localdate()
        return super().get_context_data(
            **self.page(
                item=item,
                photos=list(services.photos_for(item)),
                warranty=item.warranty_state(today),
                today=today,
                # The maintenance log and the cost of ownership arrive with the
                # tasks: nothing is shown until there are entries.
                journal=[],
            ),
            **kwargs,
        )


class ItemEditView(ItemFormMixin):
    def get_form_kwargs(self) -> dict[str, Any]:
        kwargs = super().get_form_kwargs()
        kwargs["instance"] = self.get_item()
        return kwargs

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        item = self.get_item()
        return super().get_context_data(item=item, room=item.room, **kwargs)

    def form_valid(self, form: forms.ItemForm) -> HttpResponse:
        data = dict(form.cleaned_data)
        room = data.pop("room")
        item = self.get_item()
        try:
            services.update_item(self.request.user, item, room=room, **data)
        except ValidationError as exc:
            _errors(form, exc)
            return self.form_invalid(form)
        messages.success(self.request, _("Item saved."))
        return redirect("rooms:item-detail", home_id=self.home.id, item_id=item.id)


class ItemDeleteView(ConfirmDeleteView):
    message = gettext_lazy("The item and its photos disappear from the screens.")

    def target(self) -> Item:
        return self.get_item()

    def cancel_url(self, target: Item) -> str:
        return _url("item-detail", home_id=self.home.id, item_id=target.id)

    def remove(self, target: Item) -> HttpResponse:
        services.delete_item(self.request.user, target)
        messages.success(self.request, _("Item deleted."))
        return redirect("rooms:detail", home_id=self.home.id, room_id=target.room_id)


# ---------- photos ----------


class PhotoAddView(RoomFormMixin):
    """Upload a photo of a room (`target = "room"`) or of an item (`target = "item"`)."""

    template_name = "rooms/photo_form.html"
    form_class = forms.PhotoForm
    target = "room"

    def get_target(self) -> Room | Item:
        return self.get_room() if self.target == "room" else self.get_item()

    def get(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        self.get_target()
        return super().get(request, *args, **kwargs)

    def post(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        # Refuse an oversized body before reading any of it.
        declared = int(request.META.get("CONTENT_LENGTH") or 0)
        if declared > conf.photo_max_bytes() + conf.MULTIPART_OVERHEAD:
            return HttpResponse(_("This file is too large."), status=413, content_type="text/plain")
        return super().post(request, *args, **kwargs)

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        target = self.get_target()
        return super().get_context_data(
            target=target,
            back_url=self.back_url(target),
            max_bytes=conf.photo_max_bytes(),
            **kwargs,
        )

    def back_url(self, target: Room | Item) -> str:
        if isinstance(target, Room):
            return _url("detail", home_id=self.home.id, room_id=target.id)
        return _url("item-detail", home_id=self.home.id, item_id=target.id)

    def form_valid(self, form: forms.PhotoForm) -> HttpResponse:
        target = self.get_target()
        data = form.cleaned_data
        try:
            services.add_photo(
                self.request.user,
                upload=data["file"],
                room=target if isinstance(target, Room) else None,
                item=target if isinstance(target, Item) else None,
                caption=data["caption"],
                category=data["category"],
            )
        except ValidationError as exc:
            form.add_error("file", exc)
            return self.form_invalid(form)
        messages.success(self.request, _("Photo added."))
        return HttpResponseRedirect(self.back_url(target))


class ItemPhotoAddView(PhotoAddView):
    target = "item"


class PhotoFileView(HomeRoomsMixin, View):
    """The photo itself, or its thumbnail: only to the members of its home."""

    thumbnail = False
    http_method_names = ["get", "head"]

    def get(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponseBase:
        photo = get_object_or_404(services.photos_of(self.home), id=self.kwargs["photo_id"])
        return photo_response(photo, thumbnail=self.thumbnail)


class PhotoThumbnailView(PhotoFileView):
    thumbnail = True


class PhotoDeleteView(HomeRoomsMixin, View):
    require_write = True
    http_method_names = ["post"]

    def post(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        photo: Photo = get_object_or_404(services.photos_of(self.home), id=self.kwargs["photo_id"])
        services.delete_photo(request.user, photo)
        messages.success(request, _("Photo deleted."))
        if photo.room_id:
            return redirect("rooms:detail", home_id=self.home.id, room_id=photo.room_id)
        return redirect("rooms:item-detail", home_id=self.home.id, item_id=photo.item_id)


# ---------- search ----------


class SearchView(HomeRoomsMixin, TemplateView):
    template_name = "rooms/search.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        query = self.request.GET.get("q", "").strip()
        return super().get_context_data(
            **self.page(query=query, results=services.search(self.home, query)), **kwargs
        )
