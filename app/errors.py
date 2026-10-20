"""Erreurs métier renvoyées au navigateur sans détail interne."""


class AppError(Exception):
    def __init__(self, status, code, message, fields=None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.fields = fields or {}

    def payload(self):
        return {"error": {"code": self.code, "message": self.message, "fields": self.fields}}
