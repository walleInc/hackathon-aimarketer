import {
  useForm,
  type DefaultValues,
  type FieldValues,
  type Resolver,
} from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
export function useEditorForm<T extends FieldValues>(
  schema: z.ZodType<T>,
  defaults: T,
) {
  const form = useForm<T>({
    resolver: zodResolver(schema) as Resolver<T>,
    defaultValues: defaults as DefaultValues<T>,
  });
  return {
    ...form,
    values: form.watch(),
    setValues: (values: T) => form.reset(values),
  };
}
