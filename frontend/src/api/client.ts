const BASE_URL = '';

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    headers: { 'Content-Type': 'application/json', ...options?.headers },
    ...options,
  });
  if (!res.ok) throw new Error(`API Error: ${res.status} ${res.statusText}`);
  return res.json();
}

// Files
export const uploadFile = async (file: File) => {
  const fd = new FormData();
  fd.append('file', file);
  const res = await fetch(`${BASE_URL}/api/files/upload`, { method: 'POST', body: fd });
  return res.json();
};

export const previewFile = (fileId: string, limit = 50) =>
  request<{ columns: string[]; rows: Record<string, any>[] }>(`/api/files/${fileId}/preview?limit=${limit}`);

export const getFileColumns = (fileId: string) =>
  request<{ columns: string[] }>(`/api/files/${fileId}/columns`);

// Nodes
export const getNodeTypes = () => request<any[]>('/api/nodes/types');
export const getDictionaries = () =>
  request<{ name: string; count: number }[]>('/api/nodes/dictionaries');
export const getNormalizeFunctions = () =>
  request<string[]>('/api/nodes/normalize-functions');

// Providers
export const getProviders = () => request<any[]>('/api/providers');
export const getModels = () => request<any[]>('/api/providers/models');

// Pipelines
export const listPipelines = () => request<any[]>('/api/pipelines');
export const getPipeline = (id: string) => request<any>(`/api/pipelines/${id}`);
export const createPipeline = (data: any) =>
  request<any>('/api/pipelines', { method: 'POST', body: JSON.stringify(data) });
export const updatePipeline = (id: string, data: any) =>
  request<any>(`/api/pipelines/${id}`, { method: 'PUT', body: JSON.stringify(data) });
export const deletePipeline = (id: string) =>
  request<any>(`/api/pipelines/${id}`, { method: 'DELETE' });

// Execution (SSE) - pass API keys per request
export const runPipelineSSE = async (id: string, apiKeys: Record<string, string> = {}): Promise<Response> => {
  return fetch(`${BASE_URL}/api/pipelines/${id}/run`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ api_keys: apiKeys }),
  });
};

export const getNodeResults = (pipelineId: string, nodeId: string) =>
  request<{ columns: string[]; rows: Record<string, any>[]; total: number }>(
    `/api/pipelines/${pipelineId}/results/${nodeId}`
  );

export const getOutputs = (pipelineId: string) =>
  request<{ filename: string; url: string }[]>(`/api/pipelines/${pipelineId}/outputs`);

// NL Parse - pass API key and model per request
export const parseNL = (
  text: string, nodeType: string, fieldName: string,
  columns: string[], apiKey: string = '', model: string = ''
) =>
  request<{ result: any; raw?: string; error?: string }>('/api/nl/parse', {
    method: 'POST',
    body: JSON.stringify({
      text, node_type: nodeType, field_name: fieldName,
      columns, api_key: apiKey, model,
    }),
  });
