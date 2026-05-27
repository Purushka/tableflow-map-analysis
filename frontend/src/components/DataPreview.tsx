import { useState, useEffect } from 'react';
import { getNodeResults } from '../api/client';
import { usePipelineStore } from '../store/pipelineStore';
import { useT } from '../i18n/useI18n';
import { X, Table2 } from 'lucide-react';
import DataTable from './DataTable';

interface DataPreviewProps {
  nodeId: string;
  onClose: () => void;
}

export default function DataPreview({ nodeId, onClose }: DataPreviewProps) {
  const t = useT();
  const pipelineId = usePipelineStore((s) => s.pipelineId);
  const nodes = usePipelineStore((s) => s.nodes);
  const node = nodes.find((n) => n.id === nodeId);

  const [data, setData] = useState<{ columns: string[]; rows: any[]; total: number } | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!pipelineId) {
      setError(t('pv.notSaved'));
      setLoading(false);
      return;
    }
    setLoading(true);
    getNodeResults(pipelineId, nodeId)
      .then((result) => {
        if ('error' in result) {
          setError((result as any).error);
        } else {
          setData(result);
        }
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [pipelineId, nodeId]);

  return (
    <div className="fixed inset-0 bg-black/60 z-50 flex items-center justify-center p-8">
      <div className="bg-[#1e293b] rounded-lg border border-[#334155] w-full max-w-5xl max-h-[80vh] flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-[#334155]">
          <div className="flex items-center gap-2">
            <Table2 size={16} className="text-blue-400" />
            <span className="text-sm font-semibold text-white">
              {t('pv.title')}: {node?.data.label as string || nodeId}
            </span>
            {data && (
              <span className="text-xs text-[#64748b] ml-2">
                {data.total} {t('pv.rows')} / {data.columns.length} {t('pv.cols')}
              </span>
            )}
          </div>
          <button onClick={onClose} className="p-1 hover:bg-[#334155] rounded">
            <X size={16} className="text-[#94a3b8]" />
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-hidden">
          {loading && (
            <div className="p-8 text-center text-[#94a3b8] text-sm">{t('pv.loading')}</div>
          )}
          {error && (
            <div className="p-8 text-center text-red-400 text-sm">{error}</div>
          )}
          {data && (
            <DataTable
              columns={data.columns}
              rows={data.rows}
              totalRows={data.total}
              showSearch
              showFilters
            />
          )}
        </div>
      </div>
    </div>
  );
}
