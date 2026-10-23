"""CHECKLIST.md: acceptance checklist the user ticks while testing."""

from __future__ import annotations

import re

from .models import Architecture
from .render import LAYER_ORDER, LAYER_TITLE

GENERAL = "_general"
NODE_RE = re.compile(r"<!--\s*node:\s*([^\s>]+)\s*-->")
ITEM_RE = re.compile(r"^\s*-\s*\[([ xXvV✓✔])\]\s*(.*?)\s*<!--\s*id:\s*([^\s>]+)\s*-->")
ISSUE_RE = re.compile(r"^\s*問題回報\s*[:：]\s*(.*)$")


def items_for(arch: Architecture) -> list[dict]:
    """Checklist items derived from node acceptance criteria."""
    items = []
    for layer in LAYER_ORDER:
        for n in [n for n in arch.nodes if n.layer == layer]:
            crit = n.acceptance or [f"{n.title}：{n.description or '功能如架構描述運作'}"]
            for i, text in enumerate(crit, 1):
                items.append({"id": f"{n.id}#{i}", "node_id": n.id, "text": text})
    return items


def render(
    project_name: str,
    version: int,
    round_no: int,
    arch: Architecture,
    checked: set[str] | None = None,
    test_status: dict[str, bool] | None = None,
) -> str:
    checked = checked or set()
    test_status = test_status or {}
    items = items_for(arch)
    done = sum(1 for i in items if i["id"] in checked)
    out = [
        f"# {project_name} — 驗收清單（架構 v{version}，第 {round_no} 輪）",
        "",
        "**使用方式**：一邊實際操作一邊測試，確認沒問題就把 `[ ]` 改成 `[x]`。",
        "有問題就寫在該功能的「問題回報：」後面（可以換行）。",
        "看完存檔後回到 Claude Code，說「清單看完了」或直接提出修改需求。",
        "",
        f"產生時進度：{done} / {len(items)}（之前輪次已驗收且未變更的項目會保留勾選）",
        "",
    ]
    for layer in LAYER_ORDER:
        nodes = [n for n in arch.nodes if n.layer == layer]
        if not nodes:
            continue
        out += [f"## {LAYER_TITLE[layer]}", ""]
        for n in nodes:
            out.append(f"### {n.title} `{n.id}` <!-- node:{n.id} -->")
            out.append("")
            if n.description:
                out += [n.description, ""]
            for it in [i for i in items if i["node_id"] == n.id]:
                mark = "x" if it["id"] in checked else " "
                out.append(f"- [{mark}] {it['text']} <!-- id:{it['id']} -->")
            if n.tests:
                ok = test_status.get(n.id)
                st = "全部通過" if ok else ("未通過" if ok is False else "未回報")
                out.append(f"  - 自動化測試（{st}）：" + ", ".join(f"`{t.id}`" for t in n.tests))
            out += ["", "問題回報：", ""]
    out += [
        "## 其他問題或新需求",
        f"<!-- node:{GENERAL} -->",
        "",
        "問題回報：",
        "",
    ]
    return "\n".join(out).rstrip() + "\n"


def parse(text: str) -> dict:
    """Return {"items": [{id,node_id,text,checked}], "issues": {node_id: text}}."""
    items, issues = [], {}
    node = None
    in_issue = False
    for line in text.splitlines():
        m = NODE_RE.search(line)
        if m:
            node = m.group(1)
            in_issue = False
            continue
        if line.lstrip().startswith("#"):
            in_issue = False
            continue
        m = ITEM_RE.match(line)
        if m:
            in_issue = False
            iid = m.group(3)
            items.append(
                {
                    "id": iid,
                    "node_id": iid.split("#")[0],
                    "text": m.group(2),
                    "checked": m.group(1).strip() != "",
                }
            )
            continue
        m = ISSUE_RE.match(line)
        if m and node:
            in_issue = True
            if m.group(1).strip():
                issues.setdefault(node, []).append(m.group(1).strip())
            continue
        if in_issue and node and line.strip():
            issues.setdefault(node, []).append(line.strip())
    return {"items": items, "issues": {k: "\n".join(v) for k, v in issues.items()}}
