class RepoPilotError(Exception):
    """An error whose message is safe to persist or present to the user."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
