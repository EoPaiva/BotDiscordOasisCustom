class ChoqueError(Exception):
    """Erro de dominio que pode ser apresentado ao usuario."""


class ValidationError(ChoqueError):
    pass


class PermissionDenied(ChoqueError):
    pass


class ConflictError(ChoqueError):
    pass


class NotFoundError(ChoqueError):
    pass
