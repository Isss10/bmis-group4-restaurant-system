from src.data.schema.review import DishRatingStats, Review, ReviewModeration


def test_review_tables_exist() -> None:
    assert Review.__tablename__ == "reviews"
    assert ReviewModeration.__tablename__ == "review_moderation"
    assert DishRatingStats.__tablename__ == "dish_rating_stats"


def test_review_columns() -> None:
    assert hasattr(Review, "customer_id")
    assert hasattr(Review, "dish_id")
    assert hasattr(Review, "rating")
