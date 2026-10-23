"""Render architectures as Mermaid, Markdown and a standalone HTML viewer."""

from __future__ import annotations

import html
import json

from .models import Architecture, Node

LAYER_ORDER = ["frontend", "backend", "data", "external", "infra"]
LAYER_TITLE = {
    "frontend": "前端 Frontend",
    "backend": "後端 Backend",
    "data": "資料 Data",
    "external": "外部服務 External",
    "infra": "基礎設施 Infra",
}
TYPE_TITLE = {
    "page": "頁面/畫面",
    "component": "元件",
    "state": "狀態管理",
    "api": "API",
    "service": "服務/邏輯",
    "data": "資料模型",
    "external": "外部服務",
    "job": "背景工作",
    "infra": "基礎設施",
}
# Mermaid shape wrappers (open, close) for quoted labels.
SHAPES = {
    "page": ('(["', '"])'),
    "component": ('["', '"]'),
    "state": ('{{"', '"}}'),
    "api": ('[/"', '"/]'),
    "service": ('["', '"]'),
    "data": ('[("', '")]'),
    "external": ('>"', '"]'),
    "job": ('[["', '"]]'),
    "infra": ('[\\"', '"\\]'),
}
STATUS_STYLE = {
    "done": "fill:#d1fae5,stroke:#059669,color:#064e3b",
    "failing": "fill:#fee2e2,stroke:#dc2626,color:#7f1d1d",
    "added": "fill:#dbeafe,stroke:#2563eb,color:#1e3a8a",
    "modified": "fill:#fef3c7,stroke:#d97706,color:#78350f",
    "removed": "fill:#f3f4f6,stroke:#9ca3af,color:#6b7280,stroke-dasharray:4 3",
}


