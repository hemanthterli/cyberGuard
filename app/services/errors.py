class ServiceError(Exception):
    def __init__(self, message: str, *, code: str = "service_error", status_code: int = 500) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code
