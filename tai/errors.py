"""Exceptions raised by tai.services (design 9.3).

The UI catches TaiError in one place. Each subclass carries the HTTP status
it would map to if the services were ever exposed as a REST API.
"""


class TaiError(Exception):
    http_status: int = 500

    def __init__(self, detail: str):
        super().__init__(detail)
        self.detail = detail

    def to_dict(self) -> dict:
        return {
            "error": type(self).__name__,
            "detail": self.detail,
            "http_status": self.http_status,
        }


class DataNotAvailableError(TaiError):
    """A file in data/processed/ is missing or fails validation."""

    http_status = 503


class TargetNotFoundError(TaiError):
    """target_id is not in targets.json."""

    http_status = 404


class CellNotFoundError(TaiError):
    """cell_id is not in the grid."""

    http_status = 404


class InvalidWeightsError(TaiError):
    """A dimension is missing, or a weight is outside 0..1 or not finite."""

    http_status = 422


class ZeroWeightsError(TaiError):
    """All weights are 0."""

    http_status = 422
