export interface Template {
  id: string;
  name: string;
  description: string;
  category: 'general' | 'ai' | 'plugin';
  nodes: any[];
  edges: any[];
}

import { CSV_CLEANUP_TEMPLATE } from './csv_cleanup';
import { AI_CLASSIFICATION_TEMPLATE } from './ai_classification';
import { DATA_MERGE_TEMPLATE } from './data_merge';
import { RGSSA_TEMPLATE } from './rgssa';
import { AI_VISION_TEMPLATE } from './ai_vision_analysis';
import { AI_MAP_ANALYSIS_TEMPLATE } from './ai_map_analysis';

export const TEMPLATES: Template[] = [
  CSV_CLEANUP_TEMPLATE,
  AI_CLASSIFICATION_TEMPLATE,
  AI_VISION_TEMPLATE,
  AI_MAP_ANALYSIS_TEMPLATE,
  DATA_MERGE_TEMPLATE,
  { ...RGSSA_TEMPLATE, category: 'plugin' as const },
];
