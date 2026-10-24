class ReviewDomainError(Exception):
    """Base exception for review module."""

    pass


class OrderVerificationError(ReviewDomainError):
    """Order verification failed."""

    pass


class DishNotInOrderError(ReviewDomainError):
    """Dish not in the order."""

    pass


class ReviewAlreadyExistsError(ReviewDomainError):
    """Dish already reviewed for this order."""

    pass
