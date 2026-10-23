"""Starter guidance for web / mobile app projects.

These are not fixed architectures. They tell the AI which layers a project
of this kind normally needs and which decisions it must not guess.
"""

from __future__ import annotations

ProjectType = str  # "web" | "mobile" | "fullstack" | "other"

COMMON_QUESTIONS = [
    "使用者是誰？需要登入嗎？登入方式（email/密碼、Google、Apple、手機簡訊）？",
    "資料要存在哪裡（本機、雲端資料庫、Firebase/Supabase 等 BaaS）？需要多裝置同步嗎？",
    "有沒有角色/權限（一般使用者、管理員）？",
    "需要串接哪些外部服務（金流、地圖、推播、Email、AI API）？",
    "部署/上架方式與預算（免費方案、自架、雲端）？",
    "MVP 必須有哪些功能？哪些可以之後再做？",
]

TYPE_GUIDANCE: dict[str, dict] = {
    "web": {
        "label": "網頁應用 (Web App)",
        "typical_nodes": [
            "page：每個主要頁面（首頁、登入、列表、詳細頁、設定…）",
            "component：跨頁共用元件（導覽列、表單、卡片）",
            "state：前端狀態（登入狀態、購物車…）",
            "api：每個後端 endpoint（或 BaaS 呼叫）",
            "service：後端商業邏輯",
            "data：資料表/集合",
            "external：第三方服務",
            "infra：部署（Vercel/Netlify/Render…）",
        ],
        "questions": [
            "前端框架（React/Next.js、Vue/Nuxt、純 HTML+JS）？",
            "需要 SEO / 伺服器端渲染嗎？",
            "要支援手機瀏覽（RWD）嗎？要做成 PWA 嗎？",
            "後端要自己寫（Node/Express、Python/FastAPI…）還是用 BaaS？",
        ],
    },
    "mobile": {
        "label": "手機 App",
        "typical_nodes": [
            "page：每個畫面（screen）",
            "component：共用 UI 元件",
            "state：App 狀態管理",
            "data：本機儲存（SQLite/AsyncStorage）與雲端資料模型",
            "api / service：後端或 BaaS",
            "external：推播、相機、定位、金流、登入供應商",
            "infra：建置與上架（EAS、App Store、Google Play）",
        ],
        "questions": [
            "平台：iOS、Android 或兩者？",
            "技術：跨平台（React Native/Expo、Flutter）或原生（Swift/Kotlin）？",
            "需要離線使用嗎？",
            "需要哪些裝置權限（相機、定位、通知、相簿）？",
            "要上架商店，還是只做可安裝的測試版本？",
        ],
    },
    "fullstack": {
        "label": "網頁 + App（共用後端）",
        "typical_nodes": [
            "前端分成 web 與 app 兩組 page/component（id 用 web.* 與 app.* 區分）",
            "共用的 api / service / data",
            "external 與 infra 同上",
        ],
        "questions": [
            "Web 與 App 功能是否完全相同？哪些只在其中一邊？",
            "要不要共用程式碼（例如 React + React Native / Expo Router）？",
        ],
    },
    "other": {"label": "其他", "typical_nodes": [], "questions": []},
}


def guidance(project_type: str) -> dict:
    g = TYPE_GUIDANCE.get(project_type, TYPE_GUIDANCE["other"])
    return {
        "project_type": project_type,
        "label": g["label"],
        "node_types": {
            "page": "頁面/畫面",
            "component": "UI 元件",
            "state": "前端狀態",
            "api": "API endpoint",
            "service": "後端邏輯",
            "data": "資料模型/儲存",
            "external": "第三方服務",
            "job": "背景工作",
            "infra": "部署/設定",
        },
        "typical_nodes": g["typical_nodes"],
        "decisions_to_confirm": COMMON_QUESTIONS + g["questions"],
        "instruction": (
            "Draft an architecture with arch_propose using these node types. Any decision in "
            "decisions_to_confirm that the user's requirements do not answer explicitly MUST become "
            "a questionnaire question (questions_create) instead of a guess. Offer concrete options "
            "with pros/cons and mark the one you recommend."
        ),
    }
