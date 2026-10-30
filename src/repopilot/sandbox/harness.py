"""Stdlib-only frozen-suite adapter, executed inside the restricted container."""

import contextlib
import json
import sys
import unittest


class ObservationResult(unittest.TestResult):
    def __init__(self):
        super().__init__()
        self.observations = []

    def record(self, test, status):
        self.observations.append({"test_id": test.id(), "status": status})

    def addSuccess(self, test):
        super().addSuccess(test)
        self.record(test, "passed")

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self.record(test, "failed")

    def addError(self, test, err):
        super().addError(test, err)
        self.record(test, "error")

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self.record(test, "skipped")

    def addExpectedFailure(self, test, err):
        super().addExpectedFailure(test, err)
        self.record(test, "xfailed")

    def addUnexpectedSuccess(self, test):
        super().addUnexpectedSuccess(test)
        self.record(test, "unexpected_success")

    def addSubTest(self, test, subtest, err):
        # Subtest aggregation is intentionally unsupported in this first protocol.
        super().addSubTest(test, subtest, err)
        self.record(subtest, "error")


def main():
    sys.path[:0] = ["/suite", "/workspace/src", "/workspace"]
    with contextlib.redirect_stdout(sys.stderr):
        suite = unittest.defaultTestLoader.discover("/suite", pattern="test_*.py")
        result = ObservationResult()
        suite.run(result)
        for _test, trace in result.failures + result.errors:
            print(trace, file=sys.stderr)
    print(
        json.dumps(
            {
                "protocol": "repopilot-unittest-v1",
                "tests_run": result.testsRun,
                "tests": result.observations,
            }
        )
    )
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
