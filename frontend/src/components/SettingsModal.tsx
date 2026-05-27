import { useState } from 'react';
import { useSettingsStore } from '../store/settingsStore';
import { useT } from '../i18n/useI18n';
import { X, Check, AlertCircle, Eye, EyeOff } from 'lucide-react';

interface Props {
  onClose: () => void;
}

export default function SettingsModal({ onClose }: Props) {
  const t = useT();
  const { providers, getApiKey, setApiKey, defaultModel, setDefaultModel } = useSettingsStore();
  const [activeTab, setActiveTab] = useState(providers[0]?.id || 'anthropic');
  const [showKeys, setShowKeys] = useState<Record<string, boolean>>({});
  const [tempKeys, setTempKeys] = useState<Record<string, string>>(() => {
    const keys: Record<string, string> = {};
    for (const p of providers) {
      keys[p.id] = getApiKey(p.id);
    }
    return keys;
  });

  const handleSave = () => {
    for (const p of providers) {
      const val = tempKeys[p.id] || '';
      if (val) {
        setApiKey(p.id, val);
      } else {
        // Clear key if emptied
        setApiKey(p.id, '');
      }
    }
    onClose();
  };

  return (
    <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center">
      <div className="bg-[#1e293b] rounded-lg border border-[#334155] w-[520px] max-h-[80vh] flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-[#334155]">
          <h3 className="text-sm font-semibold text-white">{t('settings.title')}</h3>
          <button onClick={onClose} className="p-1 hover:bg-[#334155] rounded">
            <X size={14} className="text-[#94a3b8]" />
          </button>
        </div>

        {/* Provider Tabs */}
        <div className="flex border-b border-[#334155]">
          {providers.map((p) => {
            const hasKey = !!(tempKeys[p.id]);
            return (
              <button
                key={p.id}
                onClick={() => setActiveTab(p.id)}
                className={`flex items-center gap-1.5 px-4 py-2.5 text-xs transition-colors ${
                  activeTab === p.id
                    ? 'text-white border-b-2 border-blue-500 bg-[#0f172a]/50'
                    : 'text-[#94a3b8] hover:text-white hover:bg-[#0f172a]/30'
                }`}
              >
                {p.label}
                {hasKey && <Check size={10} className="text-emerald-400" />}
              </button>
            );
          })}
        </div>

        {/* Active Provider Config */}
        <div className="flex-1 overflow-y-auto p-4 space-y-4">
          {providers.map((p) => {
            if (p.id !== activeTab) return null;
            const isOllama = p.id === 'ollama';
            return (
              <div key={p.id} className="space-y-3">
                <div>
                  <label className="block text-xs text-[#94a3b8] mb-1.5">
                    {isOllama ? t('settings.ollamaUrl') : t('settings.apiKey')}
                  </label>
                  <div className="flex gap-2">
                    <div className="flex-1 relative">
                      <input
                        type={showKeys[p.id] ? 'text' : 'password'}
                        value={tempKeys[p.id] || ''}
                        onChange={(e) => setTempKeys({ ...tempKeys, [p.id]: e.target.value })}
                        placeholder={p.api_key_placeholder || t('settings.apiKeyPlaceholder')}
                        className="w-full px-3 py-2 pr-8 text-sm bg-[#0f172a] border border-[#334155] rounded-md
                                   text-[#e2e8f0] placeholder-[#475569] focus:border-blue-500 focus:outline-none"
                      />
                      <button
                        onClick={() => setShowKeys({ ...showKeys, [p.id]: !showKeys[p.id] })}
                        className="absolute right-2 top-1/2 -translate-y-1/2 text-[#475569] hover:text-[#94a3b8]"
                      >
                        {showKeys[p.id] ? <EyeOff size={14} /> : <Eye size={14} />}
                      </button>
                    </div>
                  </div>
                  <div className="flex items-center gap-1.5 mt-1.5">
                    {tempKeys[p.id] ? (
                      <>
                        <Check size={10} className="text-emerald-400" />
                        <span className="text-xs text-emerald-400">{t('settings.configured')}</span>
                      </>
                    ) : (
                      <>
                        <AlertCircle size={10} className="text-[#475569]" />
                        <span className="text-xs text-[#475569]">{t('settings.notConfigured')}</span>
                      </>
                    )}
                  </div>
                </div>

                {/* Models for this provider */}
                <div>
                  <label className="block text-xs text-[#94a3b8] mb-1.5">{t('settings.availableModels')}</label>
                  <div className="space-y-1">
                    {p.models.map((m) => (
                      <div key={m.id} className="flex items-center justify-between px-2 py-1.5 bg-[#0f172a] rounded text-xs">
                        <span className="text-[#e2e8f0]">{m.label}</span>
                        <span className="text-[#475569]">{m.id}</span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            );
          })}
        </div>

        {/* Default Model */}
        <div className="px-4 py-3 border-t border-[#334155]">
          <label className="block text-xs text-[#94a3b8] mb-1.5">{t('settings.defaultModel')}</label>
          <select
            value={defaultModel}
            onChange={(e) => setDefaultModel(e.target.value)}
            className="w-full px-3 py-2 text-sm bg-[#0f172a] border border-[#334155] rounded-md
                       text-[#e2e8f0] focus:border-blue-500 focus:outline-none"
          >
            <option value="">{t('cfg.select')}</option>
            {providers.map((p) => (
              <optgroup key={p.id} label={p.label}>
                {p.models.map((m) => (
                  <option key={m.id} value={m.id}>{m.label}</option>
                ))}
              </optgroup>
            ))}
          </select>
        </div>

        {/* Footer */}
        <div className="flex gap-2 justify-end px-4 py-3 border-t border-[#334155]">
          <button
            onClick={onClose}
            className="px-3 py-1.5 text-xs bg-[#334155] rounded-md text-[#94a3b8] hover:bg-[#475569]"
          >
            {t('toolbar.cancel')}
          </button>
          <button
            onClick={handleSave}
            className="px-3 py-1.5 text-xs bg-blue-600 rounded-md text-white hover:bg-blue-700"
          >
            {t('toolbar.saveBtn')}
          </button>
        </div>
      </div>
    </div>
  );
}
