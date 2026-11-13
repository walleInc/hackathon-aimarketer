import type { FieldErrors } from 'react-hook-form';
export function FormErrors({ errors }: { errors: FieldErrors }) {
  const messages = Object.values(errors)
    .map((e) => e?.message)
    .filter((m): m is string => typeof m === 'string');
  return messages.length ? (
    <div
      role="alert"
      aria-live="polite"
      className="mb-3 rounded-md border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive"
    >
      {messages.map((m, i) => (
        <p key={i}>{m}</p>
      ))}
    </div>
  ) : null;
}
