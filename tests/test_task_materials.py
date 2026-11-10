"""Materials of a task: the stock items it needs, in services, screens and API (ADR 0046)."""

import io
import zipfile
from decimal import Decimal

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import Client, TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from housecairn.accounts.models import User
from housecairn.homes import services as home_services
from housecairn.homes.models import Home
from housecairn.stock import services as stock_services
from housecairn.stock.models import Article
from housecairn.tasks import materials, services
from housecairn.tasks.models import Task, TaskMaterial
from tests.data_support import export_data

pytest_plugins = ("tests.tasks_fixtures", "tests.stock_fixtures")
pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("media_root", "frozen_today")]


def url(name: str, home: Home, **kwargs: object) -> str:
    return reverse(f"tasks:{name}", kwargs={"home_id": home.id, **kwargs})


def api(name: str, home: Home, **kwargs: object) -> str:
    return reverse(f"api-v1:home-{name}", kwargs={"home_id": home.id, **kwargs})


@pytest.fixture
def paint(alice: User, alice_home: Home) -> Article:
    return stock_services.create_article(alice, alice_home, name="White paint", unit="litre")


def lines(task: Task) -> list[tuple[str, Decimal]]:
    return [(m.article.name, m.quantity) for m in materials.materials_of(task)]


def form_data(task_title: str, *rows: tuple[object, str]) -> dict[str, object]:
    """The task form with stock item rows (and room for two empty ones, as the screen has)."""
    data: dict[str, object] = {
        "title": task_title,
        "priority": "normal",
        "repeat_mode": "once",
        "repeat_unit": "month",
        "repeat_interval": "1",
        "hide_days_before": "0",
        "materials-TOTAL_FORMS": str(len(rows) + 2),
        "materials-INITIAL_FORMS": "0",
        "materials-MIN_NUM_FORMS": "0",
        "materials-MAX_NUM_FORMS": "50",
    }
    for index, (article, quantity) in enumerate([*rows, ("", ""), ("", "")]):
        data[f"materials-{index}-article"] = str(article)
        data[f"materials-{index}-quantity"] = quantity
    return data


