"""Composition root: the one place that knows every layer. It builds the infrastructure adapters and hands
them to the use cases; presentation code receives the finished Container and never imports infrastructure."""
from __future__ import annotations

import threading
from dataclasses import dataclass

from app.application.interfaces.repositories import UnitOfWorkFactory
from app.application.interfaces.semantic_classifier import SemanticClassifier
from app.application.interfaces.services import (
    Clock,
    Embedder,
    ExtractSource,
    IdGenerator,
    ImageStore,
)
from app.application.services.priority_recalculation import PriorityRecalculator
from app.application.services.topic_ranker_cache import TopicRankerCache
from app.application.use_cases import (
    health,
    ingestion,
    items,
    priority,
    queries,
    review,
    topic_content,
    topics,
)


@dataclass(frozen=True)
class Container:
    # ports and shared application services
    uow: UnitOfWorkFactory
    embedder: Embedder
    images: ImageStore
    extract_source: ExtractSource
    clock: Clock
    ids: IdGenerator
    classifier: SemanticClassifier
    rankers: TopicRankerCache
    recalculator: PriorityRecalculator

    # meetings and whole-knowledge-base views
    list_meetings: queries.ListMeetings
    get_meeting: queries.GetMeeting
    get_most_recent_meeting: queries.GetMostRecentMeeting
    search: queries.SearchKnowledge
    build_graph: queries.BuildGraph
    get_follow_up: queries.GetFollowUp

    # items
    list_items: items.ListItems
    get_item_detail: items.GetItemDetail
    find_similar_items: items.FindSimilarItems
    create_item: items.CreateItem
    update_item: items.UpdateItem
    delete_item: items.DeleteItem
    set_item_status: items.SetItemStatus
    set_item_priority_override: items.SetItemPriorityOverride
    assign_item_topic: items.AssignItemTopic
    assign_items_topic: items.AssignItemsTopic
    add_item_tag: items.AddItemTag
    remove_item_tag: items.RemoveItemTag
    add_item_note: items.AddItemNote
    edit_item_note: items.EditItemNote
    delete_item_note: items.DeleteItemNote

    # topics
    list_topics: topics.ListTopics
    get_topic: topics.GetTopic
    create_topic: topics.CreateTopic
    rename_topic: topics.RenameTopic
    set_topic_status: topics.SetTopicStatus
    delete_topic: topics.DeleteTopic
    merge_topics: topics.MergeTopics
    get_related_topics: topics.GetRelatedTopics
    suggest_topic_merges: topics.SuggestTopicMerges
    suggest_item_topics: topics.SuggestItemTopics
    add_topic_tag: topic_content.AddTopicTag
    remove_topic_tag: topic_content.RemoveTopicTag
    add_topic_note: topic_content.AddTopicNote
    edit_topic_note: topic_content.EditTopicNote
    delete_topic_note: topic_content.DeleteTopicNote
    add_topic_image: topic_content.AddTopicImage
    delete_topic_image: topic_content.DeleteTopicImage
    get_topic_image: topic_content.GetTopicImage

    # priority
    recalculate_topic_priority: priority.RecalculateTopicPriority
    recalculate_all_priorities: priority.RecalculateAllPriorities
    set_topic_priority_override: priority.SetTopicPriorityOverride
    get_priority_history: priority.GetPriorityHistory
    get_recent_escalations: priority.GetRecentEscalations

    # human review
    list_pending_review: review.ListPendingReview
    decide_review_candidate: review.DecideReviewCandidate
    list_topic_proposals: review.ListTopicProposals
    accept_topic_proposal: review.AcceptTopicProposal
    reject_topic_proposal: review.RejectTopicProposal

    # ingestion
    ingest_extracts: ingestion.IngestExtracts

    # operations
    check_storage_health: health.CheckStorageHealth


