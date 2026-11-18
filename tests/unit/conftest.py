import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.data.database import Base
from src.data.schema.membership import User
from src.data.models.order import Order
from src.data.models.dish import Dish

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
    
    table_waiter = User(id=7, username="waiter_07", role="waiter")
    dish = Dish(id=12, name="Test Dish - Kung Pao Chicken", price=58.00)
    order = Order(id=23, customer_name="Test Customer", total_price=58.00, status="pending")
    
    session.add_all([table_waiter, dish, order])
    session.commit()
    
    yield session
    
    session.close()
    Base.metadata.drop_all(engine)
