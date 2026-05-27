import type { Template } from './index';

export const AI_CLASSIFICATION_TEMPLATE: Template = {
  id: 'ai_classification',
  name: 'AI Classification',
  description: 'Load CSV, classify rows with AI, export results',
  category: 'ai',
  nodes: [
    {
      id: 'n1', type: 'input_csv',
      position: { x: 50, y: 100 },
      data: { label: 'CSV Input', config: {} },
    },
    {
      id: 'n2', type: 'ai_classify',
      position: { x: 350, y: 100 },
      data: {
        label: 'AI Classify',
        config: {
          model: '',
          prompt_template: 'Classify this item: {Title}',
          labels: 'Category A, Category B, Category C',
        },
      },
    },
    {
      id: 'n3', type: 'output_xlsx',
      position: { x: 650, y: 100 },
      data: { label: 'Excel Output', config: { filename: 'classified.xlsx' } },
    },
  ],
  edges: [
    { id: 'e1', source: 'n1', sourceHandle: 'output', target: 'n2', targetHandle: 'input' },
    { id: 'e2', source: 'n2', sourceHandle: 'output', target: 'n3', targetHandle: 'input' },
  ],
};