class TestServices:
    def test_a_task_lists_articles_with_a_quantity(
        self, alice: User, owner_task: Task, article: Article, paint: Article
    ) -> None:
        materials.add_material(alice, owner_task, article, Decimal("1"))
        materials.add_material(alice, owner_task, paint, Decimal("2.5"))
        assert lines(owner_task) == [
            ("Boiler filter", Decimal("1.00")),
            ("White paint", Decimal("2.50")),
        ]

    def test_the_line_shows_what_is_in_stock(
        self, alice: User, owner_task: Task, article: Article
    ) -> None:
        stock_services.record_movement(alice, article, kind="entry", quantity=Decimal("4"))
        materials.add_material(alice, owner_task, article, Decimal("1"))
        (line,) = materials.materials_of(owner_task)
        assert line.stock_quantity == Decimal("4.00")  # type: ignore[attr-defined]

    def test_change_and_remove(self, alice: User, owner_task: Task, article: Article) -> None:
        line = materials.add_material(alice, owner_task, article, Decimal("1"))
        materials.update_material(alice, line, quantity=Decimal("3"))
        assert lines(owner_task) == [("Boiler filter", Decimal("3.00"))]
        materials.remove_material(alice, line)
        assert lines(owner_task) == []
        # Removed, the article can be listed again.
        materials.add_material(alice, owner_task, article, Decimal("2"))
        assert lines(owner_task) == [("Boiler filter", Decimal("2.00"))]

    def test_an_article_is_listed_once(
        self, alice: User, owner_task: Task, article: Article
    ) -> None:
        materials.add_material(alice, owner_task, article, Decimal("1"))
        with pytest.raises(ValidationError) as caught:
            materials.add_material(alice, owner_task, article, Decimal("2"))
        assert "article" in caught.value.message_dict
        # Saving is the gesture of the screen: it changes the quantity instead.
        materials.save_material(alice, owner_task, article, Decimal("2"))
        assert lines(owner_task) == [("Boiler filter", Decimal("2.00"))]

    @pytest.mark.parametrize("quantity", ["0", "-1", "0.001", "123456789"])
    def test_the_quantity_is_a_positive_amount(
        self, alice: User, owner_task: Task, article: Article, quantity: str
    ) -> None:
        with pytest.raises(ValidationError) as caught:
            materials.add_material(alice, owner_task, article, Decimal(quantity))
        assert "quantity" in caught.value.message_dict

    def test_set_materials_makes_the_list_exactly(
        self, alice: User, owner_task: Task, article: Article, paint: Article
    ) -> None:
        materials.set_materials(alice, owner_task, [(article, Decimal("1")), (paint, Decimal("2"))])
        materials.set_materials(alice, owner_task, [(paint, Decimal("5"))])
        assert lines(owner_task) == [("White paint", Decimal("5.00"))]
        with pytest.raises(ValidationError):
            materials.set_materials(
                alice, owner_task, [(paint, Decimal("1")), (paint, Decimal("2"))]
            )

    def test_an_article_of_another_home_is_refused(
        self, alice: User, owner_task: Task, foreign_article: Article
    ) -> None:
        with pytest.raises(ValidationError) as caught:
            materials.add_material(alice, owner_task, foreign_article, Decimal("1"))
        assert "article" in caught.value.message_dict
        assert not TaskMaterial.objects.exists()

    def test_a_deleted_article_drops_out_of_the_list(
        self, alice: User, owner_task: Task, article: Article
    ) -> None:
        materials.add_material(alice, owner_task, article, Decimal("1"))
        stock_services.delete_article(alice, article)
        assert lines(owner_task) == []

    def test_read_only_changes_nothing(
        self, reader: User, alice: User, owner_task: Task, article: Article
    ) -> None:
        with pytest.raises(PermissionDenied):
            materials.add_material(reader, owner_task, article, Decimal("1"))
        line = materials.add_material(alice, owner_task, article, Decimal("1"))
        with pytest.raises(PermissionDenied):
            materials.update_material(reader, line, quantity=Decimal("2"))
        with pytest.raises(PermissionDenied):
            materials.remove_material(reader, line)
        with pytest.raises(PermissionDenied):
            materials.set_materials(reader, owner_task, [])
        assert lines(owner_task) == [("Boiler filter", Decimal("1.00"))]

    def test_the_tasks_that_need_an_article(
        self, alice: User, owner_task: Task, article: Article
    ) -> None:
        materials.add_material(alice, owner_task, article, Decimal("1"))
        assert list(materials.tasks_using(article)) == [owner_task]


