import json

import pytest

from archflow.models import ArchPatch, EdgeRef, Node, Question, TestCase
from archflow.project import ArchFlowError, Project

from conftest import todo_app


# ------------------------------------------------------------------ init
def test_init_creates_dir_and_guidance(tmp_path):
    res = Project(tmp_path).init("X", "需求", "mobile")
    assert (tmp_path / ".archflow" / "state.json").exists()
    assert any("iOS" in q for q in res["guidance"]["decisions_to_confirm"])


def test_init_twice_rejected(proj):
    with pytest.raises(ArchFlowError):
        proj.init("again", "x")


def test_tools_need_init(tmp_path):
    with pytest.raises(ArchFlowError, match="arch_init"):
        Project(tmp_path).status()


# ------------------------------------------------------------- versioning
def test_propose_writes_version_and_docs(drafted):
    d = drafted.dir
    assert (d / "versions" / "v0001.json").exists()
    assert "```mermaid" in (d / "ARCHITECTURE.md").read_text(encoding="utf-8")
    assert (d / "architecture.html").exists()
    assert drafted.state["current_version"] == 1


def test_update_creates_new_version_with_diff(drafted):
    res = drafted.update(
        ArchPatch(
            upsert_nodes=[Node(id="ext.push", title="推播", type="external"),
                          Node(id="db.todo", title="Todo 資料表", type="data", description="加 due_date")],
            add_edges=[{"source": "api.todos", "target": "ext.push", "kind": "calls"}],
        ),
        "加推播",
    )
    assert res["version"] == 2
    assert res["diff"]["added_nodes"] == ["ext.push"]
    assert res["diff"]["modified_nodes"] == [{"id": "db.todo", "fields": ["description"]}]


def test_remove_node_drops_its_edges(drafted):
    res = drafted.update(ArchPatch(remove_nodes=["app.edit"]), "先不做編輯")
    arch = drafted.get()["architecture"]
    assert all("app.edit" not in (e["source"], e["target"]) for e in arch["edges"])
    assert res["diff"]["removed_nodes"] == ["app.edit"]


def test_remove_missing_edge_errors(drafted):
    with pytest.raises(ArchFlowError):
        drafted.update(ArchPatch(remove_edges=[EdgeRef(source="db.todo", target="app.list")]), "x")


def test_reason_required(drafted):
    with pytest.raises(ArchFlowError, match="reason"):
        drafted.update(ArchPatch(remove_nodes=["app.edit"]), "  ")


def test_rollback_creates_new_version_and_keeps_history(drafted):
    drafted.update(ArchPatch(remove_nodes=["app.edit"]), "移除編輯")
    res = drafted.rollback(1, "還是要編輯")
    assert res["version"] == 3
    assert drafted.diff(1, 3)["added_nodes"] == []
    assert drafted.diff(1, 3)["removed_nodes"] == []
    h = drafted.history()["versions"]
    assert [v["version"] for v in h] == [1, 2, 3] and h[2]["rollback_of"] == 1


def test_diff_marks_removed_nodes_in_mermaid(drafted):
    drafted.update(ArchPatch(remove_nodes=["app.edit"]), "移除")
    m = drafted.diff(1)["mermaid"]
    assert "新增/編輯畫面" in m and "classDef removed" in m


def test_node_detail_and_comments(drafted):
    drafted.comment("api.todos", "需要分頁嗎？")
    drafted.update(ArchPatch(upsert_nodes=[Node(id="api.todos", title="Todos API", type="api",
                                                description="支援分頁")]), "回答分頁問題")
    d = drafted.node_detail("api.todos")
    assert d["comments"][0]["text"] == "需要分頁嗎？"
    assert [c["version"] for c in d["changed_in_versions"]] == [1, 2]
    assert d["incoming"][0]["source"] == "app.store"
    assert "需要分頁嗎？" in (drafted.dir / "ARCHITECTURE.md").read_text(encoding="utf-8")


# ---------------------------------------------------------- questionnaire
def test_questionnaire_flow(drafted):
    q = [Question(id="Q1", question="技術？", node_ids=["app.list"],
                  options=[{"key": "A", "label": "Expo"}, {"key": "B", "label": "Flutter"}])]
    drafted.questions_create(q)
    assert drafted.status()["questionnaire"]["status"] == "pending"
    res = drafted.questions_collect()
    assert not res["complete"] and res["unanswered"] == ["Q1"]
    f = drafted.dir / "questionnaire.md"
    f.write_text(f.read_text(encoding="utf-8").replace("- [ ] A. Expo", "- [x] A. Expo"), encoding="utf-8")
    res = drafted.questions_collect()
    assert res["complete"]
    assert drafted.state["questionnaire"]["status"] == "answered"


def test_questions_with_unknown_node_rejected(drafted):
    with pytest.raises(ArchFlowError, match="unknown nodes"):
        drafted.questions_create([Question(id="Q1", question="?", type="text", node_ids=["nope"])])


# ----------------------------------------------------------------- gates
def test_approve_requires_tests(drafted):
    with pytest.raises(ArchFlowError, match="no tests"):
        drafted.approve("OK")


def test_approve_rejects_empty_confirmation(drafted):
    with pytest.raises(ArchFlowError, match="confirmation"):
        drafted.approve("   ")


