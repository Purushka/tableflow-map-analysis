import { useState } from 'react';
import { usePipelineStore } from '../store/pipelineStore';
import { useT } from '../i18n/useI18n';
import { Table2, X, ChevronDown, ChevronUp, Download, AlertTriangle } from 'lucide-react';

export default function LivePreview() {
  const t = useT();
  const liveData = usePipelineStore((s) => s.livePreview);
  const isRunning = usePipelineStore((s) => s.isRunning);
  const [collapsed, setCollapsed] = useState(false);
  const [dismissed, setDismissed] = useState(false);

  // Only show when there's live data
  if (!liveData || dismissed) return null;

  const { columns, new_columns, rows, total_rows, processed_rows, node_label, partial_file } = liveData;
  const isProcessing = isRunning && processed_rows !== null && processed_rows < total_rows;

  const handleDownloadPartial = () => {
    if (partial_file) {
      window.open(`/api/files/${partial_file}/download`, '_blank');
    }
  };

  const handleDismiss = () => {
    setDismissed(true);
    usePipelineStore.getState().setLivePreview(null);
  };

  return (
    <div className="border-t border-[#334155] bg-[#0f172a] flex flex-col" style={{ maxHeight: collapsed ? '32px' : '280px' }}>
      {/* Header bar */}
      <div
        className="flex items-center justify-between px-3 py-1 cursor-pointer hover:bg-[#1e293b] transition-colors shrink-0"
        onClick={() => setCollapsed(!collapsed)}
      >
        <div className="flex items-center gap-2 text-xs">
          <Table2 size={12} className="text-blue-400" />
          <span className="text-[#e2e8f0] font-medium">
            {t('live.title')}: {node_label || ''}
          </span>
          {isProcessing && (
            <span className="text-blue-400 animate-pulse">
              ({processed_rows}/{total_rows})
            </span>
          )}
          {!isProcessing && total_rows > 0 && (
            <span className="text-[#64748b]">
              {total_rows} {t('pv.rows')} / {columns.length} {t('pv.cols')}
            </span>
          )}
          {new_columns.length > 0 && (
            <span className="text-emerald-400 text-[10px] px-1.5 py-0.5 bg-emerald-400/10 rounded">
              +{new_columns.length} {t('live.newCols')}
            </span>
          )}
          {partial_file && (
            <span className="flex items-center gap-1 text-amber-400 text-[10px] px-1.5 py-0.5 bg-amber-400/10 rounded">
              <AlertTriangle size={10} />
              {t('live.partial')}
            </span>
          )}
        </div>
        <div className="flex items-center gap-1">
          {partial_file && (
            <button
              onClick={(e) => { e.stopPropagation(); handleDownloadPartial(); }}
              className="flex items-center gap-1 px-2 py-0.5 text-[10px] bg-amber-500/20 text-amber-400
                         hover:bg-amber-500/30 rounded transition-colors"
            >
              <Download size={10} />
              {t('live.download')}
            </button>
          )}
          {collapsed ? <ChevronUp size={14} className="text-[#64748b]" /> : <ChevronDown size={14} className="text-[#64748b]" />}
          <button
            onClick={(e) => { e.stopPropagation(); handleDismiss(); }}
            className="p-0.5 hover:bg-[#334155] rounded"
          >
            <X size={12} className="text-[#64748b]" />
          </button>
        </div>
      </div>

      {/* Table */}
      {!collapsed && (
        <div className="flex-1 overflow-auto">
          {isProcessing && (
            <div className="h-0.5 bg-[#1e293b]">
              <div
                className="h-full bg-blue-500 transition-all duration-300"
                style={{ width: `${(processed_rows! / total_rows) * 100}%` }}
              />
            </div>
          )}
          <table className="w-full text-[11px]">
            <thead className="sticky top-0 bg-[#0f172a] z-10">
              <tr>
                <th className="px-2 py-1 text-left text-[#475569] font-medium border-b border-[#1e293b] w-8">#</th>
                {columns.map((col) => {
                  const isNew = new_columns.includes(col);
                  return (
                    <th
                      key={col}
                      className={`px-2 py-1 text-left font-medium border-b whitespace-nowrap ${
                        isNew
                          ? 'text-emerald-400 bg-emerald-400/5 border-emerald-900/30'
                          : 'text-[#94a3b8] border-[#1e293b]'
                      }`}
                    >
                      {isNew && <span className="mr-1">*</span>}
                      {col}
                    </th>
                  );
                })}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, i) => {
                const isProcessedBoundary = isProcessing && processed_rows !== null && i === Math.min(processed_rows - 1, rows.length - 1);
                return (
                  <tr
                    key={i}
                    className={`hover:bg-[#1e293b]/50 ${
                      isProcessedBoundary ? 'border-b-2 border-blue-500/50' : ''
                    }`}
                  >
                    <td className="px-2 py-0.5 text-[#334155] border-b border-[#1e293b]/30">{i + 1}</td>
                    {columns.map((col) => {
                      const isNew = new_columns.includes(col);
                      const val = String(row[col] ?? '');
                      const hasValue = isNew && val !== '';
                      return (
                        <td
                          key={col}
                          className={`px-2 py-0.5 border-b max-w-[180px] truncate ${
                            hasValue
                              ? 'text-emerald-300 bg-emerald-400/5 border-emerald-900/10'
                              : isNew
                              ? 'text-[#475569] bg-emerald-400/[0.02] border-[#1e293b]/30'
                              : 'text-[#cbd5e1] border-[#1e293b]/30'
                          }`}
                          title={val}
                        >
                          {val}
                        </td>
                      );
                    })}
                  </tr>
                );
              })}
            </tbody>
          </table>
          {rows.length < total_rows && (
            <div className="px-3 py-1 text-[10px] text-[#475569] text-center">
              {t('live.showing')} {rows.length} / {total_rows}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
