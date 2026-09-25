import type { TopicImage } from "@/lib/domain";

type Props = {
  topicId: string;
  images: TopicImage[];
  addAction: (formData: FormData) => Promise<void>;
  deleteAction: (formData: FormData) => Promise<void>;
};

export function TopicImages({ topicId, images, addAction, deleteAction }: Props) {
  return (
    <div className="topic-images-body">
      {images.length ? (
        <ul className="topic-image-list">
          {images.map((image) => {
            const src = `/api/topics/${encodeURIComponent(topicId)}/images/${encodeURIComponent(image.id)}`;
            return (
              <li key={image.id}>
                <a href={src} target="_blank" rel="noreferrer">
                  {/* plain <img>: the source is an app route backed by a private bucket, not an optimizable remote URL */}
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img src={src} alt={image.filename} loading="lazy" />
                </a>
                <small title={image.filename}>{image.filename}</small>
                <form action={deleteAction}>
                  <input type="hidden" name="topicId" value={topicId} />
                  <input type="hidden" name="imageId" value={image.id} />
                  <button aria-label={`Remove image ${image.filename}`}>Remove</button>
                </form>
              </li>
            );
          })}
        </ul>
      ) : null}
      <form className="image-form" action={addAction}>
        <input type="hidden" name="topicId" value={topicId} />
        <input type="file" name="image" accept="image/png,image/jpeg,image/gif,image/webp" required />
        <button>Add image</button>
        <small>PNG, JPEG, GIF or WebP, up to 5 MB.</small>
      </form>
    </div>
  );
}