def _esc(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace('"', "#quot;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("\n", " ")
    )


def mermaid(
    arch: Architecture,
    node_classes: dict[str, str] | None = None,
    extra_nodes: list[Node] | None = None,
    links: bool = False,
) -> str:
    """Return a Mermaid flowchart.

    node_classes maps node id -> one of STATUS_STYLE keys.
    extra_nodes are drawn too (used to show removed nodes in a diff).
    links adds click-to-anchor directives for the HTML viewer.
    """
    node_classes = node_classes or {}
    nodes = list(arch.nodes) + list(extra_nodes or [])
    mid = {n.id: f"n{i}" for i, n in enumerate(nodes)}
    lines = ["flowchart LR"]
    for layer in LAYER_ORDER:
        members = [n for n in nodes if n.layer == layer]
        if not members:
            continue
        lines.append(f'  subgraph L_{layer}["{LAYER_TITLE[layer]}"]')
        for n in members:
            o, c = SHAPES[n.type]
            label = f"{_esc(n.title)}<br/><small>{_esc(n.id)}</small>"
            lines.append(f"    {mid[n.id]}{o}{label}{c}")
        lines.append("  end")
    for e in arch.edges:
        text = e.label or e.kind
        arrow = "-.->" if e.kind == "navigates" else "-->"
        lines.append(f'  {mid[e.source]} {arrow}|"{_esc(text)}"| {mid[e.target]}')
    used = sorted({c for c in node_classes.values() if c in STATUS_STYLE})
    for c in used:
        lines.append(f"  classDef {c} {STATUS_STYLE[c]}")
    for nid, c in node_classes.items():
        if nid in mid and c in STATUS_STYLE:
            lines.append(f"  class {mid[nid]} {c}")
    if links:
        for n in nodes:
            lines.append(f'  click {mid[n.id]} href "#node-{n.id}"')
    return "\n".join(lines)


def _node_md(n: Node, status: str | None = None, comments: list[dict] | None = None) -> list[str]:
    out = [f"### {n.title} `{n.id}`", ""]
    meta = f"類型：{TYPE_TITLE[n.type]}　｜　層：{LAYER_TITLE[n.layer]}"
    if status:
        meta += f"　｜　狀態：{status}"
    out += [meta, ""]
    if n.description:
        out += [n.description, ""]
    if n.acceptance:
        out.append("**驗收標準**")
        out += [f"- {a}" for a in n.acceptance]
        out.append("")
    if n.decisions:
        out.append("**已確認決策**")
        out += [f"- {d.question} → **{d.answer}**（{d.source}）" for d in n.decisions]
        out.append("")
    if n.tests:
        out.append("**測試設計**")
        out += [f"- `{t.id}` [{t.kind}] {t.description}" for t in n.tests]
        out.append("")
    if comments:
        out.append("**討論紀錄**")
        out += [f"- {c['ts'][:16]} {c['author']}：{c['text']}" for c in comments]
        out.append("")
    return out


def architecture_md(
    project_name: str,
    version: int,
    reason: str,
    arch: Architecture,
    phase: str,
    statuses: dict[str, str] | None = None,
    comments: list[dict] | None = None,
) -> str:
    statuses = statuses or {}
    comments = comments or []
    classes = {k: v for k, v in statuses.items() if v in ("done", "failing")}
    out = [
        f"# {project_name} — 架構圖 v{version}",
        "",
        f"> 階段：**{phase}**　｜　此版本變更理由：{reason}",
        "> 此檔案由 ArchFlow 自動產生，請勿手動修改；要修改請在對話中跟 AI 說。",
        "",
        "```mermaid",
        mermaid(arch, classes),
        "```",
        "",
        "## 節點說明",
        "",
    ]
    for layer in LAYER_ORDER:
        for n in [n for n in arch.nodes if n.layer == layer]:
            out += _node_md(n, statuses.get(n.id), [c for c in comments if c["node_id"] == n.id])
    if arch.edges:
        out += ["## 關係", "", "| 從 | 關係 | 到 | 說明 |", "|---|---|---|---|"]
        out += [f"| `{e.source}` | {e.kind} | `{e.target}` | {e.label} |" for e in arch.edges]
        out.append("")
    return "\n".join(out)


def test_plan_md(project_name: str, version: int, arch: Architecture) -> str:
    out = [
        f"# {project_name} — 測試計畫（架構 v{version}）",
        "",
        "> AI 在討論階段設計的測試。有疑問或想新增/修改測試，直接在對話中提出。",
        "",
    ]
    total = 0
    for layer in LAYER_ORDER:
        for n in [n for n in arch.nodes if n.layer == layer]:
            out.append(f"## {n.title} `{n.id}`")
            if not n.tests:
                out += ["", "_（尚未設計測試）_", ""]
                continue
            out += ["", "| 測試 ID | 類型 | 內容 |", "|---|---|---|"]
            for t in n.tests:
                out.append(f"| `{t.id}` | {t.kind} | {t.description} |")
                total += 1
            out.append("")
    out.insert(3, f"共 {total} 個測試。\n")
    return "\n".join(out)


HTML_TEMPLATE = """<!doctype html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  :root {{ --bg:#fafaf9; --fg:#1c1917; --muted:#78716c; --card:#fff; --line:#e7e5e4; --accent:#2563eb; }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --bg:#1c1917; --fg:#f5f5f4; --muted:#a8a29e; --card:#292524; --line:#44403c; --accent:#60a5fa; }}
  }}
  body {{ margin:0; font-family: system-ui, "Noto Sans TC", sans-serif; background:var(--bg); color:var(--fg); }}
  header {{ padding:20px 24px; border-bottom:1px solid var(--line); }}
  header h1 {{ margin:0 0 6px; font-size:22px; }}
  header p {{ margin:0; color:var(--muted); font-size:14px; }}
  main {{ padding:16px 24px 48px; max-width:1200px; margin:0 auto; }}
  .diagram {{ background:#fff; border:1px solid var(--line); border-radius:10px; padding:16px; overflow:auto; }}
  .legend {{ font-size:13px; color:var(--muted); margin:8px 0 24px; }}
  .node {{ background:var(--card); border:1px solid var(--line); border-radius:10px; padding:14px 18px; margin:12px 0; scroll-margin-top:16px; }}
  .node:target {{ outline:3px solid var(--accent); }}
  .node h3 {{ margin:0 0 4px; font-size:17px; }}
  .meta {{ color:var(--muted); font-size:13px; margin-bottom:8px; }}
  .tag {{ display:inline-block; padding:1px 8px; border-radius:99px; font-size:12px; border:1px solid var(--line); margin-left:6px; }}
  .done {{ background:#d1fae5; color:#064e3b; }} .failing {{ background:#fee2e2; color:#7f1d1d; }} .todo {{ background:#f5f5f4; color:#57534e; }}
  h4 {{ margin:10px 0 4px; font-size:14px; }}
  ul {{ margin:4px 0; padding-left:20px; }} li {{ margin:2px 0; font-size:14px; }}
  code {{ font-size:12px; }}
</style>
</head>
<body>
<header>
  <h1>{title}</h1>
  <p>{subtitle}</p>
</header>
<main>
  <div class="diagram"><pre class="mermaid">{mermaid}</pre></div>
  <div class="legend">點擊節點可跳到說明。形狀：(頁面) [元件/服務] /API/ {{狀態}} [(資料)] &gt;外部] [[背景工作]]；虛線＝頁面導覽。綠色＝已完成，紅色＝測試未過。</div>
  {nodes}
</main>
<script src="https://cdn.jsdelivr.net/npm/mermaid@10.9.1/dist/mermaid.min.js"></script>
<script>mermaid.initialize({{ startOnLoad: true, securityLevel: "loose", theme: "default", flowchart: {{ htmlLabels: true }} }});</script>
</body>
</html>
"""


def _li(items: list[str]) -> str:
    return "<ul>" + "".join(f"<li>{i}</li>" for i in items) + "</ul>"


def architecture_html(
    project_name: str,
    version: int,
    reason: str,
    arch: Architecture,
    phase: str,
    statuses: dict[str, str] | None = None,
    comments: list[dict] | None = None,
) -> str:
    statuses = statuses or {}
    comments = comments or []
    classes = {k: v for k, v in statuses.items() if v in ("done", "failing")}
    blocks = []
    for layer in LAYER_ORDER:
        for n in [n for n in arch.nodes if n.layer == layer]:
            e = html.escape
            st = statuses.get(n.id)
            tag = f'<span class="tag {e(st)}">{e(st)}</span>' if st else ""
            parts = [
                f'<section class="node" id="node-{e(n.id)}">',
                f"<h3>{e(n.title)} <code>{e(n.id)}</code>{tag}</h3>",
                f'<div class="meta">{TYPE_TITLE[n.type]} · {LAYER_TITLE[n.layer]}</div>',
            ]
            if n.description:
                parts.append(f"<div>{e(n.description)}</div>")
            if n.acceptance:
                parts.append("<h4>驗收標準</h4>" + _li([e(a) for a in n.acceptance]))
            if n.decisions:
                parts.append(
                    "<h4>已確認決策</h4>"
                    + _li([f"{e(d.question)} → <b>{e(d.answer)}</b> ({e(d.source)})" for d in n.decisions])
                )
            if n.tests:
                parts.append(
                    "<h4>測試設計</h4>"
                    + _li([f"<code>{e(t.id)}</code> [{e(t.kind)}] {e(t.description)}" for t in n.tests])
                )
            outgoing = [x for x in arch.edges if x.source == n.id]
            incoming = [x for x in arch.edges if x.target == n.id]
            if outgoing or incoming:
                rel = [f'{e(x.kind)} → <a href="#node-{e(x.target)}">{e(x.target)}</a>' for x in outgoing]
                rel += [f'<a href="#node-{e(x.source)}">{e(x.source)}</a> → {e(x.kind)}' for x in incoming]
                parts.append("<h4>關係</h4>" + _li(rel))
            nc = [c for c in comments if c["node_id"] == n.id]
            if nc:
                parts.append(
                    "<h4>討論紀錄</h4>"
                    + _li([f"{e(c['ts'][:16])} {e(c['author'])}：{e(c['text'])}" for c in nc])
                )
            parts.append("</section>")
            blocks.append("\n".join(parts))
    return HTML_TEMPLATE.format(
        title=html.escape(f"{project_name} — 架構圖 v{version}"),
        subtitle=html.escape(f"階段：{phase}　｜　變更理由：{reason}"),
        mermaid=html.escape(mermaid(arch, classes, links=True)),
        nodes="\n".join(blocks),
    )


def node_summary(n: Node) -> dict:
    return json.loads(n.model_dump_json())
