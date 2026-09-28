from abc import ABC, abstractmethod

from app.ingestion.models.job_record import JobRecord


class BaseJobAdapter(ABC):
    """
    Base interface for all CareerOS job-source adapters.
    """

    source_name: str

    @abstractmethod
    def fetch(self) -> list[JobRecord]:
        """
        Fetch opportunities from the source and convert them
        into CareerOS JobRecord objects.
        """
        raise NotImplementedError