/** The Hansard Guru seal: a monogram in gilt on Commons-green cloth, as on a volume's spine label. */
export function Mark({ className = "mark" }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 48 48" aria-hidden="true" focusable="false">
      <rect className="mark-cloth" width="48" height="48" rx="2" />
      <rect className="mark-rule" x="3.5" y="3.5" width="41" height="41" rx="1" />
      <rect className="mark-rule thin" x="6" y="6" width="36" height="36" />
      <text className="mark-letters" x="24" y="30.5" textAnchor="middle">
        HG
      </text>
    </svg>
  );
}
