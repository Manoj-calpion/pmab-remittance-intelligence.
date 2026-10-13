"""LangGraph supervisor for the five analytical agents.

Agents call read-only tools. The model only narrates evidence that those tools
already calculated. Routing is deterministic so it can be tested without an LLM.
"""

import time
from decimal import Decimal
from typing import TypedDict

from langgraph.graph import END, StateGraph
from sqlalchemy.orm import Session

from app.agents.llm import InsightDraft, MockLLMProvider, build_provider, exposure_amount
from app.agents.tools import ReadOnlyTools
from app.core.config import Settings
from app.core.phi import assert_no_phi_payload


class InvestigationState(TypedDict, total=False):
    question: str
    plan: list[str]
    completed: list[str]
    next_agent: str | None
    iteration: int
    max_iterations: int
    deadline: float
    evidence: dict
    agent_outputs: list[dict]
    errors: list[str]
    needs_human_review: bool
    final: dict


def plan_agents(question: str) -> list[str]:
    text = question.lower()
    planned: list[str] = []
    if any(word in text for word in ("denial", "denied", "carc", "rarc", "coding", "authorization", "procedure")):
        planned.append("denial")
    if any(word in text for word in ("delay", "underpay", "reimburse", "payment", "variance")):
        planned.append("payment")
    if any(word in text for word in ("payer", "compare", "trend", "which")):
        planned.append("payer")
    if any(word in text for word in ("why", "root", "cause", "increas")):
        planned.append("root_cause")
    if not planned:
        planned = ["denial", "payment", "payer"]
    ordered: list[str] = []
    for name in planned:
        if name not in ordered:
            ordered.append(name)
    ordered.append("insight")
    return ordered


def _fmt_rate(value: str | None) -> str:
    if value is None:
        return "unavailable"
    return str(Decimal(value).quantize(Decimal("0.0001")))


def denial_output(tools: ReadOnlyTools) -> dict:
    evidence = tools.denial_summary()
    claim = evidence["claim_level"]
    top = evidence["by_category"][0]["label"] if evidence["by_category"] else "none"
    payer = max(evidence["by_payer"], key=lambda item: Decimal(item["denial_rate"] or "0"), default=None)
    payer_text = "No payer has a calculated denial rate."
    if payer and payer["denial_rate"] is not None:
        payer_text = f"{payer['label']} denial rate is {_fmt_rate(payer['denial_rate'])} across {payer['claims']} claims."
    summary = (
        f"Denial rate is {_fmt_rate(claim['denial_rate'])} on {claim['claims']} claims. "
        f"Denied amount is {claim['denied_amount']}. The largest denial category is {top}. {payer_text}"
    )
    return {"agent": "denial", "summary": summary, "evidence": evidence}


def payment_output(tools: ReadOnlyTools) -> dict:
    evidence = tools.payment_summary()
    delays = evidence["delays"]
    underpay = evidence["underpayments"]
    summary = (
        f"Payment delay basis is {delays['metric_basis']}. Delayed count is {delays['delayed_count']}. "
        f"Delay records with insufficient data: {delays['insufficient_data_count']}. "
        f"Underpayment basis is {underpay['metric_basis']}. Underpaid amount is {underpay['underpaid_amount']}. "
        f"{underpay['notice']}"
    )
    return {"agent": "payment", "summary": summary, "evidence": evidence}


def payer_output(tools: ReadOnlyTools) -> dict:
    evidence = tools.payer_summary()
    parts = []
    for payer in evidence["payers"]:
        parts.append(f"{payer['label']} denial rate {_fmt_rate(payer['denial_rate'])} denied amount {payer['denied_amount']}")
    summary = "Payer comparison: " + ("; ".join(parts) if parts else "no payer rows were available.")
    return {"agent": "payer", "summary": summary, "evidence": evidence}


