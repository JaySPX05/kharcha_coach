"""A fake OpenAI-compatible client so llm/ and the app can be tested with no API key.

It looks at the request and returns what a well-behaved Nemotron would:
  - categorise prompt -> JSON mapping every merchant to a category
  - chat with tools   -> a tool call first, then an answer quoting the tool result
  - coach prompt      -> a valid report built from numbers in the insights
"""
from __future__ import annotations

import json
import re
from types import SimpleNamespace as NS


def _usage(p=100, c=50):
    return NS(prompt_tokens=p, completion_tokens=c)


def _reply(content=None, tool_calls=None):
    return NS(choices=[NS(message=NS(content=content, tool_calls=tool_calls))], usage=_usage())


class _Completions:
    def __init__(self, owner):
        self.owner = owner

    def create(self, model, messages, **kw):
        self.owner.requests.append({"model": model, "messages": messages, **kw})
        last = messages[-1]["content"] or ""
        first = messages[0]["content"] or ""

        if "Merchants:" in last:
            names = last.split("Merchants:", 1)[1].strip().splitlines()
            return _reply("<think>easy</think>" + json.dumps({n: self.owner.category_for(n) for n in names}))

        if "practical money coach" in first:
            ins = json.loads(first.split("Analysis:", 1)[1])
            cats = [c for c in ins["by_category"] if c["category"] != "Income"][:4]
            top = ins["top_merchants"][0]
            rep = {
                "summary": f"You spent Rs {ins['summary']['spend']:,.0f}. Income was Rs {ins['summary']['income']:,.0f}. "
                           f"{top['merchant']} was your top merchant.",
                "budgets": [{"category": c["category"], "budget": round(c["total"] * 0.9, -2)} for c in cats],
                "actions": [{"title": f"Cut {top['merchant']}", "detail": "Order less.", "rupee_impact": top["total"]},
                            {"title": "Small payments", "detail": "Carry a bottle.",
                             "rupee_impact": ins["small_ticket"]["total"]},
                            {"title": "Friends", "detail": "Split fairly.",
                             "rupee_impact": ins["transfers_to_people"]["total"]}],
                "watch_outs": [f"{r['counterparty']} Rs {r['amount']:,.0f}" for r in ins["recurring"][:2]] or ["None"],
            }
            if self.owner.coach_invent:
                rep["summary"] += " You could save Rs 98,765."
            return _reply(json.dumps(rep))

        if kw.get("tools"):
            tool_msgs = [m for m in messages if m.get("role") == "tool"]
            if not tool_msgs:
                q = next(m["content"] for m in reversed(messages) if m["role"] == "user").lower()
                merchant = "swiggy" if "swiggy" in q else None
                args = {"merchant": merchant, "month": "2026-09"} if merchant else {"month": "2026-09"}
                name = "spend_by" if merchant else "month_overview"
                return _reply(None, [NS(id="call_1", function=NS(name=name, arguments=json.dumps(args)))])
            res = json.loads(tool_msgs[-1]["content"])["result"]
            total = res.get("total") if "total" in res else res["summary"]["spend"]
            extra = " That's about Rs 12,345 extra." if self.owner.chat_invent else ""
            return _reply(f"You spent Rs {total:,.0f}.{extra}")

        return _reply("ok")


class FakeClient:
    def __init__(self, chat_invent=False, coach_invent=False, category_for=None):
        self.requests: list[dict] = []
        self.chat = NS(completions=_Completions(self))
        self.models = NS(list=lambda: [NS(id="nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B")])
        self.chat_invent = chat_invent
        self.coach_invent = coach_invent
        self.category_for = category_for or (lambda n: "Eating out" if re.search(r"tea|chai", n, re.I) else "Other")
