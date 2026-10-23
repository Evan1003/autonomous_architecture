from archflow import questionnaire
from archflow.models import Question

QS = [
    Question(id="Q1", question="App 技術？", node_ids=["app.list"], recommended="A",
             options=[{"key": "A", "label": "Expo"}, {"key": "B", "label": "Flutter"}]),
    Question(id="Q2", question="需要哪些登入方式？", type="multi",
             options=[{"key": "A", "label": "Email"}, {"key": "B", "label": "Google"}, {"key": "C", "label": "Apple"}]),
    Question(id="Q3", question="App 名稱？", type="text"),
]


def fill(md: str, replacements: list[tuple[str, str]]) -> str:
    for old, new in replacements:
        assert old in md, old
        md = md.replace(old, new, 1)
    return md


def test_render_contains_markers_and_recommendation():
    md = questionnaire.render(QS, 1, 2, "Todo")
    assert "<!-- qid:Q1 -->" in md and "<!-- qid:Q3 -->" in md
    assert "- [ ] A. Expo　⭐ AI 建議" in md
    assert "回答：" in md


def test_parse_unfilled_is_all_unanswered():
    res = questionnaire.parse(questionnaire.render(QS, 1, 1, "T"), QS)
    assert res["unanswered"] == ["Q1", "Q2", "Q3"]
    assert res["problems"] == []


def test_parse_filled():
    md = questionnaire.render(QS, 1, 1, "T")
    md = fill(md, [
        ("- [ ] A. Expo", "- [x] A. Expo"),
        ("- [ ] A. Email", "- [X] A. Email"),
        ("- [ ] C. Apple", "- [x] C. Apple"),
        ("\n回答：\n", "\n回答：DoIt\n第二行\n"),
    ])
    res = questionnaire.parse(md, QS)
    assert res["unanswered"] == []
    a = {x["id"]: x for x in res["answers"]}
    assert [s["label"] for s in a["Q1"]["selected"]] == ["Expo"]
    assert [s["key"] for s in a["Q2"]["selected"]] == ["A", "C"]
    assert a["Q3"]["text"] == "DoIt\n第二行"


def test_parse_other_and_note():
    md = questionnaire.render(QS, 1, 1, "T")
    # Q1's "其他" is the first one in the file
    md = md.replace("- [ ] 其他：", "- [ ] 其他：React Native CLI", 1)
    md = md.replace("\n補充說明：\n", "\n補充說明：我比較熟 JS\n", 1)
    a = questionnaire.parse(md, QS)["answers"][0]
    assert a["other"] == "React Native CLI" and a["answered"]
    assert a["note"] == "我比較熟 JS"


def test_single_choice_with_two_ticks_is_a_problem():
    md = questionnaire.render(QS, 1, 1, "T")
    md = md.replace("- [ ] A. Expo", "- [x] A. Expo").replace("- [ ] B. Flutter", "- [x] B. Flutter")
    res = questionnaire.parse(md, QS)
    assert any("Q1" in p for p in res["problems"])


def test_deleted_marker_reported():
    md = questionnaire.render(QS, 1, 1, "T").replace("<!-- qid:Q2 -->", "")
    res = questionnaire.parse(md, QS)
    assert "Q2" in res["unanswered"]
    assert any("Q2" in p for p in res["problems"])
