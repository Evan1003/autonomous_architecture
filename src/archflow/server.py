"""ArchFlow MCP server: exposes the architecture-first workflow as tools."""

from __future__ import annotations

import os
from typing import Literal

import functools

from pydantic import ValidationError

try:  # mcp >= 2
    from mcp.server.mcpserver import MCPServer as _Server
    from mcp.server.mcpserver.exceptions import ToolError
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP as _Server  # type: ignore[no-redef]
    from mcp.server.fastmcp.exceptions import ToolError  # type: ignore[no-redef]

from .models import ArchPatch, Architecture, Edge, Node, Question, TestCase
from .project import ArchFlowError, Project

INSTRUCTIONS = """\
ArchFlow enforces an architecture-first workflow. Follow it strictly:

1. DISCUSS: when the user describes a project, call arch_init (once), then arch_propose a draft
   architecture (pages/screens, components, state, APIs, services, data, external services).
   Everything the user did not state explicitly, and every choice between approaches, becomes a
   questionnaire (questions_create) with concrete options and your recommendation. Do not guess.
2. After the user fills the questionnaire, call questions_collect and apply the answers with
   arch_update (record them as node decisions). Show the user the diagram (the viewer file
   .archflow/architecture.html or the mermaid text).
3. The user may ask about or change any node: use node_detail to answer, node_comment to record the
   question, arch_update to change it. Every change creates a new version; arch_rollback restores one.
4. Design unit tests for every node (tests_design) and let the user review TEST_PLAN.md.
5. Only when the user explicitly says the architecture is OK, call arch_approve with their words.
6. IMPLEMENT strictly: loop impl_next -> write tests -> write code -> run tests -> impl_done.
   Never build anything that is not in the approved diagram. If something is missing or wrong,
   stop and call change_request.
7. Then conformance_check and checklist_generate; the user ticks CHECKLIST.md while testing.
8. On any feedback, call checklist_status, ask about every unchecked item and reported issue,
   then change_request to reopen discussion: update the diagram first, re-approve, then implement.
Call arch_status whenever unsure what to do next. Talk to the user in their language.
"""

mcp = _Server("archflow", instructions=INSTRUCTIONS)


def _tool(fn):
    """Register a tool whose workflow/validation errors reach the model verbatim."""

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except (ArchFlowError, ValidationError, ValueError) as e:
            raise ToolError(str(e)) from e

    return mcp.tool()(wrapper)


def _project() -> Project:
    root = os.environ.get("ARCHFLOW_PROJECT_DIR") or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    return Project(root)


# ----------------------------------------------------------------- overview
@_tool
def arch_init(
    name: str,
    requirements: str,
    project_type: Literal["web", "mobile", "fullstack", "other"] = "web",
) -> dict:
    """Start an ArchFlow project in the current directory. Pass the user's requirements verbatim.
    Returns guidance on node types and the decisions that must be confirmed with the user."""
    return _project().init(name, requirements, project_type)


@_tool
def arch_status() -> dict:
    """Current phase, versions, pending questionnaire/progress and the recommended next action."""
    return _project().status()


# ------------------------------------------------------------ architecture
@_tool
def arch_propose(nodes: list[Node], edges: list[Edge], reason: str) -> dict:
    """Submit a complete architecture (new version). Use for the first draft or a full redesign.
    Edges point from the dependent node to what it uses (page -> api -> service -> data);
    use kind='navigates' for page-to-page navigation."""
    return _project().propose(Architecture(nodes=nodes, edges=edges), reason)


@_tool
def arch_update(patch: ArchPatch, reason: str) -> dict:
    """Change part of the architecture (new version): upsert/remove nodes, add/remove edges.
    Upserted nodes replace the whole node, so include all fields you want to keep."""
    return _project().update(patch, reason)


@_tool
def arch_get(version: int | None = None, include_json: bool = True) -> dict:
    """Get an architecture version (default: current) as JSON plus Mermaid text."""
    return _project().get(version, include_json)


