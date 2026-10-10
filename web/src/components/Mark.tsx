/** The Hansard Guru mark: a speech bubble in Commons green holding a gilt quotation mark. */
export function Mark({ className = "mark" }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 40 40" aria-hidden="true" focusable="false">
      <path
        className="mark-bubble"
        d="M8 3h24a5 5 0 0 1 5 5v17a5 5 0 0 1-5 5H17l-8 7v-7H8a5 5 0 0 1-5-5V8a5 5 0 0 1 5-5Z"
      />
      <path
        className="mark-quote"
        d="M13.2 22.5c-1.9 0-3.2-1.4-3.2-3.4 0-3.3 2.2-6.2 5.6-7.6l.9 1.4c-2 1-3.1 2.4-3.3 4 1.6 0 2.9 1.2 2.9 2.8s-1.3 2.8-2.9 2.8Zm9.4 0c-1.9 0-3.2-1.4-3.2-3.4 0-3.3 2.2-6.2 5.6-7.6l.9 1.4c-2 1-3.1 2.4-3.3 4 1.6 0 2.9 1.2 2.9 2.8s-1.3 2.8-2.9 2.8Z"
      />
    </svg>
  );
}
