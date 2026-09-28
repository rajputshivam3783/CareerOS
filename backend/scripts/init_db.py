from app.db.base import Base
from app.db.session import engine
import app.models.domain  # noqa: F401  (registers every model on Base.metadata before create_all)
Base.metadata.create_all(bind=engine)
print('CareerOS database initialized.')
