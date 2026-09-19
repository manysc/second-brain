import type { Note } from "@/lib/domain";

type Props = {
  notes: Note[];
  // the hidden field naming the parent ("itemId" or "topicId") and its value
  parentField: "itemId" | "topicId";
  parentId: string;
  addAction: (formData: FormData) => Promise<void>;
  editAction: (formData: FormData) => Promise<void>;
  deleteAction: (formData: FormData) => Promise<void>;
};

function formatNoteDate(iso: string): string {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? iso : date.toISOString().slice(0, 10);
}

export function NotesSection({ notes, parentField, parentId, addAction, editAction, deleteAction }: Props) {
  return (
    <div className="notes-body">
      {notes.length ? (
        <ul className="note-list">
          {notes.map((note) => (
            <li key={note.id}>
              <p>{note.body}</p>
              <small>{formatNoteDate(note.createdAt)}</small>
              <details className="note-edit">
                <summary>Edit</summary>
                <form className="note-form" action={editAction}>
                  <input type="hidden" name={parentField} value={parentId} />
                  <input type="hidden" name="noteId" value={note.id} />
                  <textarea name="body" rows={2} defaultValue={note.body} required maxLength={10000} />
                  <button>Save</button>
                </form>
              </details>
              <form action={deleteAction}>
                <input type="hidden" name={parentField} value={parentId} />
                <input type="hidden" name="noteId" value={note.id} />
                <button aria-label="Delete note">Delete</button>
              </form>
            </li>
          ))}
        </ul>
      ) : null}
      <form className="note-form" action={addAction}>
        <input type="hidden" name={parentField} value={parentId} />
        <textarea name="body" rows={2} placeholder="Add a note…" required maxLength={10000} />
        <button>Add note</button>
      </form>
    </div>
  );
}
