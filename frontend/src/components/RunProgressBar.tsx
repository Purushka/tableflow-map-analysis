import { usePipelineStore } from '../store/pipelineStore';
import { useT } from '../i18n/useI18n';
import { Loader2, CheckCircle2, XCircle, Download, X } from 'lucide-react';

export default function RunProgressBar() {
  const t = useT();
  const runProgress = usePipelineStore((s) => s.runProgress);
  const outputFiles = usePipelineStore((s) => s.outputFiles);
  const setRunProgress = usePipelineStore((s) => s.setRunProgress);
  const setOutputFiles = usePipelineStore((s) => s.setOutputFiles);

  if (!runProgress) return null;

  const { totalNodes, completedNodes, currentNodeLabel, currentMessage, hasError } = runProgress;
  const pct = totalNodes > 0 ? (completedNodes / totalNodes) * 100 : 0;
  const isComplete = completedNodes >= totalNodes && totalNodes > 0;

  const handleDownload = (filename: string) => {
    window.open(`/api/files/${encodeURIComponent(filename)}/download`, '_blank');
  };

  const handleDismiss = () => {
    setRunProgress(null);
    setOutputFiles([]);
  };

  return (
    <div className="bg-[#0f172a] border-b border-[#334155] px-4 py-1.5">
      <div className="flex items-center justify-between text-xs mb-1">
        <div className="flex items-center gap-2 text-[#e2e8f0]">
          {isComplete ? (
            hasError ? (
              <>
                <XCircle size={12} className="text-red-400" />
                <span className="text-red-400">{t('run.failed')}</span>
              </>
            ) : (
              <>
                <CheckCircle2 size={12} className="text-emerald-400" />
                <span className="text-emerald-400">{t('run.complete')}</span>
              </>
            )
          ) : (
            <>
              <Loader2 size={12} className="animate-spin text-blue-400" />
              <span>
                {currentNodeLabel
                  ? `${t('run.running_node').replace('{node}', currentNodeLabel)}`
                  : t('toolbar.running')}
              </span>
              <span className="text-[#64748b]">({completedNodes}/{totalNodes})</span>
            </>
          )}
        </div>
        <div className="flex items-center gap-2">
          {currentMessage && !isComplete && (
            <span className="text-[#94a3b8] truncate max-w-[300px]">{currentMessage}</span>
          )}
          {isComplete && outputFiles.length > 0 && outputFiles.map((f) => (
            <button
              key={f.filename}
              onClick={() => handleDownload(f.filename)}
              className="flex items-center gap-1 px-2 py-0.5 rounded bg-emerald-600 hover:bg-emerald-700
                         text-white text-xs transition-colors"
            >
              <Download size={10} />
              {t('run.download_file').replace('{file}', f.filename)}
            </button>
          ))}
          {isComplete && (
            <button
              onClick={handleDismiss}
              className="text-[#64748b] hover:text-[#94a3b8] transition-colors"
            >
              <X size={12} />
            </button>
          )}
        </div>
      </div>
      <div className="h-1 bg-[#1e293b] rounded-full overflow-hidden">
        <div
          className={`h-full rounded-full transition-all duration-500 ease-out ${
            hasError ? 'bg-red-500' : isComplete ? 'bg-emerald-500' : 'bg-blue-500'
          }`}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}
