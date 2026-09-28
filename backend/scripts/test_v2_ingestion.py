from app.db.session import SessionLocal
from app.ingestion.adapters.demo import DemoAdapter
from app.ingestion.ingest import run_ingestion


def main():
    db = SessionLocal()

    try:
        result = run_ingestion(
            db=db,
            adapter=DemoAdapter(),
        )

        print(result)

    finally:
        db.close()


if __name__ == "__main__":
    main()