import { useSettingsStore } from '../../store/settingsStore';
import { useT } from '../../i18n/useI18n';

interface Props {
  value: string;
  onChange: (model: string) => void;
}

export default function ModelSelector({ value, onChange }: Props) {
  const t = useT();
  const { providers, getApiKey } = useSettingsStore();

  return (
    <select
      value={value || ''}
      onChange={(e) => onChange(e.target.value)}
      className="w-full px-3 py-2 text-sm bg-[#0f172a] border border-[#334155] rounded-md
                 text-[#e2e8f0] focus:border-blue-500 focus:outline-none"
    >
      <option value="">{t('settings.selectModel')}</option>
      {providers.map((p) => {
        const hasKey = !!getApiKey(p.id) || p.id === 'ollama';
        return (
          <optgroup key={p.id} label={`${p.label}${hasKey ? '' : ' (' + t('settings.notConfigured') + ')'}`}>
            {p.models.map((m) => (
              <option key={m.id} value={m.id} disabled={!hasKey}>
                {m.label}
              </option>
            ))}
          </optgroup>
        );
      })}
    </select>
  );
}
