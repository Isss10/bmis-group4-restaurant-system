from src.data.schema.review import DishRatingStats, Review, ReviewModeration


def test_review_tables_exist():
    assert Review.__tablename__ == "reviews"
    assert ReviewModeration.__tablename__ == "review_moderation"
    assert DishRatingStats.__tablename__ == "dish_rating_stats"
