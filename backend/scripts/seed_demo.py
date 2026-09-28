from datetime import date, timedelta
from app.db.session import SessionLocal
from app.ingestion.models.job_record import JobRecord
from app.ingestion.services.publisher import publish_to_review


def main():
    db = SessionLocal()
    samples = [
        JobRecord(
            source_name="CareerOS Demo",
            source_reference="DEMO-SE-001",
            title="Software Engineer - Graduate",
            organization="Demo Technology Department",
            job_type="Government",
            govt_level="Central",
            location="India",
            vacancies=25,
            qualification="Graduate / B.Tech",
            deadline=date.today() + timedelta(days=30),
            description="Java Python SQL Git data structures backend software engineering",
        ),
        JobRecord(
            source_name="CareerOS Demo",
            source_reference="DEMO-DA-001",
            title="Data Analyst - Graduate",
            organization="Demo Analytics Board",
            job_type="Government",
            govt_level="Central",
            location="India",
            vacancies=10,
            qualification="Graduate / Bachelor",
            deadline=date.today() + timedelta(days=45),
            description="Python SQL pandas Excel Power BI data analysis",
        ),
    ]
    for rec in samples:
        created, j = publish_to_review(db, rec)
        if created:
            j.status = "published"
            j.verified = True
            db.commit()
    print("CareerOS demo data ready")
    db.close()


if __name__ == "__main__":
    main()
