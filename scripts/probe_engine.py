"""Offline upstream interface experiment; never invokes a shell or model service.

Install mini-swe-agent==2.4.6 in a separate experiment environment first.
This uses synthetic actions and is not a target-code reproduction result.
"""

import json
from pathlib import Path

from minisweagent.agents.default import DefaultAgent
from minisweagent.exceptions import Submitted


class ProbeModel:
    def query(self, messages):
        return {
            "role": "assistant",
            "content": "synthetic completion",
            "extra": {"actions": [{"command": "synthetic-submit"}], "cost": 0.0},
        }

    def format_message(self, **kwargs):
        return kwargs

    def format_observation_messages(self, message, outputs, template_vars):
        return [{"role": "user", "content": "synthetic observation"}]

    def get_template_vars(self):
        return {}

    def serialize(self):
        return {}


class ProbeEnvironment:
    def __init__(self, submit=True):
        self.submit = submit
        self.actions = 0

    def execute(self, action):
        self.actions += 1
        if self.submit:
            raise Submitted(
                {
                    "role": "exit",
                    "content": "synthetic submission",
                    "extra": {"exit_status": "Submitted", "submission": "synthetic submission"},
                }
            )
        return {"output": "synthetic", "returncode": 0}

    def get_template_vars(self):
        return {}

    def serialize(self):
        return {}


def main():
    output = Path(".repopilot/experiments/engine-contract")
    output.mkdir(parents=True, exist_ok=True)
    results = []
    for submit in (True, False):
        env = ProbeEnvironment(submit)
        agent = DefaultAgent(
            ProbeModel(),
            env,
            system_template="offline interface probe",
            instance_template="{{task}}",
            step_limit=1,
            cost_limit=1,
            output_path=output / ("submitted.json" if submit else "limited.json"),
        )
        result = agent.run("synthetic action only")
        expected = "Submitted" if submit else "LimitsExceeded"
        assert result["exit_status"] == expected
        assert env.actions == 1 and agent.n_calls == 1
        results.append(
            {"exit_status": expected, "model_calls": agent.n_calls, "synthetic_actions": 1}
        )
    summary = {
        "engine": "mini-swe-agent==2.4.6",
        "external_model_calls": 0,
        "shell_commands": 0,
        "target_code_executed": False,
        "cases": results,
    }
    (output / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=True))


if __name__ == "__main__":
    main()
