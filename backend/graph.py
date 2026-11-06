import operator
import re
from time import perf_counter
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from backend.llm import generate
from backend.logging import branch_id, event
from backend.mcp_tools import call_tool
from backend.replies import direct_answer
from backend.schemas import Answer, BranchResult, Critique, Plan, Source


class State(TypedDict, total=False):
    question: str
    plan: Plan
    branch_results: Annotated[list[BranchResult], operator.add]
    sources: list[Source]
    final_answer: str
    synthesized: bool


class BranchState(TypedDict, total=False):
    branch_id: str
    question: str
    hyde_text: str | None
    sources: list[Source]
    draft: Answer
    critic: Critique
    attempts: int
    branch_results: list[BranchResult]


def context(sources: list[Source]) -> list[dict]:
    return [source.model_dump() for source in sources]


def citation_ids(answer: str) -> set[str]:
    return set(re.findall(r"\[([^\[\]\n]+)\]", answer))


def valid_citations(answer: Answer, sources: list[Source]) -> bool:
    ids = citation_ids(answer.answer)
    allowed = {source.source_id for source in sources}
    return ids <= allowed and (bool(ids) or not answer.sufficient)


async def planner(state: State) -> dict:
    started = perf_counter()
    plan = await generate("planner", {"question": state["question"]}, Plan)
    if plan.intent == "documents":
        plan.search_question = plan.search_question.strip() or state["question"]
        plan.subquestions = [q.strip() for q in plan.subquestions if q.strip()]
        plan.subquestions = plan.subquestions or [plan.search_question]
    else:
        plan.subquestions = []
        plan.hyde_text = None
    event(
        "planner",
        intent=plan.intent,
        subquestions=plan.subquestions,
        rewritten_query=plan.search_question,
        hyde_generated=bool(plan.hyde_text),
        duration_ms=round((perf_counter() - started) * 1000),
    )
    return {"plan": plan}


def route(state: State):
    plan = state["plan"]
    if plan.intent != "documents":
        return "direct"
    return [
        Send(
            "branch",
            {
                "branch_id": f"b{index}",
                "question": question,
                "hyde_text": plan.hyde_text if len(plan.subquestions) == 1 else None,
                "attempts": 0,
            },
        )
        for index, question in enumerate(plan.subquestions, start=1)
    ]


async def retrieve_answer(state: BranchState) -> dict:
    started = perf_counter()
    attempt = state["attempts"] + 1
    event(
        "branch_answer",
        phase="start",
        attempt=attempt,
        query=state["question"],
        hyde_used=bool(state.get("hyde_text")) and attempt == 1,
    )
    sources = [
        Source.model_validate(source)
        for source in await call_tool(
            "search_documents",
            {
                "query": state["question"],
                "hyde_text": state.get("hyde_text") if attempt == 1 else None,
                "top_k": 3,
            },
        )
    ]
    if sources:
        draft = await generate(
            "answer",
            {
                "question": state["question"],
                "evidence": context(sources),
                "critic_feedback": state["critic"].reason if state.get("critic") else None,
            },
            Answer,
        )
    else:
        draft = Answer(
            answer="The available documents do not contain enough information to answer this question.",
            sufficient=False,
        )
    event(
        "branch_answer",
        phase="end",
        attempt=attempt,
        sufficient=draft.sufficient,
        duration_ms=round((perf_counter() - started) * 1000),
    )
    return {"sources": sources, "draft": draft, "attempts": attempt}


async def critic(state: BranchState) -> dict:
    started = perf_counter()
    verdict = await generate(
        "critic",
        {
            "question": state["question"],
            "answer": state["draft"].model_dump(),
            "evidence": context(state["sources"]),
        },
        Critique,
    )
    if not valid_citations(state["draft"], state["sources"]):
        verdict = Critique(
            passed=False,
            reason="Cite supported claims using only exact supplied source IDs.",
            retry_needed=True,
        )
    event(
        "critic",
        passed=verdict.passed,
        reason=verdict.reason[:300],
        retry_needed=verdict.retry_needed,
        retry_count=state["attempts"] - 1,
        duration_ms=round((perf_counter() - started) * 1000),
    )
    return {"critic": verdict}


