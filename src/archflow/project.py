"""ArchFlow engine: state machine, versioned architecture, questionnaires,
approval gate, implementation tracking, acceptance checklist and history.

All state lives in <project>/.archflow/ as plain JSON/Markdown so it can be
committed to git and read by humans.
"""

from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import checklist as checklist_mod
from . import questionnaire as questionnaire_mod
from . import render
from .models import Architecture, ArchPatch, Node, Question, TestCase
from .templates import guidance

PHASES = ("drafting", "implementing", "acceptance")
PHASE_LABEL = {
    "drafting": "討論中（架構草稿）",
    "implementing": "實作中（架構已核准鎖定）",
    "acceptance": "驗收中",
}
SOURCE_EXTS = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".vue", ".svelte", ".html", ".css", ".scss",
    ".dart", ".kt", ".java", ".swift", ".go", ".rs", ".rb", ".php", ".cs", ".sql",
}
IGNORED_DIRS = {
    ".git", ".archflow", "node_modules", ".venv", "venv", "__pycache__", "dist", "build",
    ".next", ".expo", ".dart_tool", ".idea", ".vscode", "coverage", ".pytest_cache",
}


class ArchFlowError(Exception):
    """A workflow rule was violated; the message tells the AI what to do instead."""


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


class Project:
    def __init__(self, root: str | os.PathLike):
        self.root = Path(root).resolve()
        self.dir = self.root / ".archflow"

    # ------------------------------------------------------------------ io
    def _p(self, *parts: str) -> Path:
        return self.dir.joinpath(*parts)

    def _read_json(self, path: Path, default: Any = None) -> Any:
        if not path.exists():
            return default
        return json.loads(path.read_text(encoding="utf-8"))

    def _write_json(self, path: Path, data: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)

    def _write_text(self, path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    @property
    def initialized(self) -> bool:
        return self._p("state.json").exists()

    def _require_init(self) -> None:
        if not self.initialized:
            raise ArchFlowError(
                f"No ArchFlow project in {self.root}. Call arch_init first with the user's requirements."
            )

    @property
    def state(self) -> dict:
        self._require_init()
        return self._read_json(self._p("state.json"))

    def _save_state(self, st: dict) -> None:
        self._write_json(self._p("state.json"), st)

    def _log(self, event: str, summary: str, **data: Any) -> None:
        st = self._read_json(self._p("state.json"), {})
        rec = {
            "ts": _now(),
            "round": st.get("round"),
            "phase": st.get("phase"),
            "version": st.get("current_version"),
            "event": event,
            "summary": summary,
        }
        if data:
            rec["data"] = data
        self._p().mkdir(parents=True, exist_ok=True)
        with self._p("history.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def _git_commit(self) -> str | None:
        try:
            r = subprocess.run(
                ["git", "-C", str(self.root), "rev-parse", "--short", "HEAD"],
                capture_output=True, text=True, timeout=5,
            )
            return r.stdout.strip() or None if r.returncode == 0 else None
        except (OSError, subprocess.SubprocessError):
            return None

    # ------------------------------------------------------------ versions
    def _version_path(self, v: int) -> Path:
        return self._p("versions", f"v{v:04d}.json")

    def _load_version(self, v: int) -> dict:
        p = self._version_path(v)
        if not p.exists():
            raise ArchFlowError(f"Version v{v} does not exist. Use arch_history to list versions.")
        return self._read_json(p)

    def _arch(self, v: int | None = None) -> Architecture:
        st = self.state
        v = v or st["current_version"]
        if not v:
            raise ArchFlowError("No architecture yet. Draft one with arch_propose.")
        return Architecture.model_validate(self._load_version(v)["architecture"])

    def _comments(self) -> list[dict]:
        return self._read_json(self._p("comments.json"), [])

    def _progress(self) -> dict:
        return self._read_json(self._p("progress.json"), {"nodes": {}})

    def _statuses(self) -> dict[str, str]:
        return {k: v["status"] for k, v in self._progress()["nodes"].items()}

    def _render_docs(self) -> None:
        st = self.state
        v = st["current_version"]
        if not v:
            return
        ver = self._load_version(v)
        arch = Architecture.model_validate(ver["architecture"])
        statuses = self._statuses() if st["phase"] != "drafting" else {}
        args = (st["project"]["name"], v, ver["reason"], arch, PHASE_LABEL[st["phase"]], statuses, self._comments())
        self._write_text(self._p("ARCHITECTURE.md"), render.architecture_md(*args))
        self._write_text(self._p("architecture.html"), render.architecture_html(*args))
        self._write_text(self._p("TEST_PLAN.md"), render.test_plan_md(st["project"]["name"], v, arch))

    def _new_version(self, arch: Architecture, reason: str, event: str, **extra: Any) -> dict:
        st = self.state
        if st["phase"] != "drafting":
            raise ArchFlowError(
                f"Architecture is locked (phase: {st['phase']}). Any change must start with "
                "change_request so the user and AI re-align on the diagram first."
            )
        if not reason.strip():
            raise ArchFlowError("A reason is required for every architecture change.")
        v = st["last_version"] + 1
        record = {
            "version": v,
            "parent": st["current_version"],
            "created_at": _now(),
            "round": st["round"],
            "reason": reason,
            "git_commit": self._git_commit(),
            "architecture": json.loads(arch.model_dump_json()),
            **extra,
        }
        self._write_json(self._version_path(v), record)
        parent = st["current_version"]
        st["current_version"] = v
        st["last_version"] = v
        self._save_state(st)
        d = self._diff_arch(self._arch(parent), arch) if parent else None
        self._log(event, reason, version=v, parent=parent, diff=d)
        self._render_docs()
        return {"version": v, "parent": parent, "diff": d}

    @staticmethod
    def _diff_arch(a: Architecture, b: Architecture) -> dict:
        an = {n.id: n for n in a.nodes}
        bn = {n.id: n for n in b.nodes}
        modified = []
        for nid in sorted(an.keys() & bn.keys()):
            x, y = an[nid].model_dump(), bn[nid].model_dump()
            if x != y:
                modified.append({"id": nid, "fields": sorted(k for k in x if x[k] != y[k])})
        ae = {e.key() for e in a.edges}
        be = {e.key() for e in b.edges}
        return {
            "added_nodes": sorted(bn.keys() - an.keys()),
            "removed_nodes": sorted(an.keys() - bn.keys()),
            "modified_nodes": modified,
            "added_edges": [list(k) for k in sorted(be - ae)],
            "removed_edges": [list(k) for k in sorted(ae - be)],
        }

    # ---------------------------------------------------------------- init
    def init(self, name: str, requirements: str, project_type: str = "web") -> dict:
        if self.initialized:
            raise ArchFlowError(
                "This project already has .archflow/. Use arch_status to continue, "
                "or change_request to start a new round of changes."
            )
        st = {
            "project": {"name": name, "type": project_type, "requirements": requirements},
            "phase": "drafting",
            "round": 1,
            "current_version": None,
            "last_version": 0,
            "approved_version": None,
            "questionnaire": None,  # {"round": n, "status": "pending"|"answered"}
            "questionnaire_count": 0,
            "created_at": _now(),
        }
        self._p("versions").mkdir(parents=True, exist_ok=True)
        self._save_state(st)
        self._write_json(self._p("progress.json"), {"approved_version": None, "nodes": {}})
        self._write_json(self._p("comments.json"), [])
        self._log("init", f"建立專案 {name}", requirements=requirements, project_type=project_type)
        return {
            "ok": True,
            "dir": str(self.dir),
            "guidance": guidance(project_type),
            "next": "Draft the architecture with arch_propose, then turn every unclear point into questions_create.",
        }

    # -------------------------------------------------------------- status
    def status(self) -> dict:
        st = self.state
        q = st.get("questionnaire")
        res: dict[str, Any] = {
            "project": st["project"]["name"],
            "phase": st["phase"],
            "phase_label": PHASE_LABEL[st["phase"]],
            "round": st["round"],
            "current_version": st["current_version"],
            "approved_version": st["approved_version"],
            "questionnaire": q,
            "files": {
                "diagram_html": str(self._p("architecture.html")),
                "architecture_md": str(self._p("ARCHITECTURE.md")),
                "test_plan": str(self._p("TEST_PLAN.md")),
                "questionnaire": str(self._p("questionnaire.md")),
                "checklist": str(self.root / "CHECKLIST.md"),
            },
        }
        if st["phase"] == "drafting":
            if not st["current_version"]:
                res["next"] = "Draft the first architecture with arch_propose."
            elif q and q["status"] == "pending":
                res["next"] = ("Wait for the user to fill questionnaire.md, then call questions_collect.")
            else:
                missing = [n.id for n in self._arch().nodes if not n.tests and n.type != "external"]
                res["nodes_without_tests"] = missing
                res["next"] = (
                    "Review the diagram with the user. Design tests (tests_design) for nodes without tests. "
                    "When the user explicitly says the diagram is OK, call arch_approve."
                )
        elif st["phase"] == "implementing":
            prog = self._progress()["nodes"]
            res["progress"] = {
                "done": sorted(k for k, v in prog.items() if v["status"] == "done"),
                "todo": sorted(k for k, v in prog.items() if v["status"] != "done"),
            }
            res["next"] = "Call impl_next and implement exactly that node." if res["progress"]["todo"] else (
                "All nodes done. Run conformance_check, then checklist_generate."
            )
        else:
            res["next"] = (
                "User is testing with CHECKLIST.md. When they come back, call checklist_status; "
                "for changes or unchecked items call change_request."
            )
        return res

    # ------------------------------------------------------- architecture
    def propose(self, arch: Architecture, reason: str) -> dict:
        self._require_init()
        r = self._new_version(arch, reason, "arch_propose")
        return {**r, "mermaid": render.mermaid(arch), "viewer": str(self._p("architecture.html"))}

    def update(self, patch: ArchPatch, reason: str) -> dict:
        arch = self._arch()
        nodes = {n.id: n for n in arch.nodes}
        order = [n.id for n in arch.nodes]
        for nid in patch.remove_nodes:
            if nid not in nodes:
                raise ArchFlowError(f"remove_nodes: unknown node '{nid}'")
            del nodes[nid]
        for n in patch.upsert_nodes:
            if n.id not in nodes and n.id not in order:
                order.append(n.id)
            nodes[n.id] = n
        edges = [e for e in arch.edges if e.source in nodes and e.target in nodes]
        for ref in patch.remove_edges:
            before = len(edges)
            edges = [
                e for e in edges
                if not (e.source == ref.source and e.target == ref.target and (ref.kind is None or e.kind == ref.kind))
            ]
            if len(edges) == before:
                raise ArchFlowError(f"remove_edges: no edge {ref.source}->{ref.target}")
        edges += patch.add_edges
        new = Architecture(nodes=[nodes[i] for i in order if i in nodes], edges=edges)
        r = self._new_version(new, reason, "arch_update")
        return {**r, "mermaid": render.mermaid(new, self._diff_classes(r["diff"]))}

    @staticmethod
    def _diff_classes(d: dict | None) -> dict[str, str]:
        if not d:
            return {}
        c = {n: "added" for n in d["added_nodes"]}
        c.update({m["id"]: "modified" for m in d["modified_nodes"]})
        return c

    def get(self, version: int | None = None, include_json: bool = True) -> dict:
        st = self.state
        v = version or st["current_version"]
        if not v:
            raise ArchFlowError("No architecture yet. Draft one with arch_propose.")
        ver = self._load_version(v)
        arch = Architecture.model_validate(ver["architecture"])
        statuses = self._statuses() if st["phase"] != "drafting" and v == st["current_version"] else {}
        res = {
            "version": v,
            "reason": ver["reason"],
            "created_at": ver["created_at"],
            "git_commit": ver.get("git_commit"),
            "is_current": v == st["current_version"],
            "is_approved": v == st["approved_version"],
            "mermaid": render.mermaid(arch, {k: s for k, s in statuses.items() if s in ("done", "failing")}),
            "viewer": str(self._p("architecture.html")),
        }
        if include_json:
            res["architecture"] = ver["architecture"]
        return res

    def node_detail(self, node_id: str) -> dict:
        arch = self._arch()
        n = arch.node(node_id)
        if not n:
            raise ArchFlowError(f"Unknown node '{node_id}'. Known: {[x.id for x in arch.nodes]}")
        history = []
        for v in range(1, self.state["last_version"] + 1):
            p = self._version_path(v)
            if not p.exists():
                continue
            ver = self._read_json(p)
            m = next((x for x in ver["architecture"]["nodes"] if x["id"] == node_id), None)
            history.append({"version": v, "present": m is not None, "reason": ver["reason"], "_node": m})
        changes, prev = [], None
        for h in history:
            if h["_node"] != prev:
                changes.append({"version": h["version"], "present": h["present"], "reason": h["reason"]})
            prev = h["_node"]
        return {
            "node": json.loads(n.model_dump_json()),
            "outgoing": [e.model_dump() for e in arch.edges if e.source == node_id],
            "incoming": [e.model_dump() for e in arch.edges if e.target == node_id],
            "comments": [c for c in self._comments() if c["node_id"] == node_id],
            "progress": self._progress()["nodes"].get(node_id),
            "changed_in_versions": changes,
        }

    def comment(self, node_id: str, text: str, author: str = "user") -> dict:
        arch = self._arch()
        if not arch.node(node_id):
            raise ArchFlowError(f"Unknown node '{node_id}'.")
        cs = self._comments()
        c = {"ts": _now(), "node_id": node_id, "author": author, "text": text, "version": self.state["current_version"]}
        cs.append(c)
        self._write_json(self._p("comments.json"), cs)
        self._log("node_comment", f"{author} 對 {node_id}：{text}", node_id=node_id)
        self._render_docs()
        return {"ok": True, "comment": c}

    def diff(self, a: int, b: int | None = None) -> dict:
        b = b or self.state["current_version"]
        aa, bb = self._arch(a), self._arch(b)
        d = self._diff_arch(aa, bb)
        removed = [n for n in aa.nodes if n.id in d["removed_nodes"]]
        classes = self._diff_classes(d) | {n.id: "removed" for n in removed}
        return {"from": a, "to": b, **d, "mermaid": render.mermaid(bb, classes, extra_nodes=removed)}

    def history(self) -> dict:
        st = self.state
        out = []
        for v in range(1, st["last_version"] + 1):
            p = self._version_path(v)
            if p.exists():
                ver = self._read_json(p)
                out.append({
                    "version": v,
                    "created_at": ver["created_at"],
                    "round": ver.get("round"),
                    "reason": ver["reason"],
                    "git_commit": ver.get("git_commit"),
                    "rollback_of": ver.get("rollback_of"),
                    "approved": v in st.get("approved_history", []),
                    "nodes": len(ver["architecture"]["nodes"]),
                })
        return {"current_version": st["current_version"], "approved_version": st["approved_version"], "versions": out}

    def rollback(self, version: int, reason: str) -> dict:
        st = self.state
        if st["phase"] != "drafting":
            raise ArchFlowError("Rollback changes the architecture: call change_request first, then arch_rollback.")
        target = self._load_version(version)
        arch = Architecture.model_validate(target["architecture"])
        r = self._new_version(arch, f"退回 v{version}：{reason}", "arch_rollback", rollback_of=version)
        r["code_hint"] = (
            f"Architecture restored as new version v{r['version']}. Code is NOT changed automatically. "
            + (f"v{version} was created at git commit {target['git_commit']}; "
               "ask the user whether to restore code too (e.g. git revert / git checkout <commit> -- <paths>)."
               if target.get("git_commit") else "No git commit was recorded for that version.")
        )
        return r

    # ------------------------------------------------------- questionnaire
    def questions_create(self, questions: list[Question]) -> dict:
        st = self.state
        if st["phase"] != "drafting":
            raise ArchFlowError("Questionnaires belong to the discussion phase. Call change_request first.")
        if not questions:
            raise ArchFlowError("No questions given.")
        ids = [q.id for q in questions]
        if len(set(ids)) != len(ids):
            raise ArchFlowError("Duplicate question ids.")
        if st["current_version"]:
            known = {n.id for n in self._arch().nodes}
            bad = sorted({n for q in questions for n in q.node_ids if n not in known})
            if bad:
                raise ArchFlowError(f"Questions reference unknown nodes: {bad}")
        n = st.get("questionnaire_count", 0) + 1
        qpath = self._p("questions", f"q{n:03d}.json")
        self._write_json(qpath, [json.loads(q.model_dump_json()) for q in questions])
        md = questionnaire_mod.render(questions, n, st["current_version"], st["project"]["name"])
        self._write_text(self._p("questionnaire.md"), md)
        self._write_text(self._p("questions", f"q{n:03d}.md"), md)
        st["questionnaire_count"] = n
        st["questionnaire"] = {"number": n, "status": "pending", "count": len(questions)}
        self._save_state(st)
        self._log("questions_create", f"第 {n} 份問卷，{len(questions)} 題", ids=ids)
        return {
            "ok": True,
            "file": str(self._p("questionnaire.md")),
            "tell_user": f"請打開 {self._p('questionnaire.md')} 填寫 {len(questions)} 題，填完回來說一聲。",
        }

    def questions_collect(self) -> dict:
        st = self.state
        q = st.get("questionnaire")
        if not q:
            raise ArchFlowError("There is no questionnaire to collect.")
        questions = [Question.model_validate(x) for x in self._read_json(self._p("questions", f"q{q['number']:03d}.json"))]
        text = self._p("questionnaire.md").read_text(encoding="utf-8")
        res = questionnaire_mod.parse(text, questions)
        self._write_json(self._p("questions", f"q{q['number']:03d}.answers.json"), res)
        self._write_text(self._p("questions", f"q{q['number']:03d}.md"), text)
        complete = not res["unanswered"] and not res["problems"]
        q["status"] = "answered" if complete else "pending"
        st["questionnaire"] = q
        self._save_state(st)
        self._log("questions_collect", f"問卷 {q['number']}：已答 {len(res['answers']) - len(res['unanswered'])}/{len(res['answers'])}", result=res)
        res["complete"] = complete
        res["next"] = (
            "Apply every answer with arch_update (record each as a node decision with source=<question id>), "
            "then show the updated diagram to the user."
            if complete else
            "Some questions are unanswered or ambiguous. Ask the user about them (in chat or by editing the file), "
            "then call questions_collect again."
        )
        return res

    # --------------------------------------------------------------- tests
    def tests_design(self, node_tests: dict[str, list[TestCase]], reason: str) -> dict:
        arch = self._arch()
        unknown = [k for k in node_tests if not arch.node(k)]
        if unknown:
            raise ArchFlowError(f"Unknown nodes: {unknown}")
        nodes = [
            n.model_copy(update={"tests": node_tests[n.id]}) if n.id in node_tests else n
            for n in arch.nodes
        ]
        new = Architecture(nodes=nodes, edges=arch.edges)
        r = self._new_version(new, reason, "tests_design")
        r["test_plan"] = str(self._p("TEST_PLAN.md"))
        r["tell_user"] = "測試設計已寫入 TEST_PLAN.md，請使用者檢查，有疑問或要增減測試直接說。"
        return r

    # ------------------------------------------------------------ approval
    def approve(self, user_confirmation: str) -> dict:
        st = self.state
        if st["phase"] != "drafting":
            raise ArchFlowError(f"Nothing to approve in phase '{st['phase']}'.")
        if not user_confirmation.strip():
            raise ArchFlowError("Quote the user's explicit confirmation. Never approve on the user's behalf.")
        if not st["current_version"]:
            raise ArchFlowError("No architecture to approve.")
        q = st.get("questionnaire")
        if q and q["status"] == "pending":
            raise ArchFlowError("A questionnaire is still pending. Collect and apply the answers first.")
        arch = self._arch()
        missing = [n.id for n in arch.nodes if not n.tests and n.type != "external"]
        if missing:
            raise ArchFlowError(
                f"These nodes have no tests designed: {missing}. Use tests_design and let the user review TEST_PLAN.md."
            )
        prev_v = st["approved_version"]
        prog = self._progress()
        kept, reset = [], []
        prev_nodes = {n.id: n for n in self._arch(prev_v).nodes} if prev_v else {}
        new_prog = {}
        for n in arch.nodes:
            old = prog["nodes"].get(n.id)
            if old and old["status"] == "done" and prev_nodes.get(n.id) == n:
                new_prog[n.id] = old
                kept.append(n.id)
            else:
                new_prog[n.id] = {"status": "todo", "files": (old or {}).get("files", []),
                                  "tests_passing": None, "note": ""}
                reset.append(n.id)
        self._write_json(
            self._p("progress.json"),
            {"approved_version": st["current_version"], "nodes": new_prog, "changed_this_round": reset},
        )
        st["approved_version"] = st["current_version"]
        st.setdefault("approved_history", []).append(st["current_version"])
        st["phase"] = "implementing"
        self._save_state(st)
        self._log("arch_approve", f"使用者核准 v{st['current_version']}：{user_confirmation}",
                  todo=reset, unchanged_done=kept)
        self._render_docs()
        return {
            "approved_version": st["current_version"],
            "to_implement": reset,
            "unchanged_already_done": kept,
            "rules": [
                "Implement ONLY what the approved nodes describe; nothing else.",
                "Work node by node via impl_next; write the designed tests first, then the code.",
                "If something must change, stop and call change_request; do not improvise.",
            ],
        }

    # ------------------------------------------------------ implementation
    def _require_phase(self, phase: str) -> dict:
        st = self.state
        if st["phase"] != phase:
            raise ArchFlowError(f"This action needs phase '{phase}', current phase is '{st['phase']}'.")
        return st

    def impl_next(self) -> dict:
        self._require_phase("implementing")
        arch = self._arch()
        prog = self._progress()["nodes"]
        todo = [n for n in arch.nodes if prog.get(n.id, {}).get("status") != "done"]
        if not todo:
            return {"done": True, "next": "All nodes implemented. Run conformance_check, then checklist_generate."}
        deps = {n.id: {e.target for e in arch.edges if e.source == n.id and e.kind != "navigates"} for n in arch.nodes}
        layer_rank = {"data": 0, "external": 1, "infra": 2, "backend": 3, "frontend": 4}
        done = {k for k, v in prog.items() if v["status"] == "done"}
        ready = [n for n in todo if deps[n.id] <= done]
        pool = ready or todo  # cycles: fall back to any
        pool.sort(key=lambda n: (layer_rank.get(n.layer, 9), n.id))
        n = pool[0]
        return {
            "node": json.loads(n.model_dump_json()),
            "depends_on": sorted(deps[n.id]),
            "used_by": sorted(e.source for e in arch.edges if e.target == n.id),
            "comments": [c for c in self._comments() if c["node_id"] == n.id],
            "remaining": len(todo),
            "instructions": (
                "Implement this node only. Write its designed tests first, run them, then call "
                "impl_done with the files you created/changed and whether the tests pass."
            ),
        }

    def impl_done(self, node_id: str, files: list[str], tests_passing: bool, note: str = "") -> dict:
        st = self._require_phase("implementing")
        arch = self._arch()
        n = arch.node(node_id)
        if not n:
            raise ArchFlowError(
                f"'{node_id}' is not in the approved architecture v{st['approved_version']}. "
                "If it is needed, stop and call change_request to discuss it with the user."
            )
        prog = self._progress()
        status = "done" if (tests_passing or not n.tests) else "failing"
        missing_files = [f for f in files if not (self.root / f).exists()]
        prog["nodes"][node_id] = {
            "status": status, "files": files, "tests_passing": tests_passing,
            "note": note, "updated_at": _now(),
        }
        self._write_json(self._p("progress.json"), prog)
        self._log("impl_done", f"{node_id}: {status}", files=files, tests_passing=tests_passing, note=note)
        self._render_docs()
        remaining = [k for k, v in prog["nodes"].items() if v["status"] != "done"]
        res = {"node_id": node_id, "status": status, "remaining": remaining}
        if missing_files:
            res["warning"] = f"These files do not exist (paths are relative to {self.root}): {missing_files}"
        if status == "failing":
            res["next"] = "Tests are failing: fix the implementation (not the tests) and call impl_done again."
        elif remaining:
            res["next"] = "Call impl_next."
        else:
            res["next"] = "All nodes done. Run conformance_check, then checklist_generate."
        return res

    def _source_files(self) -> list[str]:
        out = []
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = [d for d in dirnames if d not in IGNORED_DIRS and not d.startswith(".")]
            for f in filenames:
                if Path(f).suffix.lower() in SOURCE_EXTS:
                    out.append(Path(dirpath, f).relative_to(self.root).as_posix())
        return sorted(out)

    def conformance(self) -> dict:
        st = self.state
        if st["phase"] == "drafting":
            raise ArchFlowError("Nothing implemented yet (phase: drafting).")
        arch = self._arch(st["approved_version"])
        prog = self._progress()["nodes"]
        not_done = [n.id for n in arch.nodes if prog.get(n.id, {}).get("status") != "done"]
        mapped = {Path(f).as_posix() for v in prog.values() for f in v.get("files", [])}
        missing = sorted(f for f in mapped if not (self.root / f).exists())
        unmapped = [f for f in self._source_files() if f not in mapped]
        ok = not not_done and not missing
        res = {
            "ok": ok,
            "nodes_not_done": not_done,
            "mapped_files_missing": missing,
            "unmapped_source_files": unmapped,
        }
        if unmapped:
            res["note"] = (
                "Unmapped files are code not linked to any architecture node. Either attach them to the right "
                "node (impl_done with the full file list) or, if they add behaviour not in the diagram, "
                "remove them or raise a change_request."
            )
        self._log("conformance_check", "通過" if ok and not unmapped else "有待處理項目", result=res)
        return res

    # ------------------------------------------------------------ checklist
    def _checklist_path(self) -> Path:
        return self.root / "CHECKLIST.md"

    def checklist_generate(self) -> dict:
        st = self.state
        if st["phase"] not in ("implementing", "acceptance"):
            raise ArchFlowError("The checklist is generated after implementation.")
        arch = self._arch(st["approved_version"])
        prog = self._progress()["nodes"]
        not_done = [n.id for n in arch.nodes if prog.get(n.id, {}).get("status") != "done"]
        if not_done:
            raise ArchFlowError(f"Not all nodes are implemented: {not_done}")
        prev = self._read_json(self._p("checklist.json"), {"items": []})
        prev_checked = {i["id"]: i["text"] for i in prev["items"] if i.get("checked")}
        changed = set(self._read_json(self._p("progress.json"), {}).get("changed_this_round", []))
        checked = {
            i["id"] for i in checklist_mod.items_for(arch)
            if prev_checked.get(i["id"]) == i["text"] and i["node_id"] not in changed
        }
        tests = {k: bool(v.get("tests_passing")) for k, v in prog.items()}
        md = checklist_mod.render(st["project"]["name"], st["approved_version"], st["round"], arch, checked, tests)
        self._write_text(self._checklist_path(), md)
        items = [{**i, "checked": i["id"] in checked} for i in checklist_mod.items_for(arch)]
        self._write_json(self._p("checklist.json"), {"version": st["approved_version"], "items": items})
        st["phase"] = "acceptance"
        self._save_state(st)
        self._log("checklist_generate", f"產生驗收清單 {len(items)} 項（保留勾選 {len(checked)}）")
        self._render_docs()
        return {
            "file": str(self._checklist_path()),
            "items": len(items),
            "kept_checked": len(checked),
            "tell_user": "實作完成。請打開 CHECKLIST.md，一邊操作一邊打勾；有問題寫在「問題回報：」，看完回來說一聲。",
        }

    def checklist_status(self) -> dict:
        st = self.state
        p = self._checklist_path()
        if not p.exists():
            raise ArchFlowError("CHECKLIST.md does not exist yet.")
        res = checklist_mod.parse(p.read_text(encoding="utf-8"))
        known = {i["id"]: i for i in self._read_json(self._p("checklist.json"), {"items": []})["items"]}
        for i in res["items"]:
            if i["id"] in known:
                known[i["id"]]["checked"] = i["checked"]
        self._write_json(self._p("checklist.json"), {"version": st["approved_version"], "items": list(known.values())})
        unchecked = [i for i in res["items"] if not i["checked"]]
        out = {
            "total": len(res["items"]),
            "checked": len(res["items"]) - len(unchecked),
            "unchecked": unchecked,
            "issues": res["issues"],
        }
        self._log("checklist_status", f"驗收 {out['checked']}/{out['total']}", unchecked=[i["id"] for i in unchecked], issues=res["issues"])
        if unchecked or res["issues"]:
            out["next"] = (
                "Ask the user about each unchecked item (not tested yet, or broken? what happened?) and each issue. "
                "Fixes and new features go through change_request, then the diagram."
            )
        else:
            out["next"] = "Everything is accepted. Congratulate the user; new features start with change_request."
        return out

    # ------------------------------------------------------- change request
    def change_request(self, description: str) -> dict:
        st = self.state
        if st["phase"] == "drafting":
            raise ArchFlowError("Already in discussion phase; just update the architecture.")
        carry: dict[str, Any] = {}
        if self._checklist_path().exists():
            res = checklist_mod.parse(self._checklist_path().read_text(encoding="utf-8"))
            carry = {
                "unchecked_items": [i for i in res["items"] if not i["checked"]],
                "issues": res["issues"],
            }
            known = {i["id"]: i for i in self._read_json(self._p("checklist.json"), {"items": []})["items"]}
            for i in res["items"]:
                if i["id"] in known:
                    known[i["id"]]["checked"] = i["checked"]
            self._write_json(self._p("checklist.json"), {"version": st["approved_version"], "items": list(known.values())})
        prev_phase = st["phase"]
        st["phase"] = "drafting"
        st["round"] += 1
        st["questionnaire"] = None
        self._save_state(st)
        self._log("change_request", description, from_phase=prev_phase, carried=carry)
        self._render_docs()
        return {
            "round": st["round"],
            "from_phase": prev_phase,
            "carried_from_checklist": carry,
            "next": (
                "Discussion phase reopened. First ask the user about every unchecked item/issue above "
                "(unless already explained), then update the diagram (arch_update), use questions_create for "
                "unclear points, update tests, and get approval again. Unchanged done nodes keep their status."
            ),
        }

    # ------------------------------------------------------------- log export
    def export_log(self) -> dict:
        st = self.state
        lines = [f"# {st['project']['name']} — AI 協作紀錄", "", f"原始需求：{st['project']['requirements']}", ""]
        p = self._p("history.jsonl")
        cur_round = None
        for raw in p.read_text(encoding="utf-8").splitlines():
            e = json.loads(raw)
            if e.get("round") != cur_round:
                cur_round = e.get("round")
                lines += ["", f"## 第 {cur_round} 輪", ""]
            v = f" v{e['data']['version']}" if isinstance(e.get("data"), dict) and e["data"].get("version") else ""
            lines.append(f"- `{e['ts'][:19]}` **{e['event']}**{v} — {e['summary']}")
            d = (e.get("data") or {}).get("diff")
            if d:
                bits = []
                if d["added_nodes"]:
                    bits.append("新增 " + ", ".join(d["added_nodes"]))
                if d["removed_nodes"]:
                    bits.append("刪除 " + ", ".join(d["removed_nodes"]))
                if d["modified_nodes"]:
                    bits.append("修改 " + ", ".join(m["id"] for m in d["modified_nodes"]))
                if bits:
                    lines.append(f"  - 架構變更：{'；'.join(bits)}")
        out = self.root / "COLLABORATION_LOG.md"
        self._write_text(out, "\n".join(lines) + "\n")
        return {"file": str(out)}