@_tool
def node_detail(node_id: str) -> dict:
    """Everything about one node: spec, decisions, tests, edges, comments, progress, and in which
    versions it changed. Use this to answer the user's questions about a node."""
    return _project().node_detail(node_id)


@_tool
def node_comment(node_id: str, text: str, author: Literal["user", "ai"] = "user") -> dict:
    """Record a question or change request the user made about a node (or the AI's answer)."""
    return _project().comment(node_id, text, author)


@_tool
def arch_diff(from_version: int, to_version: int | None = None) -> dict:
    """Compare two versions (default to current). Mermaid highlights added/modified/removed nodes."""
    return _project().diff(from_version, to_version)


@_tool
def arch_history() -> dict:
    """List all architecture versions with reasons, git commits and which were approved."""
    return _project().history()


@_tool
def arch_rollback(version: int, reason: str) -> dict:
    """Restore an old version as a new version (history is kept). Discussion phase only."""
    return _project().rollback(version, reason)


# ------------------------------------------------------------ questionnaire
@_tool
def questions_create(questions: list[Question]) -> dict:
    """Write .archflow/questionnaire.md for everything unclear or needing the user's choice.
    Prefer single/multi choice with concrete options + pros/cons, mark 'recommended'."""
    return _project().questions_create(questions)


@_tool
def questions_collect() -> dict:
    """Parse the user's answers from questionnaire.md. Reports unanswered/ambiguous questions."""
    return _project().questions_collect()


# -------------------------------------------------------------------- tests
@_tool
def tests_design(node_tests: dict[str, list[TestCase]], reason: str) -> dict:
    """Set the designed test cases for nodes (replaces each listed node's tests). Writes TEST_PLAN.md."""
    return _project().tests_design(node_tests, reason)


# ----------------------------------------------------------------- approval
@_tool
def arch_approve(user_confirmation: str) -> dict:
    """Lock the current version for implementation. ONLY call after the user explicitly approves;
    pass their exact words. Requires no pending questionnaire and tests on every non-external node."""
    return _project().approve(user_confirmation)


# ----------------------------------------------------------- implementation
@_tool
def impl_next() -> dict:
    """Next node to implement (dependencies first) with its spec and designed tests."""
    return _project().impl_next()


@_tool
def impl_done(node_id: str, files: list[str], tests_passing: bool, note: str = "") -> dict:
    """Report a node implemented. files: paths relative to the project root. Rejects nodes that are
    not in the approved architecture."""
    return _project().impl_done(node_id, files, tests_passing, note)


@_tool
def conformance_check() -> dict:
    """Check every node is done and find source files that are not linked to any node."""
    return _project().conformance()


# --------------------------------------------------------------- acceptance
@_tool
def checklist_generate() -> dict:
    """Write CHECKLIST.md (acceptance items per node) for the user to tick while testing."""
    return _project().checklist_generate()


@_tool
def checklist_status() -> dict:
    """Read CHECKLIST.md: checked/unchecked items and issues the user wrote."""
    return _project().checklist_status()


@_tool
def change_request(description: str) -> dict:
    """Reopen discussion for fixes or new features. Carries unchecked checklist items and reported
    issues into the new round. The diagram must be updated and re-approved before coding."""
    return _project().change_request(description)


@_tool
def log_export() -> dict:
    """Write COLLABORATION_LOG.md: the full timeline of discussions, versions and approvals."""
    return _project().export_log()


@mcp.prompt()
def archflow_start(idea: str) -> str:
    """Start a new project with the ArchFlow workflow."""
    return (
        "Use the ArchFlow tools for this project. Follow the server instructions strictly: draft the "
        "architecture first, turn every unclear point into a questionnaire, and do not write code until "
        f"I approve the diagram.\n\nMy idea:\n{idea}"
    )


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
