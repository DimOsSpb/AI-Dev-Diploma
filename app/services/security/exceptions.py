class SecurityException(Exception):
    """Базовое исключение для всех инцидентов безопасности сервиса."""

    def __init__(self, message: str, rule: str):
        super().__init__(message)
        self.rule = rule


class SecurityInputViolation(SecurityException):
    """Вызывается при обнаружении prompt-инъекции или аномалии кодирования на ВХОДЕ."""


class SecurityOutputViolation(SecurityException):
    """Вызывается при обнаружении утечки промпта/канарейки или токсичности на ВЫХОДЕ."""