def root_cause_output(tools: ReadOnlyTools, question: str) -> dict:
    category = "authorization" if "authorization" in question.lower() else "coding" if "coding" in question.lower() else "authorization"
    category_evidence = tools.category_summary(category)
    knowledge = tools.knowledge(question)
    missing = ["Approved payer policy documents are not loaded."]
    if knowledge["approved_citation_count"] == 0:
        missing.append("Retrieved excerpts are synthetic samples or unapproved documents and cannot confirm a cause.")
    summary = (
        f"Potential contributing pattern in {category} denials: "
        f"{category_evidence['claim_level']['denied_claims']} denied claims and denied amount "
        f"{category_evidence['claim_level']['denied_amount']}. "
        "This is a hypothesis for investigation, not a confirmed cause."
    )
    return {
        "agent": "root_cause",
        "summary": summary,
        "evidence": {"category": category_evidence, "knowledge": knowledge, "missing_evidence": missing},
    }


def insight_output(state: InvestigationState, tools: ReadOnlyTools, settings: Settings, llm) -> dict:
    evidence = {
        "question_handled_as_data": True,
        "agents": state.get("agent_outputs", []),
        "financial_exposure": _exposure_from_outputs(state.get("agent_outputs", [])),
    }
    assert_no_phi_payload(evidence)
    findings = [item["summary"] for item in state.get("agent_outputs", []) if item.get("agent") != "insight"]
    missing: list[str] = []
    citations: list[str] = []
    for item in state.get("agent_outputs", []):
        item_evidence = item.get("evidence") or {}
        missing.extend(item_evidence.get("missing_evidence", []))
        for citation in item_evidence.get("knowledge", {}).get("citations", []):
            citations.append(f"{citation['title']} ({citation['source_label']})")
    has_claims = any(_evidence_has_activity(item.get("evidence") or {}) for item in state.get("agent_outputs", []))
    if not findings or not has_claims:
        draft = InsightDraft(
            sufficient_evidence=False,
            summary="Insufficient evidence. No analyzed remittance claims are available for this question.",
            findings=[],
            financial_exposure=None,
            recommendations=["Load remittance files and approved contract or submission data before relying on an answer."],
            missing_evidence=missing or ["No remittance claims are available."],
            citations=citations,
            disclaimer="No reimbursement amount in this response was calculated by a language model.",
        )
    else:
        draft = InsightDraft(
            sufficient_evidence=True,
            summary=" ".join(findings),
            findings=findings,
            financial_exposure=evidence["financial_exposure"],
            recommendations=[
                "Review the highest denial category with the payer and the original remittance trace.",
                "Treat statistical anomalies as leads. They are not confirmed payment errors.",
                "Do not use synthetic demo contracts as a basis for a recovery demand.",
            ],
            missing_evidence=missing or ["Confirm whether approved payer policies and contract rates are loaded."],
            citations=citations,
            disclaimer="Language-model text is limited to tool evidence. It is not the source of reimbursement amounts.",
        )
    try:
        completed = llm.complete_json(evidence, draft)
        provider = llm.name
        model_id = llm.model_id
        summary = completed.summary
        recommendations = completed.recommendations
        insufficient = not completed.sufficient_evidence
        llm_error = None
    except Exception as exc:
        if isinstance(llm, MockLLMProvider):
            raise
        provider = llm.name
        model_id = llm.model_id
        summary = draft.summary
        recommendations = draft.recommendations
        insufficient = True
        llm_error = str(exc)[:400]
    exposure = exposure_amount({"financial_exposure": evidence["financial_exposure"]})
    needs_review = exposure >= settings.human_review_exposure_threshold
    return {
        "agent": "insight",
        "summary": summary,
        "recommendations": recommendations,
        "insufficient_evidence": insufficient,
        "provider_name": provider,
        "model_id": model_id,
        "llm_error": llm_error,
        "needs_human_review": needs_review,
        "evidence": evidence,
        "missing_evidence": draft.missing_evidence,
        "citations": citations,
        "disclaimer": draft.disclaimer,
    }


def _evidence_has_activity(evidence: dict) -> bool:
    level = evidence.get("claim_level") or {}
    if int(level.get("claims") or 0) > 0:
        return True
    category = (evidence.get("category") or {}).get("claim_level") or {}
    if int(category.get("claims") or 0) > 0:
        return True
    if any(int(payer.get("claims") or 0) > 0 for payer in evidence.get("payers") or []):
        return True
    delays = evidence.get("delays") or {}
    if int(delays.get("calculated_count") or 0) + int(delays.get("insufficient_data_count") or 0) > 0:
        return True
    under = evidence.get("underpayments") or {}
    if int(under.get("underpaid_count") or 0) + int(under.get("insufficient_data_count") or 0) > 0:
        return True
    return False


