import { useState } from 'react';
import { usePipelineStore } from '../store/pipelineStore';
import { useT } from '../i18n/useI18n';
import type { Locale } from '../i18n/locales';
import { useSSE } from '../hooks/useSSE';
import { Play, Save, Settings, Loader2, FolderOpen, Globe } from 'lucide-react';
import SettingsModal from './SettingsModal';

interface ToolbarProps {
  onLoadTemplate: () => void;
}

export default function Toolbar({ onLoadTemplate }: ToolbarProps) {
  const t = useT();
  const { pipelineName, nodes, isRunning, locale, setLocale } = usePipelineStore();
  const [showSettings, setShowSettings] = useState(false);
  const { handleSave, handleRun } = useSSE();

  const toggleLocale = () => {
    setLocale(locale === 'en' ? 'zh-CN' as Locale : 'en' as Locale);
  };

  return (
    <>
      <div className="h-12 bg-[#1e293b] border-b border-[#334155] flex items-center justify-between px-4 shrink-0">
        <div className="flex items-center gap-3">
          <span className="text-sm font-bold text-white tracking-tight">{t('app.title')}</span>
          <span className="text-[#475569]">|</span>
          <span className="text-sm text-[#94a3b8]">{pipelineName}</span>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={toggleLocale}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs bg-[#0f172a] border border-[#334155]
                       rounded-md text-[#94a3b8] hover:bg-[#334155] transition-colors"
            title={locale === 'en' ? 'Switch to Chinese' : '切换到英文'}
          >
            <Globe size={12} />
            {locale === 'en' ? t('locale.zh') : t('locale.en')}
          </button>
          <button
            onClick={onLoadTemplate}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs bg-[#0f172a] border border-[#334155]
                       rounded-md text-[#94a3b8] hover:bg-[#334155] transition-colors"
          >
            <FolderOpen size={12} />
            {t('toolbar.loadTemplate')}
          </button>
          <button
            onClick={handleSave}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs bg-[#0f172a] border border-[#334155]
                       rounded-md text-[#94a3b8] hover:bg-[#334155] transition-colors"
          >
            <Save size={12} />
            {t('toolbar.save')}
          </button>
          <button
            onClick={() => setShowSettings(true)}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs bg-[#0f172a] border border-[#334155]
                       rounded-md text-[#94a3b8] hover:bg-[#334155] transition-colors"
          >
            <Settings size={12} />
          </button>
          <button
            onClick={handleRun}
            disabled={isRunning || nodes.length === 0}
            className="flex items-center gap-1.5 px-4 py-1.5 text-xs font-medium rounded-md
                       text-white transition-colors disabled:opacity-50
                       bg-emerald-600 hover:bg-emerald-700"
          >
            {isRunning ? <Loader2 size={12} className="animate-spin" /> : <Play size={12} />}
            {isRunning ? t('toolbar.running') : t('toolbar.run')}
          </button>
        </div>
      </div>

      {showSettings && <SettingsModal onClose={() => setShowSettings(false)} />}
    </>
  );
}