class TestScreens:
    def test_the_form_creates_a_task_with_its_materials(
        self, signed_in: Client, alice_home: Home, article: Article, paint: Article
    ) -> None:
        response = signed_in.post(
            url("create", alice_home),
            form_data("Repaint", (article.id, "1"), (paint.id, "2.5")),
        )
        assert response.status_code == 302, response.text
        task = Task.objects.get(title="Repaint")
        assert lines(task) == [("Boiler filter", Decimal("1.00")), ("White paint", Decimal("2.50"))]

    def test_the_form_changes_and_removes_lines(
        self,
        signed_in: Client,
        alice: User,
        alice_home: Home,
        owner_task: Task,
        article: Article,
        paint: Article,
    ) -> None:
        materials.set_materials(alice, owner_task, [(article, Decimal("1")), (paint, Decimal("2"))])
        page = signed_in.get(url("edit", alice_home, task_id=owner_task.id))
        assert page.status_code == 200
        assert "Boiler filter" in page.text
        data = form_data(owner_task.title, (article.id, "4"), ("", ""))
        data["materials-INITIAL_FORMS"] = "2"
        assert (
            signed_in.post(url("edit", alice_home, task_id=owner_task.id), data).status_code == 302
        )
        assert lines(owner_task) == [("Boiler filter", Decimal("4.00"))]

    def test_a_form_without_the_stock_items_leaves_them_alone(
        self, signed_in: Client, alice: User, alice_home: Home, owner_task: Task, article: Article
    ) -> None:
        materials.add_material(alice, owner_task, article, Decimal("2"))
        data = form_data(owner_task.title)
        for key in [k for k in data if k.startswith("materials-")]:
            del data[key]
        assert (
            signed_in.post(url("edit", alice_home, task_id=owner_task.id), data).status_code == 302
        )
        assert lines(owner_task) == [("Boiler filter", Decimal("2.00"))]

    @pytest.mark.parametrize(
        ("rows", "message"),
        [
            ([("article", "")], "Give the quantity."),
            ([("", "3")], "Choose the stock item."),
            ([("article", "0")], "Ensure this value is greater than or equal to 0.01."),
            ([("article", "1"), ("article", "2")], "A stock item is listed once for a task."),
        ],
    )
    def test_the_form_refuses_a_bad_line_and_saves_nothing(
        self,
        signed_in: Client,
        alice_home: Home,
        article: Article,
        rows: list[tuple[str, str]],
        message: str,
    ) -> None:
        shown = [(article.id if a == "article" else a, q) for a, q in rows]
        response = signed_in.post(url("create", alice_home), form_data("Repaint", *shown))
        assert response.status_code == 200
        assert message in response.text
        assert not Task.objects.filter(title="Repaint").exists()

    def test_an_article_of_another_home_is_not_a_choice(
        self, signed_in: Client, alice_home: Home, foreign_article: Article
    ) -> None:
        response = signed_in.post(
            url("create", alice_home), form_data("Repaint", (foreign_article.id, "1"))
        )
        assert response.status_code == 200
        assert not Task.objects.filter(title="Repaint").exists()
        assert not TaskMaterial.objects.exists()

    def test_the_task_page_adds_changes_and_removes(
        self, signed_in: Client, alice_home: Home, owner_task: Task, article: Article
    ) -> None:
        save = url("material-save", alice_home, task_id=owner_task.id)
        assert signed_in.post(save, {"article": article.id, "quantity": "2"}).status_code == 302
        assert lines(owner_task) == [("Boiler filter", Decimal("2.00"))]
        signed_in.post(save, {"article": article.id, "quantity": "3"})
        (line,) = materials.materials_of(owner_task)
        assert line.quantity == Decimal("3.00")
        page = signed_in.get(url("detail", alice_home, task_id=owner_task.id))
        assert "Boiler filter" in page.text
        assert "Not enough in stock" in page.text
        remove = url("material-remove", alice_home, task_id=owner_task.id, material_id=line.id)
        assert signed_in.post(remove).status_code == 302
        assert lines(owner_task) == []

    def test_the_add_form_has_a_dash_not_a_row_of_hyphens_as_empty_choice(
        self, signed_in: Client, alice_home: Home, owner_task: Task, article: Article
    ) -> None:
        page = signed_in.get(url("detail", alice_home, task_id=owner_task.id))
        assert "---------" not in page.text
        assert '<option value="" selected>—</option>' in page.text

    def test_a_bad_quantity_on_the_task_page_changes_nothing(
        self, signed_in: Client, alice_home: Home, owner_task: Task, article: Article
    ) -> None:
        save = url("material-save", alice_home, task_id=owner_task.id)
        response = signed_in.post(save, {"article": article.id, "quantity": "0"}, follow=True)
        assert "greater than or equal to 0.01" in response.text
        assert lines(owner_task) == []

    def test_the_task_page_refuses_an_article_of_another_home(
        self, signed_in: Client, alice_home: Home, owner_task: Task, foreign_article: Article
    ) -> None:
        save = url("material-save", alice_home, task_id=owner_task.id)
        signed_in.post(save, {"article": foreign_article.id, "quantity": "1"})
        assert not TaskMaterial.objects.exists()

    def test_a_reader_sees_the_lines_and_changes_nothing(
        self,
        client: Client,
        alice: User,
        reader: User,
        alice_home: Home,
        owner_task: Task,
        article: Article,
    ) -> None:
        line = materials.add_material(alice, owner_task, article, Decimal("1"))
        client.force_login(reader)
        page = client.get(url("detail", alice_home, task_id=owner_task.id))
        assert "Boiler filter" in page.text
        assert "Add the stock item" not in page.text
        save = url("material-save", alice_home, task_id=owner_task.id)
        assert client.post(save, {"article": article.id, "quantity": "9"}).status_code == 403
        remove = url("material-remove", alice_home, task_id=owner_task.id, material_id=line.id)
        assert client.post(remove).status_code == 403
        assert lines(owner_task) == [("Boiler filter", Decimal("1.00"))]

    def test_a_stranger_gets_a_404(
        self, client: Client, bob: User, alice_home: Home, owner_task: Task, article: Article
    ) -> None:
        client.force_login(bob)
        save = url("material-save", alice_home, task_id=owner_task.id)
        assert client.post(save, {"article": article.id, "quantity": "1"}).status_code == 404

    def test_the_article_page_names_the_tasks_that_need_it(
        self, signed_in: Client, alice: User, alice_home: Home, owner_task: Task, article: Article
    ) -> None:
        materials.add_material(alice, owner_task, article, Decimal("1"))
        page = signed_in.get(
            reverse("stock:detail", kwargs={"home_id": alice_home.id, "article_id": article.id})
        )
        assert owner_task.title in page.text


