import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type DependencyList,
} from 'react';
export function useLoad<T>(
  fn: () => Promise<T>,
  deps: DependencyList,
): [T | null, () => void, string] {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState('');
  const request = useRef(0);
  const load = useCallback(() => {
    const current = ++request.current;
    setError('');
    fn()
      .then((value) => {
        if (request.current === current) setData(value);
      })
      .catch((e) => {
        if (request.current === current)
          setError(e instanceof Error ? e.message : 'Ошибка запроса');
      });
  }, deps);
  useEffect(() => {
    setData(null);
    load();
    return () => {
      request.current++;
    };
  }, [load]);
  return [data, load, error];
}
