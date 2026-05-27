import type { Template } from './index';

export const AI_VISION_TEMPLATE: Template = {
  id: 'ai_vision_analysis',
  name: 'AI Vision Analysis',
  description: 'Load images from ZIP, analyze with vision AI, export structured results',
  category: 'ai',
  nodes: [
    {
      id: 'n1', type: 'input_images',
      position: { x: 50, y: 300 },
      data: { label: 'Image Loader', config: { max_images: 0 } },
    },
    {
      id: 'n2', type: 'ai_vision',
      position: { x: 350, y: 300 },
      data: {
        label: 'AI Vision Analysis',
        config: {
          model: '',
          image_column: 'file_path',
          system_prompt: 'You are an image analysis assistant. Analyze the provided image and extract structured information. Return JSON only, no markdown.',
          user_prompt_template: 'Analyze this image.\nFilename: {filename}\n\nReturn JSON: {"description":"","objects":"","text_content":"","dominant_colors":""}',
          json_field_mapping: JSON.stringify({
            description: "description",
            objects: "objects",
            text_content: "text_content",
            dominant_colors: "dominant_colors",
          }),
          max_tokens: 2000,
          concurrency: 0,
        },
      },
    },
    {
      id: 'n3', type: 'output_xlsx',
      position: { x: 650, y: 300 },
      data: { label: 'Excel Output', config: { filename: 'vision_results.xlsx' } },
    },
  ],
  edges: [
    { id: 'e1', source: 'n1', sourceHandle: 'output', target: 'n2', targetHandle: 'input' },
    { id: 'e2', source: 'n2', sourceHandle: 'output', target: 'n3', targetHandle: 'input' },
  ],
};
