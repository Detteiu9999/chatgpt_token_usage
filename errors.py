class ConnectionProblem(Exception):
    def __init__(self, message, needs_login=False):
        super().__init__(message)
        self.needs_login = needs_login
