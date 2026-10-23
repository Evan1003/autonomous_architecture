import pytest
from pydantic import ValidationError

from archflow import render
from archflow.models import Architecture, Node, Question

from conftest import todo_app


def test_layer_defaults_from_type():
    assert Node(id="fe.home", title="首頁", type="page").layer == "frontend"
    assert Node(id="db.user", title="User", type="data").layer == "data"


@pytest.mark.parametrize("bad", ["Fe.Home", "has space", "", "-start"])
def test_rejects_bad_node_ids(bad):
    with pytest.raises(ValidationError):
        Node(id=bad, title="x", type="page")


def test_rejects_dangling_edge():
    with pytest.raises(ValidationError, match="unknown node"):
        Architecture.model_validate(
            {"nodes": [{"id": "a", "title": "A", "type": "page"}],
             "edges": [{"source": "a", "target": "ghost"}]}
        )


def test_rejects_duplicate_nodes_and_tests():
    with pytest.raises(ValidationError, match="duplicate node"):
        Architecture.model_validate(
            {"nodes": [{"id": "a", "title": "A", "type": "page"}, {"id": "a", "title": "B", "type": "api"}]}
        )
    with pytest.raises(ValidationError, match="duplicate test"):
        Architecture.model_validate(
            {"nodes": [
                {"id": "a", "title": "A", "type": "page", "tests": [{"id": "T1", "description": "x"}]},
                {"id": "b", "title": "B", "type": "page", "tests": [{"id": "T1", "description": "y"}]},
            ]}
        )


def test_question_validation():
    with pytest.raises(ValidationError):
        Question(id="Q1", question="框架？", type="single")  # no options
    with pytest.raises(ValidationError):
        Question(id="Q1", question="框架？", options=[{"key": "A", "label": "React"}], recommended="Z")


def test_mermaid_has_layers_shapes_and_edges():
    m = render.mermaid(todo_app(), {"db.todo": "done"}, links=True)
    assert m.startswith("flowchart LR")
    assert 'subgraph L_frontend' in m and 'subgraph L_data' in m
    assert '(["待辦清單畫面' in m  # page shape
    assert '[("Todo 資料表' in m  # data shape
    assert "-.->" in m  # navigates edge is dashed
    assert "classDef done" in m
    assert 'click n0 href "#node-app.list"' in m


def test_mermaid_escapes_quotes():
    a = Architecture.model_validate({"nodes": [{"id": "a", "title": 'Say "hi"', "type": "page"}]})
    assert '#quot;hi#quot;' in render.mermaid(a)


def test_html_viewer_contains_nodes():
    html = render.architecture_html("P", 1, "init", todo_app(), "drafting")
    assert 'id="node-api.todos"' in html
    assert "mermaid@10.9.1" in html
