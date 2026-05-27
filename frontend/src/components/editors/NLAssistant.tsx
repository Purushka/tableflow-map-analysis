import { useState } from 'react';
import { parseNL } from '../../api/client';
import { useSettingsStore } from '../../store/settingsStore';
import { useT } from '../../i18n/useI18n';
import { Sparkles, Loader2 } from 'lucide-react';

interface NLAssistantProps {
  nodeType: string;
  fieldName: string;
  columns: string[];
  onResult: (result: any) => void;
}

export default function NLAssistant({ nodeType, fieldName, columns, onResult }: NLAssistantProps) {
  const t = useT();
  const { defaultModel, getApiKeyForModel } = useSettingsStore();
  const [text, setText] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const nlKey = `nl.${fieldName}` as string;
  const placeholder = t(nlKey, t('cfg.nlPlaceholder'));

  const handleParse = async () => {
    if (!text.trim()) return;
    setLoading(true);
    setError('');
    try {
      const apiKey = defaultModel ? getApiKeyForModel(defaultModel) : '';
      const res = await parseNL(text, nodeType, fieldName, columns, apiKey, defaultModel);
      if (res.error) {
        setError(res.error);
      } else {
        onResult(res.result);
        setText('');
      }
    } catch (e: any) {
      setError(e.message || 'Parse failed');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="mt-2 p-2 bg-[#0f172a] rounded-md border border-[#334155] space-y-2">
      <div className="flex items-center gap-1.5 text-xs text-purple-400 font-medium">
        <Sparkles size={12} />
        {t('cfg.nlToggle')}
      </div>
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder={placeholder}
        rows={2}
        className="w-full px-2 py-1.5 text-xs bg-[#1e293b] border border-[#334155] rounded
                   text-[#e2e8f0] placeholder-[#475569] focus:border-purple-500 focus:outline-none resize-none"
      />
      <div className="flex items-center gap-2">
        <button
          onClick={handleParse}
          disabled={loading || !text.trim()}
          className="flex items-center gap-1 px-2.5 py-1 text-xs rounded bg-purple-600 text-white
                     hover:bg-purple-700 disabled:opacity-50 transition-colors"
        >
          {loading ? <Loader2 size={11} className="animate-spin" /> : <Sparkles size={11} />}
          {loading ? t('cfg.nlParsing') : t('cfg.nlParse')}
        </button>
        {error && <span className="text-xs text-red-400 truncate">{error}</span>}
      </div>
    </div>
  );
}
