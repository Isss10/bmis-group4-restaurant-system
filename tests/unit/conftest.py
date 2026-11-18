import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.data.database import Base
from src.data.models.dish import Dish
from src.data.models.order import Order
from src.data.schema.membership import User


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    Base.metadata.create_all(engine)

    TestingSessionLocal = sessionmaker(bind=engine)
    session = TestingSessionLocal()

    table_waiter = User(
    id=7,
    email_normalized="waiter_07@test.com",
    display_name="Waiter 07",
    password_hash="dummy_hash",
    role="waiter"
)
    dish = Dish(id=12, name="Test Dish - Kung Pao Chicken", price=58.00)
    order = Order(id=23, customer_name="Test Customer", total_price=58.00, status="pending")

    session.add_all([table_waiter, dish, order])
    session.commit()

    yield session

    session.close()
    engine.dispose()
    Base.metadata.drop_all(engine)