def _exposure_from_outputs(outputs: list[dict]) -> str | None:
    for output in outputs:
        claim = output.get("evidence", {}).get("claim_level", {})
        if claim.get("denied_amount"):
            return str(claim["denied_amount"])
        underpaid = output.get("evidence", {}).get("underpayments", {}).get("underpaid_amount")
        if underpaid:
            return str(underpaid)
    return None


def build_graph(db: Session, settings: Settings):
    tools = ReadOnlyTools(db, settings)
    llm = build_provider(settings)

    def supervisor(state: InvestigationState) -> InvestigationState:
        updated = dict(state)
        updated["iteration"] = int(updated.get("iteration", 0)) + 1
        completed = list(updated.get("completed", []))
        errors = list(updated.get("errors", []))
        timed_out = time.monotonic() > float(updated["deadline"])
        too_many = updated["iteration"] > int(updated["max_iterations"])
        pending = [name for name in updated.get("plan", []) if name not in completed]
        if (timed_out or too_many) and "insight" not in completed:
            errors.append("Stopped after the iteration or time limit. Partial evidence was sent to the insight step.")
            pending = ["insight"]
        elif timed_out or too_many:
            errors.append("Stopped after the iteration or time limit.")
            pending = []
        updated["errors"] = errors
        updated["next_agent"] = pending[0] if pending else None
        return updated

    def route(state: InvestigationState) -> str:
        return state.get("next_agent") or END

    def make_node(name: str):
        def node(state: InvestigationState) -> InvestigationState:
            updated = dict(state)
            if name == "denial":
                output = denial_output(tools)
            elif name == "payment":
                output = payment_output(tools)
            elif name == "payer":
                output = payer_output(tools)
            elif name == "root_cause":
                output = root_cause_output(tools, updated.get("question", ""))
            else:
                output = insight_output(updated, tools, settings, llm)
                updated["needs_human_review"] = bool(output.get("needs_human_review"))
                updated["final"] = output
            updated["agent_outputs"] = [*updated.get("agent_outputs", []), output]
            updated["completed"] = [*updated.get("completed", []), name]
            return updated

        return node

    graph = StateGraph(InvestigationState)
    graph.add_node("supervisor", supervisor)
    for name in ("denial", "payment", "payer", "root_cause", "insight"):
        graph.add_node(name, make_node(name))
        graph.add_edge(name, "supervisor")
    graph.set_entry_point("supervisor")
    graph.add_conditional_edges(
        "supervisor",
        route,
        {
            "denial": "denial",
            "payment": "payment",
            "payer": "payer",
            "root_cause": "root_cause",
            "insight": "insight",
            END: END,
        },
    )
    return graph.compile()


def investigate(db: Session, settings: Settings, question: str) -> dict:
    graph = build_graph(db, settings)
    plan = plan_agents(question)
    state = graph.invoke(
        {
            "question": question,
            "plan": plan,
            "completed": [],
            "iteration": 0,
            "max_iterations": settings.agent_max_iterations,
            "deadline": time.monotonic() + settings.agent_timeout_seconds,
            "agent_outputs": [],
            "errors": [],
            "evidence": {},
        },
        config={"recursion_limit": settings.agent_max_iterations * 4},
    )
    final = state.get("final") or {}
    return {
        "question": question,
        "plan": plan,
        "status": "pending_human_review" if state.get("needs_human_review") else "completed",
        "needs_human_review": bool(state.get("needs_human_review")),
        "agent_outputs": state.get("agent_outputs", []),
        "errors": state.get("errors", []),
        "summary": final.get("summary", "Insufficient evidence."),
        "recommendations": final.get("recommendations", []),
        "insufficient_evidence": final.get("insufficient_evidence", True),
        "provider_name": final.get("provider_name", settings.llm_provider),
        "model_id": final.get("model_id", ""),
        "llm_error": final.get("llm_error"),
        "citations": final.get("citations", []),
        "missing_evidence": final.get("missing_evidence", []),
        "disclaimer": final.get("disclaimer", ""),
    }
