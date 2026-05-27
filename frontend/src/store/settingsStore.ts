import { create } from 'zustand';

export interface ProviderModel {
  id: string;
  label: string;
  provider: string;
  context_window: number;
}

export interface ProviderInfo {
  id: string;
  label: string;
  api_key_pattern: string;
  api_key_placeholder: string;
  models: ProviderModel[];
}

interface SettingsState {
  providers: ProviderInfo[];
  setProviders: (providers: ProviderInfo[]) => void;
  getApiKey: (providerId: string) => string;
  setApiKey: (providerId: string, key: string) => void;
  removeApiKey: (providerId: string) => void;
  getApiKeyForModel: (modelId: string) => string;
  getAllApiKeys: () => Record<string, string>;
  defaultModel: string;
  setDefaultModel: (modelId: string) => void;
}

const STORAGE_PREFIX = 'tableflow-api-key-';

export const useSettingsStore = create<SettingsState>((set, get) => ({
  providers: [],
  defaultModel: localStorage.getItem('tableflow-default-model') || '',

  setProviders: (providers) => set({ providers }),

  getApiKey: (providerId) => {
    return localStorage.getItem(`${STORAGE_PREFIX}${providerId}`) || '';
  },

  setApiKey: (providerId, key) => {
    localStorage.setItem(`${STORAGE_PREFIX}${providerId}`, key);
    // Force re-render by touching state
    set({});
  },

  removeApiKey: (providerId) => {
    localStorage.removeItem(`${STORAGE_PREFIX}${providerId}`);
    set({});
  },

  getApiKeyForModel: (modelId) => {
    const { providers, getApiKey } = get();
    for (const p of providers) {
      if (p.models.some((m) => m.id === modelId)) {
        return getApiKey(p.id);
      }
    }
    return '';
  },

  getAllApiKeys: () => {
    const { providers, getApiKey } = get();
    const keys: Record<string, string> = {};
    for (const p of providers) {
      const key = getApiKey(p.id);
      if (key) keys[p.id] = key;
    }
    return keys;
  },

  setDefaultModel: (modelId) => {
    localStorage.setItem('tableflow-default-model', modelId);
    set({ defaultModel: modelId });
  },
}));
