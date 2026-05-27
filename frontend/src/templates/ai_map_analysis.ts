import type { Template } from './index';

export const AI_MAP_ANALYSIS_TEMPLATE: Template = {
  id: 'ai_map_analysis',
  name: 'AI Map Analysis (3-Level)',
  description: 'Load map scans → 3-level AI analysis (scan → read text → explore map body) → standardized catalogue fields → Excel',
  category: 'ai',
  nodes: [
    {
      id: 'n1', type: 'input_images',
      position: { x: 50, y: 300 },
      data: { label: 'Map Scans', config: { max_images: 0 } },
    },
    {
      id: 'n2', type: 'ai_map_analysis',
      position: { x: 350, y: 300 },
      data: {
        label: 'AI Map Analysis',
        config: {
          mode: 'multilevel',
          model: '',
          image_column: 'file_path',
          max_tokens: 50000,
          concurrency: 0,
        },
      },
    },
    {
      id: 'n3', type: 'output_xlsx',
      position: { x: 650, y: 300 },
      data: { label: 'Excel Output', config: { filename: 'map_analysis.xlsx' } },
    },
  ],
  edges: [
    { id: 'e1', source: 'n1', sourceHandle: 'output', target: 'n2', targetHandle: 'input' },
    { id: 'e2', source: 'n2', sourceHandle: 'output', target: 'n3', targetHandle: 'input' },
  ],
};
