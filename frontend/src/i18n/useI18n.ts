import { usePipelineStore } from '../store/pipelineStore';
import { locales, type Locale } from './locales';

export function useT() {
  const locale = usePipelineStore((s) => s.locale);
  return (key: string, fallback?: string): string =>
    locales[locale]?.[key] ?? locales['en']?.[key] ?? fallback ?? key;
}

export function t(locale: Locale, key: string, fallback?: string): string {
  return locales[locale]?.[key] ?? locales['en']?.[key] ?? fallback ?? key;
}
