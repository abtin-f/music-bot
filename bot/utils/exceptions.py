"""Exception types shared across the application."""


class UserFacingError(Exception):
    """An error whose message is safe to show to the end user."""

    def __init__(self, user_message: str) -> None:
        super().__init__(user_message)
        self.user_message = user_message
