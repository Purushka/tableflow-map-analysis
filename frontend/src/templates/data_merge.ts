import type { Template } from './index';

export const DATA_MERGE_TEMPLATE: Template = {
  id: 'data_merge',
  name: 'Data Merge',
  description: 'Load two CSV files, join on a key column, export merged result',
  category: 'general',
  nodes: [
    {
      id: 'n1', type: 'input_csv',
      position: { x: 50, y: 50 },
      data: { label: 'Left CSV', config: {} },
    },
    {
      id: 'n2', type: 'input_csv',
      position: { x: 50, y: 250 },
      data: { label: 'Right CSV', config: {} },
    },
    {
      id: 'n3', type: 'transform_merge',
      position: { x: 400, y: 140 },
      data: { label: 'Merge', config: { left_key: '', right_key: '', how: 'left' } },
    },
    {
      id: 'n4', type: 'output_xlsx',
      position: { x: 700, y: 140 },
      data: { label: 'Excel Output', config: { filename: 'merged.xlsx' } },
    },
  ],
  edges: [
    { id: 'e1', source: 'n1', sourceHandle: 'output', target: 'n3', targetHandle: 'left' },
    { id: 'e2', source: 'n2', sourceHandle: 'output', target: 'n3', targetHandle: 'right' },
    { id: 'e3', source: 'n3', sourceHandle: 'output', target: 'n4', targetHandle: 'input' },
  ],
};
