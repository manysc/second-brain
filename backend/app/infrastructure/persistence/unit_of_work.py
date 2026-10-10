from __future__ import annotations

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain.exceptions import TopicNameConflict
from app.infrastructure.persistence import database
from app.infrastructure.persistence.repositories import (
    SqlAlchemyKnowledgeItemRepository,
    SqlAlchemyMeetingRepository,
    SqlAlchemyPriorityHistoryRepository,
    SqlAlchemyReviewCandidateRepository,
    SqlAlchemyTopicRepository,
    is_topic_name_conflict,
)


class SqlAlchemyUnitOfWork:
    """One SQLAlchemy session per business transaction. Leaving the block closes the session; anything not
    committed by then is discarded.

    Given an existing session it joins that session instead: the repositories are usable right away and the
    session's owner stays responsible for committing and closing it."""

    meetings: SqlAlchemyMeetingRepository
    items: SqlAlchemyKnowledgeItemRepository
    topics: SqlAlchemyTopicRepository
    review_candidates: SqlAlchemyReviewCandidateRepository
    priority_history: SqlAlchemyPriorityHistoryRepository

    def __init__(self, session: Session | None = None) -> None:
        self._owns_session = session is None
        self._session: Session | None = None
        if session is not None:
            self._bind(session)

    def _bind(self, session: Session) -> None:
        self._session = session
        self.meetings = SqlAlchemyMeetingRepository(session)
        self.items = SqlAlchemyKnowledgeItemRepository(session)
        self.topics = SqlAlchemyTopicRepository(session)
        self.review_candidates = SqlAlchemyReviewCandidateRepository(session)
        self.priority_history = SqlAlchemyPriorityHistoryRepository(session)

    def __enter__(self) -> SqlAlchemyUnitOfWork:
        if self._owns_session:
            self._bind(database.new_session())
        return self

    def __exit__(self, *exc_info: object) -> None:
        if self._owns_session and self._session is not None:
            self._session.close()
            self._session = None

    def commit(self) -> None:
        assert self._session is not None, "commit() outside the unit of work"
        try:
            self._session.commit()
        except IntegrityError as error:
            self._session.rollback()
            if is_topic_name_conflict(error):
                raise TopicNameConflict() from error
            raise

    def rollback(self) -> None:
        assert self._session is not None, "rollback() outside the unit of work"
        self._session.rollback()