def test_approve_blocked_by_pending_questionnaire(drafted):
    drafted.tests_design({n.id: [TestCase(id=f"T-{n.id}", description="x")] for n in todo_app().nodes}, "t")
    drafted.questions_create([Question(id="Q1", question="?", type="text")])
    with pytest.raises(ArchFlowError, match="questionnaire"):
        drafted.approve("OK")


def test_locked_after_approval(approved):
    assert approved.state["phase"] == "implementing"
    with pytest.raises(ArchFlowError, match="change_request"):
        approved.update(ArchPatch(remove_nodes=["app.edit"]), "偷改")
    with pytest.raises(ArchFlowError):
        approved.questions_create([Question(id="Q1", question="?", type="text")])


# ------------------------------------------------------- implementation
def _implement_all(p: Project) -> list[str]:
    order = []
    while True:
        nxt = p.impl_next()
        if nxt.get("done"):
            return order
        nid = nxt["node"]["id"]
        order.append(nid)
        f = p.root / "src" / f"{nid}.ts"
        f.parent.mkdir(exist_ok=True)
        f.write_text("// code", encoding="utf-8")
        p.impl_done(nid, [f"src/{nid}.ts"], True)


def test_impl_order_respects_dependencies(approved):
    order = _implement_all(approved)
    assert order.index("db.todo") < order.index("api.todos") < order.index("app.store") < order.index("app.list")


def test_impl_done_rejects_unknown_node(approved):
    with pytest.raises(ArchFlowError, match="change_request"):
        approved.impl_done("app.settings", [], True)


def test_failing_tests_not_done(approved):
    res = approved.impl_done("db.todo", ["x.py"], False)
    assert res["status"] == "failing" and "warning" in res
    assert approved.impl_next()["node"]["id"] == "db.todo"


def test_conformance_finds_unmapped_files(approved):
    _implement_all(approved)
    (approved.root / "src" / "secret_feature.ts").write_text("//", encoding="utf-8")
    res = approved.conformance()
    assert res["ok"] and res["unmapped_source_files"] == ["src/secret_feature.ts"]


# ------------------------------------------------------- acceptance loop
def test_checklist_requires_all_done(approved):
    with pytest.raises(ArchFlowError, match="Not all"):
        approved.checklist_generate()


def _tick(p: Project, ids: list[str], issue_for: str | None = None, issue: str = "") -> None:
    f = p.root / "CHECKLIST.md"
    lines = f.read_text(encoding="utf-8").splitlines()
    out, node = [], None
    for line in lines:
        if any(f"<!-- id:{i} -->" in line for i in ids):
            line = line.replace("- [ ]", "- [x]")
        if "<!-- node:" in line:
            node = line.split("<!-- node:")[1].split()[0]
        if issue_for and node == issue_for and line.startswith("問題回報："):
            line = "問題回報：" + issue
        out.append(line)
    f.write_text("\n".join(out), encoding="utf-8")


def test_full_change_request_cycle(approved):
    _implement_all(approved)
    res = approved.checklist_generate()
    assert res["items"] == 6 and approved.state["phase"] == "acceptance"

    _tick(approved, ["app.list#1", "db.todo#1", "api.todos#1", "app.store#1", "app.edit#1"],
          issue_for="app.list", issue="勾選完成後重開 App 狀態不見")
    st = approved.checklist_status()
    assert st["checked"] == 5
    assert [i["id"] for i in st["unchecked"]] == ["app.list#2"]
    assert "重開 App" in st["issues"]["app.list"]

    cr = approved.change_request("修正勾選狀態沒有保存")
    assert approved.state["phase"] == "drafting" and cr["round"] == 2
    assert cr["carried_from_checklist"]["unchecked_items"][0]["id"] == "app.list#2"

    # fix: change only app.store, re-approve
    store = Node(id="app.store", title="待辦狀態", type="state", description="完成狀態寫回 API",
                 tests=[TestCase(id="T-app.store-1", description="x"),
                        TestCase(id="T-app.store-2", description="完成狀態持久化")])
    approved.update(ArchPatch(upsert_nodes=[store]), "修正持久化")
    res = approved.approve("好，改這樣")
    assert res["to_implement"] == ["app.store"]
    assert set(res["unchanged_already_done"]) == {"app.list", "app.edit", "api.todos", "db.todo"}

    assert approved.impl_next()["node"]["id"] == "app.store"
    approved.impl_done("app.store", ["src/app.store.ts"], True)
    approved.checklist_generate()
    st = approved.checklist_status()
    # app.store#1 was re-opened because the node changed; the others stay ticked
    assert {i["id"] for i in st["unchecked"]} == {"app.list#2", "app.store#1"}
    assert st["checked"] == 4


def test_log_export(approved):
    _implement_all(approved)
    res = approved.export_log()
    text = (approved.root / "COLLABORATION_LOG.md").read_text(encoding="utf-8")
    assert res["file"].endswith("COLLABORATION_LOG.md")
    assert "arch_approve" in text and "impl_done" in text and "第 1 輪" in text


def test_history_jsonl_is_valid(approved):
    for line in (approved.dir / "history.jsonl").read_text(encoding="utf-8").splitlines():
        json.loads(line)