class TestApi:
    @pytest.fixture
    def client_of_alice(self, api_client: APIClient, alice: User) -> APIClient:
        api_client.force_authenticate(alice)
        return api_client

    def test_crud_and_the_task_shows_its_lines(
        self,
        client_of_alice: APIClient,
        alice_home: Home,
        owner_task: Task,
        article: Article,
    ) -> None:
        created = client_of_alice.post(
            api("task-material-list", alice_home),
            {"task": str(owner_task.id), "article": str(article.id), "quantity": "2"},
        )
        assert created.status_code == 201, created.content
        body = created.json()
        assert (body["article_name"], body["quantity"], body["stock_quantity"]) == (
            "Boiler filter",
            "2.00",
            "0.00",
        )
        detail = api("task-material-detail", alice_home, material_id=body["id"])
        patched = client_of_alice.patch(detail, {"quantity": "5"})
        assert patched.json()["quantity"] == "5.00"
        task = client_of_alice.get(api("task-detail", alice_home, task_id=owner_task.id)).json()
        assert [(m["article_name"], m["quantity"]) for m in task["materials"]] == [
            ("Boiler filter", "5.00")
        ]
        listed = client_of_alice.get(api("task-material-list", alice_home), {"task": owner_task.id})
        assert [row["id"] for row in listed.json()["results"]] == [body["id"]]
        assert client_of_alice.delete(detail).status_code == 204
        assert client_of_alice.get(detail).status_code == 404
        assert (
            client_of_alice.get(api("task-detail", alice_home, task_id=owner_task.id)).json()[
                "materials"
            ]
            == []
        )

    def test_the_same_article_twice_is_a_400(
        self, client_of_alice: APIClient, alice_home: Home, owner_task: Task, article: Article
    ) -> None:
        payload = {"task": str(owner_task.id), "article": str(article.id), "quantity": "1"}
        assert (
            client_of_alice.post(api("task-material-list", alice_home), payload).status_code == 201
        )
        again = client_of_alice.post(api("task-material-list", alice_home), payload)
        assert again.status_code == 400
        assert "article" in again.json()

    def test_a_line_keeps_its_task_and_article(
        self,
        client_of_alice: APIClient,
        alice: User,
        alice_home: Home,
        owner_task: Task,
        article: Article,
        paint: Article,
    ) -> None:
        line = materials.add_material(alice, owner_task, article, Decimal("1"))
        detail = api("task-material-detail", alice_home, material_id=line.id)
        response = client_of_alice.patch(detail, {"article": str(paint.id)})
        assert response.status_code == 400
        assert lines(owner_task) == [("Boiler filter", Decimal("1.00"))]

    @pytest.mark.parametrize("quantity", ["0", "-2", "abc"])
    def test_a_bad_quantity_is_a_400(
        self,
        client_of_alice: APIClient,
        alice_home: Home,
        owner_task: Task,
        article: Article,
        quantity: str,
    ) -> None:
        response = client_of_alice.post(
            api("task-material-list", alice_home),
            {"task": str(owner_task.id), "article": str(article.id), "quantity": quantity},
        )
        assert response.status_code == 400
        assert not TaskMaterial.objects.exists()

    def test_another_home_is_out_of_reach(
        self,
        client_of_alice: APIClient,
        alice: User,
        alice_home: Home,
        owner_task: Task,
        foreign_article: Article,
        bob: User,
        bob_home: Home,
    ) -> None:
        refused = client_of_alice.post(
            api("task-material-list", alice_home),
            {"task": str(owner_task.id), "article": str(foreign_article.id), "quantity": "1"},
        )
        assert refused.status_code == 400
        foreign_task = services.create_task(bob, bob_home, title="Not yours")
        refused = client_of_alice.post(
            api("task-material-list", alice_home),
            {"task": str(foreign_task.id), "article": str(foreign_article.id), "quantity": "1"},
        )
        assert refused.status_code == 400
        assert client_of_alice.get(api("task-material-list", bob_home)).status_code == 404
        assert not TaskMaterial.objects.exists()

    def test_a_reader_reads_and_changes_nothing(
        self,
        api_client: APIClient,
        alice: User,
        reader: User,
        alice_home: Home,
        owner_task: Task,
        article: Article,
    ) -> None:
        line = materials.add_material(alice, owner_task, article, Decimal("1"))
        api_client.force_authenticate(reader)
        assert api_client.get(api("task-material-list", alice_home)).status_code == 200
        detail = api("task-material-detail", alice_home, material_id=line.id)
        assert api_client.patch(detail, {"quantity": "9"}).status_code == 403
        assert api_client.delete(detail).status_code == 403
        post = api_client.post(
            api("task-material-list", alice_home),
            {"task": str(owner_task.id), "article": str(article.id), "quantity": "2"},
        )
        assert post.status_code == 403
        assert lines(owner_task) == [("Boiler filter", Decimal("1.00"))]

    def test_the_screen_and_the_api_give_the_same_lines(
        self,
        signed_in: Client,
        client_of_alice: APIClient,
        alice_home: Home,
        owner_task: Task,
        article: Article,
    ) -> None:
        signed_in.post(
            url("material-save", alice_home, task_id=owner_task.id),
            {"article": article.id, "quantity": "2"},
        )
        shown = client_of_alice.get(api("task-detail", alice_home, task_id=owner_task.id)).json()
        assert [(m["article"], m["quantity"]) for m in shown["materials"]] == [
            (str(article.id), "2.00")
        ]


class TestExportAndErasure:
    def test_the_export_holds_the_lines(
        self,
        client: Client,
        alice: User,
        alice_home: Home,
        owner_task: Task,
        article: Article,
    ) -> None:
        materials.add_material(alice, owner_task, article, Decimal("2"))
        client.force_login(alice)
        response = client.post(reverse("homes:export", kwargs={"home_id": alice_home.id}))
        archive = zipfile.ZipFile(io.BytesIO(b"".join(response.streaming_content)))
        body = export_data(archive)["task_materials"]
        assert [(row["task"], row["article"], row["quantity"]) for row in body] == [
            (str(owner_task.id), str(article.id), "2.00")
        ]

    def test_erasing_the_home_erases_the_lines(
        self, alice: User, alice_home: Home, owner_task: Task, article: Article
    ) -> None:
        materials.add_material(alice, owner_task, article, Decimal("2"))
        with TestCase.captureOnCommitCallbacks(execute=True):
            home_services.delete_home(alice, alice_home, confirmation="Main house")
        assert not TaskMaterial.all_objects.exists()