def build_container(
    *,
    uow: UnitOfWorkFactory | None = None,
    embedder: Embedder | None = None,
    images: ImageStore | None = None,
    extract_source: ExtractSource | None = None,
    clock: Clock | None = None,
    ids: IdGenerator | None = None,
    classifier: SemanticClassifier | None = None,
    rankers: TopicRankerCache | None = None,
) -> Container:
    """Wires the production adapters; any port can be replaced (tests pass fakes)."""
    from app.infrastructure.external_services.embeddings import (
        SentenceTransformerEmbedder,
    )
    from app.infrastructure.external_services.s3_storage import (
        S3ExtractSource,
        S3ImageStore,
    )
    from app.infrastructure.external_services.semantic_classifiers import (
        EnvConfiguredSemanticClassifier,
    )
    from app.infrastructure.external_services.system import SystemClock, UuidGenerator
    from app.infrastructure.external_services.tfidf_description_index import (
        build_tfidf_description_index,
    )
    from app.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork

    uow = uow or SqlAlchemyUnitOfWork
    embedder = embedder or SentenceTransformerEmbedder()
    images = images or S3ImageStore()
    extract_source = extract_source or S3ExtractSource()
    clock = clock or SystemClock()
    ids = ids or UuidGenerator()
    classifier = classifier or EnvConfiguredSemanticClassifier()
    rankers = rankers or TopicRankerCache(build_tfidf_description_index)
    recalculator = PriorityRecalculator(uow=uow, classifier=classifier, clock=clock, ids=ids)

    return Container(
        uow=uow,
        embedder=embedder,
        images=images,
        extract_source=extract_source,
        clock=clock,
        ids=ids,
        classifier=classifier,
        rankers=rankers,
        recalculator=recalculator,
        list_meetings=queries.ListMeetings(uow),
        get_meeting=queries.GetMeeting(uow),
        get_most_recent_meeting=queries.GetMostRecentMeeting(uow),
        search=queries.SearchKnowledge(uow, embedder),
        build_graph=queries.BuildGraph(uow),
        get_follow_up=queries.GetFollowUp(uow, clock),
        list_items=items.ListItems(uow),
        get_item_detail=items.GetItemDetail(uow),
        find_similar_items=items.FindSimilarItems(uow),
        create_item=items.CreateItem(uow, embedder, clock, ids, recalculator),
        update_item=items.UpdateItem(uow, embedder, recalculator),
        delete_item=items.DeleteItem(uow, recalculator),
        set_item_status=items.SetItemStatus(uow),
        set_item_priority_override=items.SetItemPriorityOverride(uow, clock),
        assign_item_topic=items.AssignItemTopic(uow, recalculator),
        assign_items_topic=items.AssignItemsTopic(uow, recalculator),
        add_item_tag=items.AddItemTag(uow),
        remove_item_tag=items.RemoveItemTag(uow),
        add_item_note=items.AddItemNote(uow, clock, ids),
        edit_item_note=items.EditItemNote(uow),
        delete_item_note=items.DeleteItemNote(uow),
        list_topics=topics.ListTopics(uow),
        get_topic=topics.GetTopic(uow),
        create_topic=topics.CreateTopic(uow, ids),
        rename_topic=topics.RenameTopic(uow),
        set_topic_status=topics.SetTopicStatus(uow),
        delete_topic=topics.DeleteTopic(uow, images),
        merge_topics=topics.MergeTopics(uow, recalculator),
        get_related_topics=topics.GetRelatedTopics(uow),
        suggest_topic_merges=topics.SuggestTopicMerges(uow),
        suggest_item_topics=topics.SuggestItemTopics(uow, rankers),
        add_topic_tag=topic_content.AddTopicTag(uow),
        remove_topic_tag=topic_content.RemoveTopicTag(uow),
        add_topic_note=topic_content.AddTopicNote(uow, clock, ids),
        edit_topic_note=topic_content.EditTopicNote(uow),
        delete_topic_note=topic_content.DeleteTopicNote(uow),
        add_topic_image=topic_content.AddTopicImage(uow, images, clock, ids),
        delete_topic_image=topic_content.DeleteTopicImage(uow, images),
        get_topic_image=topic_content.GetTopicImage(uow, images),
        recalculate_topic_priority=priority.RecalculateTopicPriority(uow, recalculator),
        recalculate_all_priorities=priority.RecalculateAllPriorities(recalculator),
        set_topic_priority_override=priority.SetTopicPriorityOverride(uow, clock),
        get_priority_history=priority.GetPriorityHistory(uow),
        get_recent_escalations=priority.GetRecentEscalations(uow, clock),
        list_pending_review=review.ListPendingReview(uow, embedder, rankers),
        decide_review_candidate=review.DecideReviewCandidate(uow, embedder, ids, recalculator),
        list_topic_proposals=review.ListTopicProposals(uow, rankers),
        accept_topic_proposal=review.AcceptTopicProposal(uow, ids, recalculator),
        reject_topic_proposal=review.RejectTopicProposal(uow),
        ingest_extracts=ingestion.IngestExtracts(uow, extract_source, embedder, ids, recalculator),
        check_storage_health=health.CheckStorageHealth(uow),
    )


_container: Container | None = None
_container_lock = threading.Lock()


def get_container() -> Container:
    """The process-wide production container, built on first use."""
    global _container
    with _container_lock:
        if _container is None:
            _container = build_container()
        return _container


def reset_container() -> None:
    """Test helper: the next get_container() builds a fresh one (fresh ranker cache and ingestion lock)."""
    global _container
    with _container_lock:
        _container = None
