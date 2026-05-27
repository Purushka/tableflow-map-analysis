/**
 * DataTable — reusable table component with sorting, filtering, and virtual scrolling.
 * Built on @tanstack/react-table + @tanstack/react-virtual.
 *
 * Uses spacer-row virtualisation so that <table> layout algorithm controls
 * column widths (no absolute positioning that breaks column alignment).
 */

// @refresh reset
import { useState, useMemo, useRef } from 'react';
import {
  useReactTable,
  getCoreRowModel,
  getSortedRowModel,
  getFilteredRowModel,
  flexRender,
  createColumnHelper,
  type SortingState,
  type ColumnFiltersState,
} from '@tanstack/react-table';
import { useVirtualizer } from '@tanstack/react-virtual';
import { ArrowUp, ArrowDown, Search, X } from 'lucide-react';

export interface DataTableProps {
  columns: string[];
  rows: Record<string, string>[];
  /** Columns to highlight as "new" (green) */
  highlightColumns?: string[];
  /** Total rows in source (may differ from rows.length if truncated) */
  totalRows?: number;
  /** If true, show row numbers */
  showRowNumbers?: boolean;
  /** If true, show column filter inputs */
  showFilters?: boolean;
  /** If true, show global search box */
  showSearch?: boolean;
  className?: string;
}

