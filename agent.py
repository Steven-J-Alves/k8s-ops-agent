import json
import os
from langchain_anthropic import ChatAnthropic
from langchain.agents import create_react_agent, AgentExecutor
from langchain.prompts import PromptTemplate
from k8s_tools import get_pod_logs, describe_pod, list_events, get_node_status

_TOOLS = [get_pod_logs, describe_pod, list_events, get_node_status]

_PROMPT = PromptTemplate.from_template("""You are a senior Site Reliability Engineer (SRE) specialized in Kubernetes incident response.

Analyse the incident below. Use the available tools to gather evidence before concluding.
Investigate at minimum: pod description + logs (or events if no pod name is available).

TOOLS:
{tools}

Use this format strictly:

Thought: what I need to investigate next
Action: the tool to use, must be one of [{tool_names}]
Action Input: the input to the tool
Observation: the tool result
... (repeat until you have enough evidence)
Thought: I have enough information to diagnose this incident
Final Answer:

=== ANALYSIS ===
{{
  "probable_cause": "<one clear sentence from an SRE perspective>",
  "evidence": ["<specific signal from logs/events>", "..."],
  "affected_resources": ["<resource name>", "..."],
  "fix_command": "<kubectl command, or null if manual intervention required>"
}}

INCIDENT:
namespace: {namespace}
resource: {resource}
reason: {reason}
message: {message}

{agent_scratchpad}""")


def _parse_analysis(raw: str) -> dict:
    segment = raw
    if "=== ANALYSIS ===" in raw:
        segment = raw.split("=== ANALYSIS ===")[1].strip()

    # strip markdown code fences if present
    if segment.startswith("```"):
        segment = segment.split("```")[1]
        if segment.startswith("json"):
            segment = segment[4:]

    # extract the JSON object — ignore any trailing markdown text
    start = segment.find("{")
    end = segment.rfind("}") + 1
    if start != -1 and end > start:
        try:
            return json.loads(segment[start:end])
        except json.JSONDecodeError:
            pass

    return {
        "probable_cause": segment[:300],
        "evidence": [],
        "affected_resources": [],
        "fix_command": None,
    }


def analyze_incident(namespace: str, resource: str, reason: str, message: str) -> dict:
    model = ChatAnthropic(
        model=os.getenv("MODEL", "claude-haiku-4-5-20251001"),
        temperature=0,
    )

    agent = create_react_agent(model, _TOOLS, _PROMPT)
    executor = AgentExecutor(
        agent=agent,
        tools=_TOOLS,
        verbose=True,
        max_iterations=10,
        handle_parsing_errors=True,
    )

    result = executor.invoke({
        "namespace": namespace,
        "resource": resource,
        "reason": reason,
        "message": message,
    })

    return _parse_analysis(result["output"])
