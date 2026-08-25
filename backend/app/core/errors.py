class OuturnError(Exception):
    code = "OUTURN_ERROR"
    status_code = 400

    def __init__(self, message: str, *, code: str | None = None, status_code: int | None = None):
        super().__init__(message)
        self.safe_message = message
        if code:
            self.code = code
        if status_code:
            self.status_code = status_code


class InvalidUploadError(OuturnError):
    code = "INVALID_UPLOAD"
    status_code = 422


class ExtractionUnavailableError(OuturnError):
    code = "EXTRACTION_UNAVAILABLE"
    status_code = 503


class ProviderError(OuturnError):
    code = "PROVIDER_ERROR"
    status_code = 502


class NotFoundError(OuturnError):
    code = "NOT_FOUND"
    status_code = 404