export default function DataTable({
  columns,
  rows,
  highlightColumns = [],
  totalRows,
  showRowNumbers = true,
  showFilters = false,
  showSearch = false,
  className = '',
}: DataTableProps) {
  const [sorting, setSorting] = useState<SortingState>([]);
  const [columnFilters, setColumnFilters] = useState<ColumnFiltersState>([]);
  const [globalFilter, setGlobalFilter] = useState('');
  const parentRef = useRef<HTMLDivElement>(null);

  const highlightSet = useMemo(() => new Set(highlightColumns), [highlightColumns]);

  const columnHelper = createColumnHelper<Record<string, string>>();

  const tableColumns = useMemo(() => {
    const cols = [];

    if (showRowNumbers) {
      cols.push(
        columnHelper.display({
          id: '__row_num',
          header: '#',
          size: 40,
          cell: (info) => info.row.index + 1,
        })
      );
    }

    for (const col of columns) {
      cols.push(
        columnHelper.accessor((row) => row[col] ?? '', {
          id: col,
          header: col,
          size: 150,
          cell: (info) => {
            const val = info.getValue();
            return <span title={val}>{val}</span>;
          },
        })
      );
    }

    return cols;
  }, [columns, showRowNumbers]);

  const table = useReactTable({
    data: rows,
    columns: tableColumns,
    state: { sorting, columnFilters, globalFilter },
    onSortingChange: setSorting,
    onColumnFiltersChange: setColumnFilters,
    onGlobalFilterChange: setGlobalFilter,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
  });

  const { rows: tableRows } = table.getRowModel();

  const virtualizer = useVirtualizer({
    count: tableRows.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => 24,
    overscan: 20,
  });

  const virtualItems = virtualizer.getVirtualItems();
  const totalColCount = tableColumns.length;

  // Spacer heights for proper virtualisation without position:absolute
  const topSpacerHeight = virtualItems.length > 0 ? virtualItems[0].start : 0;
  const bottomSpacerHeight =
    virtualItems.length > 0
      ? virtualizer.getTotalSize() -
        (virtualItems[virtualItems.length - 1].start +
          virtualItems[virtualItems.length - 1].size)
      : 0;

  return (
    <div className={`flex flex-col h-full overflow-hidden ${className}`}>
      {/* Search bar */}
      {showSearch && (
        <div className="shrink-0 px-2 py-1 border-b border-[#1e293b] flex items-center gap-2">
          <Search size={12} className="text-[#475569]" />
          <input
            type="text"
            value={globalFilter}
            onChange={(e) => setGlobalFilter(e.target.value)}
            placeholder="Search all columns..."
            className="flex-1 bg-transparent text-[11px] text-[#e2e8f0] outline-none placeholder-[#475569]"
          />
          {globalFilter && (
            <button onClick={() => setGlobalFilter('')} className="text-[#475569] hover:text-[#94a3b8]">
              <X size={12} />
            </button>
          )}
        </div>
      )}

      {/* Table */}
      <div ref={parentRef} className="flex-1 overflow-auto">
        <table className="w-full text-[11px]" style={{ tableLayout: 'fixed', borderCollapse: 'collapse' }}>
          {/* Explicit col widths so header + body always align */}
          <colgroup>
            {table.getAllColumns().map((col) => (
              <col
                key={col.id}
                style={{
                  width: col.id === '__row_num' ? 44 : col.getSize(),
                  minWidth: col.id === '__row_num' ? 44 : 80,
                }}
              />
            ))}
          </colgroup>

          <thead className="sticky top-0 bg-[#0f172a] z-10">
            {table.getHeaderGroups().map((headerGroup) => (
              <tr key={headerGroup.id}>
                {headerGroup.headers.map((header) => {
                  const isHighlight = highlightSet.has(header.id);
                  const canSort = header.column.getCanSort();
                  const sorted = header.column.getIsSorted();
                  return (
                    <th
                      key={header.id}
                      className={`px-2 py-1 text-left font-medium border-b whitespace-nowrap select-none overflow-hidden text-ellipsis ${
                        isHighlight
                          ? 'text-emerald-400 bg-emerald-400/5 border-emerald-900/30'
                          : 'text-[#94a3b8] border-[#1e293b]'
                      } ${canSort ? 'cursor-pointer hover:text-[#e2e8f0]' : ''}`}
                      onClick={header.column.getToggleSortingHandler()}
                    >
                      <div className="flex items-center gap-1">
                        {isHighlight && <span className="text-emerald-400">*</span>}
                        {flexRender(header.column.columnDef.header, header.getContext())}
                        {sorted === 'asc' && <ArrowUp size={10} />}
                        {sorted === 'desc' && <ArrowDown size={10} />}
                      </div>
                      {/* Column filter */}
                      {showFilters && header.id !== '__row_num' && (
                        <input
                          type="text"
                          value={(header.column.getFilterValue() as string) ?? ''}
                          onChange={(e) => header.column.setFilterValue(e.target.value || undefined)}
                          placeholder="..."
                          className="mt-0.5 w-full bg-[#1e293b] text-[9px] text-[#94a3b8] px-1 py-0 rounded outline-none border border-transparent focus:border-[#475569]"
                          onClick={(e) => e.stopPropagation()}
                        />
                      )}
                    </th>
                  );
                })}
              </tr>
            ))}
          </thead>

          <tbody>
            {/* Top spacer row — pushes visible rows to correct scroll offset */}
            {topSpacerHeight > 0 && (
              <tr aria-hidden="true">
                <td colSpan={totalColCount} style={{ height: topSpacerHeight, padding: 0, border: 'none' }} />
              </tr>
            )}

            {/* Visible virtual rows — normal table-row layout, no absolute */}
            {virtualItems.map((virtualRow) => {
              const row = tableRows[virtualRow.index];
              return (
                <tr key={row.id} className="hover:bg-[#1e293b]/50">
                  {row.getVisibleCells().map((cell) => {
                    const isHighlight = highlightSet.has(cell.column.id);
                    const val = String(cell.getValue() ?? '');
                    const hasValue = isHighlight && val !== '';
                    return (
                      <td
                        key={cell.id}
                        className={`px-2 py-0.5 border-b overflow-hidden text-ellipsis whitespace-nowrap ${
                          cell.column.id === '__row_num'
                            ? 'text-[#334155] border-[#1e293b]/30'
                            : hasValue
                            ? 'text-emerald-300 bg-emerald-400/5 border-emerald-900/10'
                            : isHighlight
                            ? 'text-[#475569] bg-emerald-400/[0.02] border-[#1e293b]/30'
                            : 'text-[#cbd5e1] border-[#1e293b]/30'
                        }`}
                      >
                        {flexRender(cell.column.columnDef.cell, cell.getContext())}
                      </td>
                    );
                  })}
                </tr>
              );
            })}

            {/* Bottom spacer row */}
            {bottomSpacerHeight > 0 && (
              <tr aria-hidden="true">
                <td colSpan={totalColCount} style={{ height: bottomSpacerHeight, padding: 0, border: 'none' }} />
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {/* Footer */}
      {totalRows !== undefined && totalRows > rows.length && (
        <div className="shrink-0 px-3 py-1 text-[10px] text-[#475569] text-center border-t border-[#1e293b]">
          Showing {rows.length} / {totalRows} rows
        </div>
      )}
    </div>
  );
}
