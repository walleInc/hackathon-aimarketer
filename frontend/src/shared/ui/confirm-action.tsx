import { useState, type ReactNode } from 'react';
import { Button } from './button';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from './dialog';
export function ConfirmAction({
  children,
  description,
  onConfirm,
  className,
  label,
}: {
  children: ReactNode;
  description: string;
  onConfirm: () => Promise<unknown>;
  className?: string;
  label?: string;
}) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const submit = async () => {
    setBusy(true);
    setError('');
    try {
      await onConfirm();
      setOpen(false);
    } catch (e) {
      setError(
        e instanceof Error ? e.message : 'Не удалось выполнить действие',
      );
    } finally {
      setBusy(false);
    }
  };
  return (
    <>
      <Button
        type="button"
        variant="ghost"
        className={className}
        aria-label={label}
        onClick={() => {
          setError('');
          setOpen(true);
        }}
      >
        {children}
      </Button>
      <Dialog
        open={open}
        onOpenChange={(value) => {
          if (!busy) setOpen(value);
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Подтвердите действие</DialogTitle>
            <DialogDescription>{description}</DialogDescription>
          </DialogHeader>
          {error && (
            <p role="alert" className="text-sm text-destructive">
              {error}
            </p>
          )}
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              disabled={busy}
              onClick={() => setOpen(false)}
            >
              Отмена
            </Button>
            <Button
              type="button"
              variant="destructive"
              disabled={busy}
              onClick={submit}
            >
              {busy ? 'Выполняется…' : 'Подтвердить'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