def after_critic(state: BranchState) -> str:
    return (
        "retrieve_answer"
        if (not state["critic"].passed and state["critic"].retry_needed and state["attempts"] < 2)
        else "finish"
    )


def finish_branch(state: BranchState) -> dict:
    draft = state["draft"]
    if not state["critic"].passed:
        draft = Answer(
            answer="The retrieved documents did not provide a sufficiently supported answer to this part.",
            sufficient=False,
        )
    return {
        "branch_results": [
            BranchResult(
                question=state["question"],
                answer=draft.answer,
                sufficient=draft.sufficient,
                sources=state["sources"] if state["critic"].passed else [],
                critic=state["critic"],
                retries=state["attempts"] - 1,
            )
        ]
    }


async def direct(state: State) -> dict:
    started = perf_counter()
    intent = state["plan"].intent
    answer = await direct_answer(state["question"], intent)
    event("direct", intent=intent, duration_ms=round((perf_counter() - started) * 1000))
    return {"final_answer": answer, "sources": [], "synthesized": False}


async def synthesize(state: State) -> dict:
    started = perf_counter()
    fallback = False
    order = {question: index for index, question in enumerate(state["plan"].subquestions)}
    branches = sorted(state["branch_results"], key=lambda branch: order[branch.question])
    sources = list(
        {source.source_id: source for branch in branches for source in branch.sources}.values()
    )
    if len(branches) == 1:
        answer = branches[0].answer
    else:
        event("synthesis", phase="start", branches=len(branches))
        result = await generate(
            "synthesis",
            {
                "question": state["question"],
                "subquestions": state["plan"].subquestions,
                "branches": [
                    {"question": b.question, "answer": b.answer, "sufficient": b.sufficient}
                    for b in branches
                ],
                "evidence": context(sources),
            },
            Answer,
        )
        if valid_citations(result, sources) and all(branch.sufficient for branch in branches):
            answer = result.answer
        else:
            fallback = True
            answer = "\n\n".join(f"{branch.question}\n{branch.answer}" for branch in branches)
    cited = citation_ids(answer)
    event(
        "synthesis",
        phase="end",
        branches=len(branches),
        generated=len(branches) > 1,
        fallback=fallback,
        source_ids=sorted(cited),
        duration_ms=round((perf_counter() - started) * 1000),
    )
    return {
        "final_answer": answer,
        "sources": [s for s in sources if s.source_id in cited],
        "synthesized": len(branches) > 1,
    }


branch = StateGraph(BranchState)
branch.add_node("retrieve_answer", retrieve_answer)
branch.add_node("critic", critic)
branch.add_node("finish", finish_branch)
branch.add_edge(START, "retrieve_answer")
branch.add_edge("retrieve_answer", "critic")
branch.add_conditional_edges("critic", after_critic, ["retrieve_answer", "finish"])
branch.add_edge("finish", END)
branch_graph = branch.compile()


async def run_branch(state: BranchState) -> dict:
    token = branch_id.set(state["branch_id"])
    started = perf_counter()
    status = "error"
    event("branch", phase="start")
    try:
        result = await branch_graph.ainvoke(state)
        status = "success"
        return {"branch_results": result["branch_results"]}
    finally:
        event(
            "branch",
            phase="end",
            status=status,
            duration_ms=round((perf_counter() - started) * 1000),
        )
        branch_id.reset(token)


workflow = StateGraph(State)
workflow.add_node("planner", planner)
workflow.add_node("direct", direct)
workflow.add_node("branch", run_branch)
workflow.add_node("synthesize", synthesize)
workflow.add_edge(START, "planner")
workflow.add_conditional_edges("planner", route, ["direct", "branch"])
workflow.add_edge("branch", "synthesize")
workflow.add_edge("synthesize", END)
workflow.add_edge("direct", END)
graph = workflow.compile()
