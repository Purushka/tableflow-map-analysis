import type { Template } from './index';

export const CSV_CLEANUP_TEMPLATE: Template = {
  id: 'csv_cleanup',
  name: 'CSV Cleanup',
  description: 'Load a CSV, clean data, export to Excel',
  category: 'general',
  nodes: [
    {
      id: 'n1', type: 'input_csv',
      position: { x: 50, y: 100 },
      data: { label: 'CSV Input', config: {} },
    },
    {
      id: 'n2', type: 'transform_normalize',
      position: { x: 350, y: 100 },
      data: { label: 'Clean Data', config: { operations: '[]' } },
    },
    {
      id: 'n3', type: 'transform_deduplicate',
      position: { x: 650, y: 100 },
      data: { label: 'Deduplicate', config: { columns: '', keep: 'first' } },
    },
    {
      id: 'n4', type: 'output_xlsx',
      position: { x: 950, y: 100 },
      data: { label: 'Excel Output', config: { filename: 'cleaned.xlsx' } },
    },
  ],
  edges: [
    { id: 'e1', source: 'n1', sourceHandle: 'output', target: 'n2', targetHandle: 'input' },
    { id: 'e2', source: 'n2', sourceHandle: 'output', target: 'n3', targetHandle: 'input' },
    { id: 'e3', source: 'n3', sourceHandle: 'unique', target: 'n4', targetHandle: 'input' },
  ],
};
