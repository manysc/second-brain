"""What people attach to a topic: tags, notes and images."""
from __future__ import annotations

from dataclasses import dataclass

from app.application.dtos import TopicDTO, TopicImageContentDTO
from app.application.interfaces.repositories import UnitOfWork, UnitOfWorkFactory
from app.application.interfaces.services import Clock, IdGenerator, ImageStore
from app.application.services import assembler
from app.application.use_cases.topics import delete_stored_images
from app.domain.entities.note import Note
from app.domain.entities.topic import Topic
from app.domain.entities.topic_image import TopicImage
from app.domain.exceptions import TopicNotFound
from app.domain.value_objects.image_upload import ImageUpload


def _get(uow: UnitOfWork, topic_id: str) -> Topic:
    topic = uow.topics.get(topic_id)
    if topic is None:
        raise TopicNotFound(topic_id)
    return topic


@dataclass(frozen=True)
class AddTopicTag:
    uow: UnitOfWorkFactory

    def __call__(self, topic_id: str, tag: str) -> TopicDTO:
        with self.uow() as uow:
            topic = _get(uow, topic_id)
            topic.add_tag(tag)
            uow.topics.save(topic)
            uow.commit()
            return assembler.load_topic_dto(uow, topic)


@dataclass(frozen=True)
class RemoveTopicTag:
    uow: UnitOfWorkFactory

    def __call__(self, topic_id: str, tag: str) -> TopicDTO:
        with self.uow() as uow:
            topic = _get(uow, topic_id)
            topic.remove_tag(tag)
            uow.topics.save(topic)
            uow.commit()
            return assembler.load_topic_dto(uow, topic)


@dataclass(frozen=True)
class AddTopicNote:
    uow: UnitOfWorkFactory
    clock: Clock
    ids: IdGenerator

    def __call__(self, topic_id: str, body: str) -> TopicDTO:
        with self.uow() as uow:
            topic = _get(uow, topic_id)
            topic.add_note(Note(id=self.ids.new_short_id(), body=body, created_at=self.clock.now().isoformat()))
            uow.topics.save(topic)
            uow.commit()
            return assembler.load_topic_dto(uow, topic)


@dataclass(frozen=True)
class EditTopicNote:
    uow: UnitOfWorkFactory

    def __call__(self, topic_id: str, note_id: str, body: str) -> TopicDTO:
        with self.uow() as uow:
            topic = _get(uow, topic_id)
            topic.edit_note(note_id, body)
            uow.topics.save(topic)
            uow.commit()
            return assembler.load_topic_dto(uow, topic)


@dataclass(frozen=True)
class DeleteTopicNote:
    uow: UnitOfWorkFactory

    def __call__(self, topic_id: str, note_id: str) -> TopicDTO:
        with self.uow() as uow:
            topic = _get(uow, topic_id)
            topic.remove_note(note_id)
            uow.topics.save(topic)
            uow.commit()
            return assembler.load_topic_dto(uow, topic)


@dataclass(frozen=True)
class AddTopicImage:
    """Stores the image and records it on the topic. The bytes are validated before the topic is even looked
    up; if recording fails, the stored object is removed again."""

    uow: UnitOfWorkFactory
    images: ImageStore
    clock: Clock
    ids: IdGenerator

    def __call__(self, topic_id: str, filename: str | None, body: bytes) -> TopicDTO:
        upload = ImageUpload.validate(filename, body)
        with self.uow() as uow:
            topic = _get(uow, topic_id)
            image_id = self.ids.new_short_id()
            key = self.images.store(topic_id, image_id, upload)
            try:
                topic.attach_image(
                    TopicImage(
                        id=image_id,
                        key=key,
                        filename=upload.filename,
                        content_type=upload.content_type,
                        size=upload.size,
                        created_at=self.clock.now().isoformat(),
                    )
                )
                uow.topics.save(topic)
                uow.commit()
            except Exception:
                uow.rollback()
                delete_stored_images(self.images, [key])
                raise
            return assembler.load_topic_dto(uow, topic)


@dataclass(frozen=True)
class DeleteTopicImage:
    """Removes the image record and its stored bytes. A missing image is a no-op."""

    uow: UnitOfWorkFactory
    images: ImageStore

    def __call__(self, topic_id: str, image_id: str) -> TopicDTO:
        with self.uow() as uow:
            topic = _get(uow, topic_id)
            removed = topic.detach_image(image_id)
            uow.topics.save(topic)
            uow.commit()
            result = assembler.load_topic_dto(uow, topic)
        delete_stored_images(self.images, [removed.key] if removed is not None else [])
        return result


@dataclass(frozen=True)
class GetTopicImage:
    uow: UnitOfWorkFactory
    images: ImageStore

    def __call__(self, topic_id: str, image_id: str) -> TopicImageContentDTO | None:
        """The bytes and content type of a topic's image, or None if the topic has no such image."""
        with self.uow() as uow:
            topic = uow.topics.get(topic_id)
            image = topic.find_image(image_id) if topic is not None else None
            if image is None:
                return None
            key, content_type = image.key, image.content_type
        return TopicImageContentDTO(body=self.images.load(key), content_type=content_type)
