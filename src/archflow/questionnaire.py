"""Render questionnaires as fillable Markdown and parse the user's answers back."""

from __future__ import annotations

import re

from .models import Question

TYPE_LABEL = {"single": "單選", "multi": "複選", "text": "簡答"}

QID_RE = re.compile(r"<!--\s*qid:\s*([^\s>]+)\s*-->")
OPT_RE = re.compile(r"^\s*-\s*\[([ xXvV✓✔])\]\s*([A-Za-z0-9]+)\.\s")
OTHER_RE = re.compile(r"^\s*-\s*\[([ xXvV✓✔])\]\s*其他\s*[:：]\s*(.*)$")
ANSWER_RE = re.compile(r"^\s*回答\s*[:：]\s*(.*)$")
NOTE_RE = re.compile(r"^\s*補充說明\s*[:：]\s*(.*)$")


def render(questions: list[Question], round_no: int, version: int | None, project_name: str) -> str:
    v = f"（架構 v{version}）" if version else ""
    out = [
        f"# {project_name} — 需求確認問卷 第 {round_no} 輪{v}",
        "",
        "**填寫方式**",
        "- 選擇題：在選項的 `[ ]` 裡填 `x`，變成 `[x]`（單選題只勾一個）。",
        "- 都不適合就勾「其他」並在冒號後面寫你的想法。",
        "- 簡答題：直接寫在「回答：」後面（可以換行）。",
        "- 有任何補充寫在「補充說明：」後面。",
        "- 填完存檔，回到 Claude Code 說「問卷填好了」。",
        "",
    ]
    for q in questions:
        out += ["---", "", f"## {q.id}. {q.question} <!-- qid:{q.id} -->", ""]
        meta = f"類型：{TYPE_LABEL[q.type]}"
        if q.node_ids:
            meta += "　｜　相關節點：" + ", ".join(f"`{n}`" for n in q.node_ids)
        out.append(meta)
        if q.why:
            out.append(f"為什麼要問：{q.why}")
        out.append("")
        if q.type in ("single", "multi"):
            for o in q.options:
                rec = "　⭐ AI 建議" if q.recommended == o.key else ""
                out.append(f"- [ ] {o.key}. {o.label}{rec}")
                if o.detail:
                    out.append(f"  - {o.detail}")
            if q.allow_other:
                out.append("- [ ] 其他：")
            out.append("")
        else:
            out += ["回答：", ""]
        out += ["補充說明：", ""]
    return "\n".join(out).rstrip() + "\n"


def _checked(mark: str) -> bool:
    return mark.strip() != ""


def parse(text: str, questions: list[Question]) -> dict:
    """Parse a filled questionnaire.

    Returns {"answers": [...], "unanswered": [ids], "problems": [str]}.
    """
    by_id = {q.id: q for q in questions}
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in text.splitlines():
        m = QID_RE.search(line)
        if m and line.lstrip().startswith("#"):
            current = m.group(1)
            sections[current] = []
            continue
        if current is not None:
            sections[current].append(line)

    answers, unanswered, problems = [], [], []
    for q in questions:
        lines = sections.get(q.id)
        if lines is None:
            problems.append(f"{q.id}: 在問卷中找不到這一題（qid 標記被刪掉了？）")
            unanswered.append(q.id)
            continue
        selected, other = [], None
        free: list[str] = []
        note: list[str] = []
        mode = None  # "answer" | "note"
        for line in lines:
            if line.strip() == "---":
                mode = None
                continue
            m = OPT_RE.match(line)
            if m:
                mode = None
                if _checked(m.group(1)):
                    selected.append(m.group(2))
                continue
            m = OTHER_RE.match(line)
            if m:
                mode = None
                txt = m.group(2).strip()
                if _checked(m.group(1)) or txt:
                    other = txt or "(勾選了其他但未填寫)"
                continue
            m = ANSWER_RE.match(line)
            if m:
                mode = "answer"
                if m.group(1).strip():
                    free.append(m.group(1).strip())
                continue
            m = NOTE_RE.match(line)
            if m:
                mode = "note"
                if m.group(1).strip():
                    note.append(m.group(1).strip())
                continue
            if mode and line.strip():
                (free if mode == "answer" else note).append(line.strip())

        opt_label = {o.key: o.label for o in q.options}
        unknown = [k for k in selected if k not in opt_label]
        if unknown:
            problems.append(f"{q.id}: 未知選項 {unknown}")
        selected = [k for k in selected if k in opt_label]
        if q.type == "single" and len(selected) + (1 if other else 0) > 1:
            problems.append(f"{q.id}: 單選題勾了多個選項，請使用者確認")

        is_answered = bool(selected or other) if q.type != "text" else bool(free)
        if not is_answered:
            unanswered.append(q.id)
        answers.append(
            {
                "id": q.id,
                "question": q.question,
                "node_ids": q.node_ids,
                "selected": [{"key": k, "label": opt_label[k]} for k in selected],
                "other": other,
                "text": "\n".join(free) or None,
                "note": "\n".join(note) or None,
                "answered": is_answered,
            }
        )
    for sid in sections:
        if sid not in by_id:
            problems.append(f"問卷中有未知題號 {sid}")
    return {"answers": answers, "unanswered": unanswered, "problems": problems}
