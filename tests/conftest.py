import pytest

from archflow.models import Architecture
from archflow.project import Project


def todo_app() -> Architecture:
    """A small mobile todo app used across tests."""
    return Architecture.model_validate(
        {
            "nodes": [
                {"id": "app.list", "title": "待辦清單畫面", "type": "page",
                 "acceptance": ["可以看到所有待辦", "可以勾選完成"]},
                {"id": "app.edit", "title": "新增/編輯畫面", "type": "page",
                 "acceptance": ["可以新增待辦"]},
                {"id": "app.store", "title": "待辦狀態", "type": "state"},
                {"id": "api.todos", "title": "Todos API", "type": "api"},
                {"id": "db.todo", "title": "Todo 資料表", "type": "data"},
            ],
            "edges": [
                {"source": "app.list", "target": "app.edit", "kind": "navigates"},
                {"source": "app.list", "target": "app.store", "kind": "uses"},
                {"source": "app.edit", "target": "app.store", "kind": "uses"},
                {"source": "app.store", "target": "api.todos", "kind": "calls"},
                {"source": "api.todos", "target": "db.todo", "kind": "writes"},
            ],
        }
    )


def make_tests(arch: Architecture) -> dict:
    return {
        n.id: [{"id": f"T-{n.id}-1", "description": f"{n.title} 基本行為"}]
        for n in arch.nodes
    }


@pytest.fixture
def proj(tmp_path) -> Project:
    p = Project(tmp_path)
    p.init("Todo App", "做一個待辦事項 App", "mobile")
    return p


@pytest.fixture
def drafted(proj) -> Project:
    proj.propose(todo_app(), "初版")
    return proj


@pytest.fixture
def approved(drafted) -> Project:
    from archflow.models import TestCase

    t = {k: [TestCase(**c) for c in v] for k, v in make_tests(todo_app()).items()}
    drafted.tests_design(t, "設計測試")
    drafted.approve("使用者：OK 可以開始")
    return drafted
